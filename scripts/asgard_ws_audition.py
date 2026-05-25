#!/usr/bin/env python3
"""WebSocket audition harness — text-streamed-in / audio-streamed-out.

Simulates an LLM trickling tokens into voice-forge's ``WS /v1/tts/stream``
endpoint and captures the streamed audio + protocol timing into a
browser-playable HTML index. Sibling to ``scripts/asgard_audition.py``
(which audits the HTTP REST surface).

What this surface measures that the HTTP harness can't:

- **first-text-token → first-audio-byte latency** (the layer-2 win):
  HTTP synth assumes the input is known up-front, so first-audio is
  bounded by "synth(first_chunk_of_known_text)". WS synth begins as soon
  as the FIRST complete sentence arrives in the trickle, so first-audio
  is bounded by "synth(first_sentence)" — independent of how slow the
  upstream LLM is producing the rest.

The output WAV is the concatenation of every binary PCM frame the server
pushes; listening to it confirms quality matches batch synth. The HTML
index surfaces the first-audio latency next to the player so you can
A/B against the HTTP layer-1 results in a separate browser tab.
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as _dt
import html as _html
import http.client
import json
import shutil
import signal
import subprocess
import sys
import time
import wave
from pathlib import Path
from typing import Any

import numpy as np
import websockets
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
FUNCTIONAL_DIR = REPO_ROOT / "tests" / "functional"
DEFAULT_FLEET = FUNCTIONAL_DIR / "streaming_test_fleet.yaml"
DEFAULT_PROMPTS = FUNCTIONAL_DIR / "prompts.yaml"
DEFAULT_RESPONSES = FUNCTIONAL_DIR / "responses.yaml"
DEFAULT_OUTPUT_BASE = FUNCTIONAL_DIR / "output"

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 9876
HEALTH_TIMEOUT_SEC = 60  # cold model load can take ~30-45s
HEALTH_POLL_INTERVAL_SEC = 1.0

# LLM-trickle parameters. Approximates a GPT-3.5-class token rate
# (~50 chars/sec). Tunable per-row if needed; defaults give a realistic
# "the upstream is still typing" experience.
DEFAULT_TOKEN_SIZE = 12  # chars per text frame
DEFAULT_TOKEN_INTERVAL_S = 0.04  # 40 ms between text frames


def _load_yaml(path: Path) -> Any:
    if not path.is_file():
        raise SystemExit(f"error: missing input file {path}")
    return yaml.safe_load(path.read_text())


def _wait_for_health(host: str, port: int, timeout_sec: float) -> None:
    deadline = time.monotonic() + timeout_sec
    last_err: Exception | None = None
    while time.monotonic() < deadline:
        try:
            conn = http.client.HTTPConnection(host, port, timeout=5)
            conn.request("GET", "/health")
            resp = conn.getresponse()
            if resp.status == 200:
                return
            last_err = RuntimeError(f"health returned status {resp.status}")
        except (ConnectionRefusedError, OSError) as exc:
            last_err = exc
        finally:
            try:
                conn.close()  # type: ignore[name-defined]
            except Exception:
                pass
        time.sleep(HEALTH_POLL_INTERVAL_SEC)
    raise SystemExit(
        f"error: voice-forge serve did not become healthy on {host}:{port} "
        f"within {timeout_sec}s (last error: {last_err!r})"
    )


def _start_server(host: str, port: int) -> subprocess.Popen:
    voice_forge = shutil.which("voice-forge")
    if voice_forge is None:
        raise SystemExit(
            "error: `voice-forge` not found on PATH. Install with "
            '`uv pip install "voice-forge-tts[neutts,voice-lab]"`'
        )
    print(f"starting `voice-forge serve --host {host} --port {port}` in the background...")
    return subprocess.Popen(
        [voice_forge, "serve", "--host", host, "--port", str(port)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )


def _stop_server(proc: subprocess.Popen) -> None:
    print("stopping background voice-forge server...")
    proc.send_signal(signal.SIGTERM)
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()


def _fill_template(template: str, sister_id: str, prompt_id: str, responses: dict) -> str | None:
    if "{response_p2}" in template:
        text = responses.get(sister_id, {}).get("p2")
        return template.replace("{response_p2}", text) if text else None
    if "{response_p3}" in template:
        text = responses.get(sister_id, {}).get("p3")
        return template.replace("{response_p3}", text) if text else None
    return template


def _pcm_to_wav(pcm_float32: np.ndarray, sample_rate: int, output_path: Path) -> None:
    """Concatenated float32 PCM → 16-bit mono WAV at sample_rate."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    samples = np.clip(pcm_float32 * 32_767.0, -32_768, 32_767).astype(np.int16)
    with wave.open(str(output_path), "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(sample_rate)
        f.writeframes(samples.tobytes())


async def _stream_one_row(
    host: str,
    port: int,
    voice_id: str,
    text: str,
    wav_path: Path,
    token_size: int,
    token_interval_s: float,
) -> dict:
    """Open WS, trickle text in token-by-token, drain audio out, write WAV.

    Returns a timing dict the HTML rendering layer surfaces to the user:

        first_text_sent_ms   — wall-time from connect to first {"text": ...} sent
        first_audio_received_ms — wall-time from connect to first binary frame
                                  (the actual layer-2 latency win — this is what
                                  layer-1 cannot beat in a token-stream context)
        last_text_sent_ms    — when the trickle finished
        total_ms             — when the server sent the 'complete' frame
        sentences            — how many sentences the server synth'd
        bytes                — size of the assembled WAV on disk
    """
    uri = f"ws://{host}:{port}/v1/tts/stream"
    timings: dict[str, Any] = {
        "first_text_sent_ms": None,
        "first_audio_received_ms": None,
        "last_text_sent_ms": None,
        "total_ms": None,
        "sentences": 0,
        "bytes": 0,
    }
    # 64 MiB max_size keeps the long-narrative rows (p3 ~ 4 MB) comfortable.
    async with websockets.connect(uri, max_size=64 * 1024 * 1024) as ws:
        await ws.send(json.dumps({"voice": voice_id}))
        session_msg = json.loads(await ws.recv())
        if session_msg.get("event") != "session":
            raise RuntimeError(f"unexpected first frame from server: {session_msg!r}")
        sample_rate = int(session_msg["sample_rate"])

        connect_t0 = time.monotonic()

        async def _trickle() -> None:
            """Send text in token-sized bursts with token_interval_s gaps."""
            chunks = [text[i : i + token_size] for i in range(0, len(text), token_size)]
            if not chunks:
                await ws.send(json.dumps({"end": True}))
                timings["last_text_sent_ms"] = (time.monotonic() - connect_t0) * 1000
                return
            for i, chunk in enumerate(chunks):
                is_last = i == len(chunks) - 1
                msg: dict[str, Any] = {"text": chunk}
                if is_last:
                    msg["end"] = True
                await ws.send(json.dumps(msg))
                if timings["first_text_sent_ms"] is None:
                    timings["first_text_sent_ms"] = (time.monotonic() - connect_t0) * 1000
                if is_last:
                    timings["last_text_sent_ms"] = (time.monotonic() - connect_t0) * 1000
                else:
                    await asyncio.sleep(token_interval_s)

        trickle_task = asyncio.create_task(_trickle())
        pcm_frames: list[np.ndarray] = []
        sentence_count = 0
        try:
            while True:
                msg = await ws.recv()
                if isinstance(msg, (bytes, bytearray)):
                    if timings["first_audio_received_ms"] is None:
                        timings["first_audio_received_ms"] = (time.monotonic() - connect_t0) * 1000
                    pcm_frames.append(np.frombuffer(msg, dtype=np.float32))
                else:
                    event = json.loads(msg)
                    ev = event.get("event")
                    if ev == "sentence_done":
                        sentence_count += 1
                    elif ev == "complete":
                        timings["sentences"] = sentence_count
                        timings["total_ms"] = (time.monotonic() - connect_t0) * 1000
                        break
                    elif ev == "error":
                        raise RuntimeError(f"server error: {event.get('detail')!r}")
        finally:
            await trickle_task

        if pcm_frames:
            full = np.concatenate(pcm_frames)
            _pcm_to_wav(full, sample_rate, wav_path)
            timings["bytes"] = wav_path.stat().st_size
    return timings


def _render_html(
    output_dir: Path,
    fleet: list[dict],
    prompts: list[dict],
    responses: dict,
    results: dict,
) -> Path:
    """Render an index.html with one <audio> per row + layer-2 timing column."""
    title = f"voice-forge WS audition — {output_dir.name}"
    rows: list[str] = []
    rows.append(
        '<p class="legend">'
        "Each row simulates an LLM trickling text into the WS endpoint at "
        "~50 chars/sec. <b>first-audio</b> is the wall-time from connect "
        "to first PCM byte from the server — that's the layer-2 win. "
        "Compare against the HTTP layer-1 numbers in the sibling "
        "<code>streaming-ab-*/</code> and <code>streaming-f5-tuned-*/</code> "
        "directories to see how a token-streamed input changes the picture."
        "</p>"
    )
    for sister in fleet:
        captured = responses.get(sister["id"], {}).get("captured", "?")
        rows.append(
            f"<h2>{_html.escape(sister['display_name'])} "
            f"<small>(voice_id={_html.escape(sister['voice_id'])}, "
            f"backend={_html.escape(sister['backend'])}, "
            f"captured={_html.escape(captured)})</small></h2>"
        )
        rows.append("<table>")
        rows.append(
            "<tr><th>prompt</th><th>WS audio</th>"
            "<th>first audio (since connect)</th>"
            "<th>sentences</th><th>note</th></tr>"
        )
        for prompt in prompts:
            key = (sister["voice_id"], prompt["id"])
            result = results.get(key, {})
            note = _html.escape(prompt.get("note", ""))
            rows.append("<tr>")
            rows.append(f"<td class=\"prompt-id\"><code>{_html.escape(prompt['id'])}</code></td>")
            wav_name = result.get("wav_name")
            if wav_name:
                first_audio = result.get("first_audio_received_ms")
                total = result.get("total_ms")
                sentences = result.get("sentences", 0)
                first_text = result.get("first_text_sent_ms") or 0
                rows.append(f'<td><audio controls src="{_html.escape(wav_name)}"></audio></td>')
                latency_cell = (
                    f"{first_audio:.0f} ms"
                    if first_audio is not None
                    else "<span class='missing'>—</span>"
                )
                latency_cell += (
                    f"<br><small>(first text sent at {first_text:.0f} ms; "
                    f"total {total:.1f} ms)</small>"
                )
                rows.append(f"<td>{latency_cell}</td>")
                rows.append(f"<td>{sentences}</td>")
            else:
                status = result.get("status", "?")
                rows.append(f'<td class="missing">{_html.escape(status)}</td>')
                rows.append("<td></td><td></td>")
            rows.append(f"<td class='note'>{note}</td>")
            rows.append("</tr>")
        rows.append("</table>")

    body = "\n".join(rows)
    html = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{_html.escape(title)}</title>
<style>
body {{ font-family: -apple-system, BlinkMacSystemFont, sans-serif;
       max-width: 1100px; margin: 2em auto; padding: 0 1em; color: #222; }}
h1 {{ border-bottom: 2px solid #ccc; padding-bottom: 0.3em; }}
h2 {{ margin-top: 2em; }}
h2 small {{ color: #888; font-weight: normal; font-size: 0.6em; }}
table {{ width: 100%; border-collapse: collapse; }}
th, td {{ padding: 0.4em 0.5em; vertical-align: middle;
         border-bottom: 1px solid #eee; text-align: left; }}
td.prompt-id {{ width: 11em; }}
td.missing {{ color: #b22; font-style: italic; }}
td.note {{ color: #666; font-size: 0.9em; }}
audio {{ width: 320px; }}
.legend {{ background: #f5f5f5; padding: 0.6em 1em; border-radius: 4px; margin: 1em 0; }}
small {{ color: #777; }}
</style>
</head>
<body>
<h1>{_html.escape(title)}</h1>
{body}
</body>
</html>
"""
    out_path = output_dir / "index.html"
    out_path.write_text(html)
    return out_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fleet", type=Path, default=DEFAULT_FLEET)
    parser.add_argument("--prompts", type=Path, default=DEFAULT_PROMPTS)
    parser.add_argument("--responses", type=Path, default=DEFAULT_RESPONSES)
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help=f"Output dir for WAVs + index.html (default: {DEFAULT_OUTPUT_BASE}/ws-<UTC>)",
    )
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument(
        "--token-size",
        type=int,
        default=DEFAULT_TOKEN_SIZE,
        help=f"Chars per simulated LLM token (default: {DEFAULT_TOKEN_SIZE})",
    )
    parser.add_argument(
        "--token-interval-ms",
        type=int,
        default=int(DEFAULT_TOKEN_INTERVAL_S * 1000),
        help=f"Inter-token delay in ms (default: {int(DEFAULT_TOKEN_INTERVAL_S * 1000)})",
    )
    parser.add_argument(
        "--skip-server",
        action="store_true",
        help="Assume a voice-forge server is already running on host:port",
    )
    args = parser.parse_args(argv)

    fleet = _load_yaml(args.fleet)
    prompts = _load_yaml(args.prompts)
    responses = _load_yaml(args.responses)
    if not isinstance(fleet, list) or not fleet:
        raise SystemExit(f"error: {args.fleet} is empty or not a list")
    if not isinstance(prompts, list) or not prompts:
        raise SystemExit(f"error: {args.prompts} is empty or not a list")

    output_dir = args.output or (
        DEFAULT_OUTPUT_BASE / ("ws-" + _dt.datetime.now(_dt.UTC).strftime("%Y%m%dT%H%M%SZ"))
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    print(f"output dir: {output_dir}")

    server_proc: subprocess.Popen | None = None
    if not args.skip_server:
        server_proc = _start_server(args.host, args.port)
    try:
        _wait_for_health(args.host, args.port, HEALTH_TIMEOUT_SEC)
        print(f"server healthy on {args.host}:{args.port}; starting WS synth loop")

        results: dict[tuple[str, str], dict] = {}
        token_interval_s = args.token_interval_ms / 1000.0
        for sister in fleet:
            voice_id = sister["voice_id"]
            for prompt in prompts:
                key = (voice_id, prompt["id"])
                text = _fill_template(prompt["template"], sister["id"], prompt["id"], responses)
                if text is None:
                    results[key] = {"status": "(no response cached)"}
                    print(f"  {voice_id}/{prompt['id']}: SKIP (no response cached)")
                    continue
                wav_name = f"{voice_id}_{prompt['id']}.wav"
                wav_path = output_dir / wav_name
                print(f"  {voice_id}/{prompt['id']}: WS-streaming ({len(text)} chars) ...")
                try:
                    info = asyncio.run(
                        _stream_one_row(
                            args.host,
                            args.port,
                            voice_id,
                            text,
                            wav_path,
                            args.token_size,
                            token_interval_s,
                        )
                    )
                except Exception as exc:  # surface row failure but keep going
                    results[key] = {"status": f"fail: {exc!r}"}
                    print(f"    -> FAIL: {exc!r}")
                    continue
                results[key] = {
                    "status": "ok",
                    "wav_name": wav_name,
                    **info,
                }
                first_audio = info["first_audio_received_ms"]
                first_text = info["first_text_sent_ms"] or 0
                print(
                    f"    -> {info['bytes']:,} bytes, "
                    f"{info['sentences']} sentence(s); "
                    f"first text sent {first_text:.0f} ms, "
                    f"first audio {first_audio:.0f} ms"
                    f" (gap {first_audio - first_text:.0f} ms)"
                )

        index_path = _render_html(output_dir, fleet, prompts, responses, results)
        print(f"\nindex written to {index_path}")
        print(f"open it: open {index_path}" if sys.platform == "darwin" else f"open {index_path}")
        successes = sum(1 for r in results.values() if r.get("status") == "ok")
        print(f"streamed {successes}/{len(results)} rows")
        return 0 if successes > 0 else 1
    finally:
        if server_proc is not None:
            _stop_server(server_proc)


if __name__ == "__main__":
    sys.exit(main())

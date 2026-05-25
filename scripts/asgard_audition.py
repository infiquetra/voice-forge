#!/usr/bin/env python3
"""Asgard audition harness — ear-driven verification of the sister voice fleet.

Synthesizes 3 prompts per sister against a locally running voice-forge server,
writes the resulting WAVs to a timestamped output directory, and generates an
HTML index with ``<audio controls>`` rows so the user can click through each
sister's three audio samples in a browser.

This is intentionally a *manual* tool — not pytest-runnable. The output is
auditioned by ear; what counts as a regression is the kind of timbre /
coherence / prosody drift that line coverage cannot catch.

See ``tests/functional/README.md`` for the full review procedure (what to
listen for per prompt, including the documented NeuTTS 30-second cliff).
"""

from __future__ import annotations

import argparse
import datetime as _dt
import html as _html
import http.client
import json
import shutil
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
FUNCTIONAL_DIR = REPO_ROOT / "tests" / "functional"
DEFAULT_FLEET = FUNCTIONAL_DIR / "fleet.yaml"
DEFAULT_PROMPTS = FUNCTIONAL_DIR / "prompts.yaml"
DEFAULT_RESPONSES = FUNCTIONAL_DIR / "responses.yaml"
DEFAULT_OUTPUT_BASE = FUNCTIONAL_DIR / "output"

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 9876
HEALTH_TIMEOUT_SEC = 60  # cold model load can take ~30-45s
HEALTH_POLL_INTERVAL_SEC = 1.0


def _load_yaml(path: Path) -> Any:
    if not path.is_file():
        raise SystemExit(f"error: missing input file {path}")
    with path.open() as f:
        return yaml.safe_load(f)


def _wait_for_health(host: str, port: int, timeout_sec: float) -> None:
    """Poll GET /health until 200 or timeout. Raises SystemExit on timeout."""
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
    """Start `voice-forge serve` as a background subprocess."""
    voice_forge = shutil.which("voice-forge")
    if voice_forge is None:
        raise SystemExit(
            "error: `voice-forge` not found on PATH. Install it: "
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
    """Substitute {response_p2} / {response_p3} from responses.yaml, or return None if missing."""
    if "{response_p2}" in template:
        text = responses.get(sister_id, {}).get("p2")
        return template.replace("{response_p2}", text) if text else None
    if "{response_p3}" in template:
        text = responses.get(sister_id, {}).get("p3")
        return template.replace("{response_p3}", text) if text else None
    return template


def _synthesize(
    host: str,
    port: int,
    voice_id: str,
    text: str,
    output_path: Path,
    stream: bool = False,
) -> tuple[bool, dict]:
    """POST /v1/audio/speech, write WAV to output_path.

    Returns (success, info_dict). info_dict has:
        bytes: total response size
        total_s: wall-clock from request-send to last byte
        first_audio_ms: time from request-send to first PCM byte
                        (after the 44-byte WAV header; only meaningful when stream=true,
                        but recorded for batch too as a baseline)
    """
    import time

    body = json.dumps(
        {
            "model": "voice-forge",
            "input": text,
            "voice": voice_id,
            "response_format": "wav",
            "stream": stream,
        }
    ).encode()
    req = urllib.request.Request(
        f"http://{host}:{port}/v1/audio/speech",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    info: dict = {"bytes": 0, "total_s": 0.0, "first_audio_ms": 0.0}
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=600) as resp:
            chunks: list[bytes] = []
            running_size = 0
            first_pcm_seen = False
            # Standard WAV header is 44 bytes; the server's streaming header
            # also writes 44 bytes (RIFF + fmt + data). Anything past that
            # counts as first PCM byte.
            WAV_HEADER_LEN = 44
            while True:
                # 8 KiB reads — small enough to see first-byte arrival quickly
                buf = resp.read(8192)
                if not buf:
                    break
                chunks.append(buf)
                running_size += len(buf)
                if not first_pcm_seen and running_size > WAV_HEADER_LEN:
                    info["first_audio_ms"] = (time.monotonic() - t0) * 1000
                    first_pcm_seen = True
        audio_bytes = b"".join(chunks)
        # Belt-and-suspenders: if a sibling process raced and removed the
        # output dir between main()'s mkdir and now, re-create before write.
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(audio_bytes)
        info["bytes"] = len(audio_bytes)
        info["total_s"] = time.monotonic() - t0
        return True, info
    except urllib.error.HTTPError as exc:
        info["error"] = f"HTTP {exc.code}: {exc.read().decode(errors='replace')[:200]}"
        return False, info
    except (urllib.error.URLError, TimeoutError) as exc:
        info["error"] = f"network error: {exc!r}"
        return False, info


def _columns_for_mode(mode: str) -> list[str]:
    """Map --mode flag to the list of columns rendered + synthesized.

    ``batch``  → one batch column
    ``stream`` → one stream column
    ``both``   → batch + stream side-by-side
    """
    if mode == "batch":
        return ["batch"]
    if mode == "stream":
        return ["stream"]
    return ["batch", "stream"]


def _render_html(
    output_dir: Path,
    fleet: list[dict],
    prompts: list[dict],
    responses: dict,
    results: dict,
    mode: str = "batch",
) -> Path:
    """Generate an index.html with grouped <audio controls> rows.

    When ``mode == 'both'``, each row gets two audio columns: batch | stream,
    so reviewers can A/B compare them directly. Latency stats (first-audio-ms
    and total-synth-seconds) appear next to each player.
    """
    title = f"voice-forge audition — {output_dir.name}"
    columns = _columns_for_mode(mode)
    rows = []
    for sister in fleet:
        captured = responses.get(sister["id"], {}).get("captured", "?")
        rows.append(
            f'<h2>{_html.escape(sister["display_name"])} '
            f'<small>(voice_id={_html.escape(sister["voice_id"])}, '
            f'target_agent={_html.escape(sister["target_agent"])}, '
            f"captured={_html.escape(captured)})</small></h2>"
        )
        rows.append("<table>")
        # Header row when we have both columns
        if len(columns) > 1:
            rows.append("<tr><th>prompt</th>")
            for col in columns:
                rows.append(f"<th>{_html.escape(col)}</th>")
            rows.append("<th>note</th></tr>")
        for prompt in prompts:
            note = _html.escape(prompt.get("note", ""))
            rows.append("<tr>")
            rows.append(f'<td class="prompt-id"><code>{_html.escape(prompt["id"])}</code></td>')
            for col in columns:
                key = (sister["voice_id"], prompt["id"], col)
                result = results.get(key, {})
                wav_name = result.get("wav_name")
                if wav_name:
                    latency = ""
                    if result.get("first_audio_ms") is not None:
                        latency = (
                            f"<br><small>first audio: "
                            f"{result['first_audio_ms']:.0f} ms · "
                            f"total: {result['total_s']:.1f} s</small>"
                        )
                    rows.append(
                        f'<td><audio controls src="{_html.escape(wav_name)}"></audio>{latency}</td>'
                    )
                else:
                    status = result.get("status", "?")
                    rows.append(f'<td class="missing">{_html.escape(status)}</td>')
            rows.append(f'<td class="note">{note}</td>')
            rows.append("</tr>")
        rows.append("</table>")
    body = "\n".join(rows)
    html = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{_html.escape(title)}</title>
<style>
body {{ font-family: -apple-system, BlinkMacSystemFont, sans-serif; max-width: 960px;
       margin: 2em auto; padding: 0 1em; color: #222; }}
h1 {{ border-bottom: 2px solid #ccc; padding-bottom: 0.3em; }}
h2 {{ margin-top: 2em; }}
h2 small {{ color: #888; font-weight: normal; font-size: 0.6em; }}
table {{ width: 100%; border-collapse: collapse; }}
td {{ padding: 0.4em 0.5em; vertical-align: middle; border-bottom: 1px solid #eee; }}
td.prompt-id {{ width: 12em; }}
td.missing {{ color: #b22; font-style: italic; }}
td.note {{ color: #666; font-size: 0.9em; }}
audio {{ width: 320px; }}
.legend {{ background: #f5f5f5; padding: 0.6em 1em; border-radius: 4px; margin: 1em 0; }}
</style>
</head>
<body>
<h1>{_html.escape(title)}</h1>
<p class="legend">
9 sisters × 3 prompts = 27 audio rows. Click each row to play.
<br>p1 should be clean. p2 will show the NeuTTS 30-second cliff on NeuTTS sisters
(that's expected). p3 should sound like the persona and mention target_agent.
See <code>tests/functional/README.md</code> for full review notes.
</p>
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
        help=f"Output dir for WAVs + index.html "
        f"(default: {DEFAULT_OUTPUT_BASE}/<UTC timestamp>)",
    )
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument(
        "--mode",
        choices=("batch", "stream", "both"),
        default="batch",
        help=(
            "Which synth path to exercise. 'batch' (default) hits "
            "/v1/audio/speech with stream=false; 'stream' uses stream=true; "
            "'both' does each row twice and renders a side-by-side HTML so "
            "you can A/B compare audio quality + first-byte latency."
        ),
    )
    parser.add_argument(
        "--skip-server",
        action="store_true",
        help="Don't start/stop a server subprocess; assume one is already running.",
    )
    args = parser.parse_args(argv)

    fleet = _load_yaml(args.fleet)
    prompts = _load_yaml(args.prompts)
    responses = _load_yaml(args.responses) or {}

    if not isinstance(fleet, list) or not fleet:
        raise SystemExit(f"error: {args.fleet} is empty or not a list")
    if not isinstance(prompts, list) or not prompts:
        raise SystemExit(f"error: {args.prompts} is empty or not a list")

    output_dir = args.output or (
        DEFAULT_OUTPUT_BASE / _dt.datetime.now(_dt.UTC).strftime("%Y%m%dT%H%M%SZ")
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    print(f"output dir: {output_dir}")

    server_proc: subprocess.Popen | None = None
    if not args.skip_server:
        server_proc = _start_server(args.host, args.port)
    try:
        _wait_for_health(args.host, args.port, HEALTH_TIMEOUT_SEC)
        print(f"server healthy on {args.host}:{args.port}; starting synth loop")

        # Modes: "batch" = one pass non-streaming, "stream" = one streaming pass,
        # "both" = each row gets both, results keyed by (voice_id, prompt_id, mode).
        cols = (
            ["batch"]
            if args.mode == "batch"
            else ["stream"] if args.mode == "stream" else ["batch", "stream"]
        )
        results: dict[tuple[str, str, str], dict] = {}
        for sister in fleet:
            voice_id = sister["voice_id"]
            for prompt in prompts:
                text = _fill_template(prompt["template"], sister["id"], prompt["id"], responses)
                if text is None:
                    for col in cols:
                        results[(voice_id, prompt["id"], col)] = {"status": "(no response cached)"}
                    print(f"  {voice_id}/{prompt['id']}: SKIP (no response cached)")
                    continue
                for col in cols:
                    key = (voice_id, prompt["id"], col)
                    suffix = "" if args.mode == "batch" else f"_{col}"
                    wav_name = f"{voice_id}_{prompt['id']}{suffix}.wav"
                    wav_path = output_dir / wav_name
                    print(f"  {voice_id}/{prompt['id']}/{col}: synthesizing ...")
                    ok, info = _synthesize(
                        args.host,
                        args.port,
                        voice_id,
                        text,
                        wav_path,
                        stream=(col == "stream"),
                    )
                    if ok:
                        results[key] = {
                            "status": "ok",
                            "wav_name": wav_name,
                            "first_audio_ms": info["first_audio_ms"],
                            "total_s": info["total_s"],
                        }
                        print(
                            f"    -> {info['bytes']:,} bytes, "
                            f"first audio {info['first_audio_ms']:.0f} ms, "
                            f"total {info['total_s']:.1f} s"
                        )
                    else:
                        results[key] = {"status": info.get("error", "fail")}
                        print(f"    -> FAIL: {info.get('error')}")

        index_path = _render_html(output_dir, fleet, prompts, responses, results, mode=args.mode)
        print(f"\nindex written to {index_path}")
        print(f"open it: open {index_path}" if sys.platform == "darwin" else f"open {index_path}")
        successes = sum(1 for r in results.values() if r.get("status") == "ok")
        print(f"synthesized {successes}/{len(results)} rows")
        return 0 if successes > 0 else 1
    finally:
        if server_proc is not None:
            _stop_server(server_proc)


if __name__ == "__main__":
    sys.exit(main())

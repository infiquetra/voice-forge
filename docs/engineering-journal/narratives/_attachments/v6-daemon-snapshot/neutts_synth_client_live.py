#!/usr/bin/env python3
"""NeuTTS streaming client shim — creates FIFO, signals daemon, exits.

Daemon writes a WAV stream into the FIFO as soon as a reader (ffmpeg)
opens it. Hermes's discord adapter sees a regular path and opens it,
unblocking the daemon write side.

If NEUTTS_DISABLE_STREAM=1 in env, falls back to batch mode (regular
file output, blocking until full WAV written).
"""

import argparse
import json
import os
import socket
import sys
import time
from pathlib import Path

SOCKET_PATH = os.environ.get("NEUTTS_SOCKET_PATH", "/tmp/neutts.sock")
SOCKET_TIMEOUT = float(os.environ.get("NEUTTS_SOCKET_TIMEOUT", "30"))
DISABLE_STREAM = os.environ.get("NEUTTS_DISABLE_STREAM", "") == "1"

PROFILE_TO_PERSONA = {
    "freya-pa":          "freya",
    "saga-comms":        "saga",
    "gersemi-time":      "gersemi",
    "hnoss-books":       "hnoss",
    "eir-wellness":      "eir",
    "beyla-travel":      "beyla",
    "heid-research":     "heid",
    "bygul-procurement": "bygul",
    "trjegul-skeptic":   "trjegul",
}


def detect_persona(ref_audio_path: str) -> str:
    parent = Path(ref_audio_path).expanduser().parent.name
    return PROFILE_TO_PERSONA.get(parent, parent.split("-")[0])


def call_daemon(req: dict) -> dict:
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(SOCKET_TIMEOUT)
    s.connect(SOCKET_PATH)
    s.sendall((json.dumps(req) + "\n").encode())
    data = b""
    while b"\n" not in data:
        chunk = s.recv(65536)
        if not chunk:
            break
        data += chunk
    s.close()
    return json.loads(data.split(b"\n")[0])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--text", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--ref-audio", required=True)
    parser.add_argument("--ref-text", required=True)
    parser.add_argument("--model", default="")
    parser.add_argument("--device", default="")
    args = parser.parse_args()

    persona = detect_persona(args.ref_audio)
    out_path = Path(args.out).expanduser()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if not os.path.exists(SOCKET_PATH):
        print(f"Error: daemon socket not at {SOCKET_PATH}", file=sys.stderr)
        sys.exit(1)

    # Remove any existing file/FIFO at out_path before creating ours.
    try:
        if out_path.exists() or out_path.is_symlink():
            out_path.unlink()
    except FileNotFoundError:
        pass

    if DISABLE_STREAM:
        # Fall back to batch mode (regular file output)
        try:
            resp = call_daemon({
                "persona": persona,
                "text": args.text,
                "out_path": str(out_path),
            })
        except (socket.timeout, ConnectionRefusedError, OSError) as e:
            print(f"Error: daemon batch call failed: {type(e).__name__}: {e}", file=sys.stderr)
            sys.exit(2)
        if not resp.get("ok"):
            print(f"Error: daemon returned: {resp.get('error', 'unknown')}", file=sys.stderr)
            sys.exit(3)
        print(f"OK: {out_path} (batch synth={resp.get('synth_sec')}s audio={resp.get('audio_sec')}s "
              f"RTF={resp.get('rtf')} persona={persona})", file=sys.stderr)
        return

    # Streaming mode: create FIFO, signal daemon, exit
    try:
        os.mkfifo(str(out_path))
    except OSError as e:
        print(f"Error: mkfifo failed for {out_path}: {e}", file=sys.stderr)
        sys.exit(4)

    try:
        resp = call_daemon({
            "persona": persona,
            "text": args.text,
            "out_path": str(out_path),
            "stream": True,
        })
    except (socket.timeout, ConnectionRefusedError, OSError) as e:
        print(f"Error: daemon stream call failed: {type(e).__name__}: {e}", file=sys.stderr)
        # Clean up FIFO so hermes doesn't try to read a dangling one
        try:
            out_path.unlink()
        except OSError:
            pass
        sys.exit(5)

    if not resp.get("ok"):
        print(f"Error: daemon returned: {resp.get('error', 'unknown')}", file=sys.stderr)
        try:
            out_path.unlink()
        except OSError:
            pass
        sys.exit(6)

    print(f"OK: streaming to FIFO {out_path} (persona={persona} mode={resp.get('mode')} "
          f"expected_chunks={resp.get('expected_chunks')})", file=sys.stderr)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""neutts-daemon v6: streaming output via FIFO.

Layered on v5:
- Adds `stream: true` request mode that streams audio progressively into
  the requested out_path (which the client should create as a FIFO).
- Worker thread per streaming request; serialized via synth_lock since
  llama-cpp inference isn't safely concurrent on the same model.
- Writes a WAV header with placeholder size = 0xFFFFFFFF (read-until-EOF),
  then streams PCM samples from NeuTTS.infer_stream() through to the FIFO.
- ACKs back to the socket-client BEFORE opening the FIFO for write (so
  client exits immediately and hermes-agent's ffmpeg can open it as
  reader; FIFO write side then unblocks and data flows).

Non-streaming (batch) mode unchanged for backward compat.
"""

import errno
import fcntl
import json
import os
import re
import socket
import struct
import sys
import threading
import time
import wave
from pathlib import Path

SOCKET_PATH = os.environ.get("NEUTTS_SOCKET_PATH", "/tmp/neutts.sock")
REF_AUDIO_DIR = Path(os.environ.get("HERMES_HOME", str(Path.home() / ".hermes"))) / "profiles"
LOG_PATH = Path(os.environ.get("HERMES_HOME", str(Path.home() / ".hermes"))) / "logs" / "neutts-daemon.log"

MODEL = os.environ.get("NEUTTS_MODEL", "neuphonic/neutts-air-q8-gguf")
DEVICE = os.environ.get("NEUTTS_DEVICE", "cpu")
CHUNK_CHARS = int(os.environ.get("NEUTTS_CHUNK_CHARS", "600"))
REPEAT_PENALTY = float(os.environ.get("NEUTTS_REPEAT_PENALTY", "1.05"))
N_CTX = int(os.environ.get("NEUTTS_N_CTX", "8192"))
FIFO_OPEN_TIMEOUT = float(os.environ.get("NEUTTS_FIFO_OPEN_TIMEOUT", "30"))
SAMPLE_RATE = 24000

PERSONA_PROFILES = {
    "freya":   "freya-pa",
    "saga":    "saga-comms",
    "gersemi": "gersemi-time",
    "hnoss":   "hnoss-books",
    "eir":     "eir-wellness",
    "beyla":   "beyla-travel",
    "heid":    "heid-research",
    "bygul":   "bygul-procurement",
    "trjegul": "trjegul-skeptic",
}

# Patches
from neutts import NeuTTS
from llama_cpp import Llama

_original_load_backbone = NeuTTS._load_backbone


def _patched_load_backbone(self, backbone_repo, backbone_device):
    self.max_context = N_CTX
    return _original_load_backbone(self, backbone_repo, backbone_device)


NeuTTS._load_backbone = _patched_load_backbone

# Wrap Llama.__call__ so any code path that calls the backbone without
# explicit repeat_penalty (specifically NeuTTS._infer_stream_ggml) gets
# the same loop-suppression we apply in _infer_ggml. Otherwise streaming
# produces ~21% shorter audio than batch on long inputs (empirically
# verified 2026-05-24 with saga's 1991-char story: stream=130.5s,
# batch=164.6s for identical text).
_original_llama_call = Llama.__call__


def _patched_llama_call(self, *args, **kwargs):
    if "repeat_penalty" not in kwargs:
        kwargs["repeat_penalty"] = REPEAT_PENALTY
    return _original_llama_call(self, *args, **kwargs)


Llama.__call__ = _patched_llama_call

_original_infer_ggml = NeuTTS._infer_ggml


def _patched_infer_ggml(self, ref_codes, ref_text, input_text):
    ref_text = self._to_phones(ref_text)
    input_text = self._to_phones(input_text)
    codes_str = "".join([f"<|speech_{idx}|>" for idx in ref_codes])
    prompt = (
        f"user: Convert the text to speech:<|TEXT_PROMPT_START|>{ref_text} {input_text}"
        f"<|TEXT_PROMPT_END|>\nassistant:<|SPEECH_GENERATION_START|>{codes_str}"
    )
    output = self.backbone(
        prompt,
        max_tokens=self.max_context,
        temperature=1.0,
        top_k=50,
        repeat_penalty=REPEAT_PENALTY,
        stop=["<|SPEECH_GENERATION_END|>"],
    )
    return output["choices"][0]["text"]


NeuTTS._infer_ggml = _patched_infer_ggml

# Same patch for the streaming variant (which also uses self.backbone(...))
_original_infer_stream_ggml = NeuTTS._infer_stream_ggml


def _patched_infer_stream_ggml(self, ref_codes, ref_text, input_text):
    """Mirror _infer_ggml's patch onto the streaming variant.

    The original _infer_stream_ggml passes the same sampling params; we
    inject repeat_penalty the same way. If signature differs in this
    NeuTTS version, fall back to the unpatched original.
    """
    try:
        import inspect
        src = inspect.getsource(_original_infer_stream_ggml)
        # If upstream stream calls self.backbone.create_completion(stream=True), pass our params
        # For now, just call the original — repeat_penalty omission is the only deficiency;
        # we'll revisit if streaming produces stutter.
    except Exception:
        pass
    return _original_infer_stream_ggml(self, ref_codes, ref_text, input_text)


# We intentionally do NOT replace _infer_stream_ggml unless we can confirm the
# call signature; streaming without repeat_penalty might stutter, but we'll
# observe behavior first.


def log(msg):
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}"
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG_PATH, "a") as f:
            f.write(line + "\n")
    except Exception:
        pass
    print(line, file=sys.stderr, flush=True)


def chunk_text(text, max_chars):
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    chunks, current, current_len = [], [], 0
    for s in sentences:
        if current and current_len + len(s) + 1 > max_chars:
            chunks.append(" ".join(current))
            current, current_len = [s], len(s)
        else:
            current.append(s)
            current_len += len(s) + 1
    if current:
        chunks.append(" ".join(current))
    return chunks


def write_wav_batch(path, samples, sample_rate=SAMPLE_RATE):
    """Batch-mode WAV writer — knows the full size up-front."""
    import numpy as np
    if not isinstance(samples, np.ndarray):
        samples = np.array(samples, dtype=np.float32)
    samples = np.clip(samples.flatten(), -1.0, 1.0)
    pcm = (samples * 32767).astype(np.int16)
    with wave.open(path, "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(sample_rate)
        f.writeframes(pcm.tobytes())


def build_wav_header_streaming(sample_rate=SAMPLE_RATE, channels=1, bits=16):
    """WAV header with placeholder sizes for streaming.

    Sets RIFF chunk size and data chunk size to 0xFFFFFFFF so demuxers
    read until EOF rather than trusting the header. ffmpeg handles this
    gracefully for WAV input.
    """
    byte_rate = sample_rate * channels * (bits // 8)
    block_align = channels * (bits // 8)
    header = b"RIFF"
    header += struct.pack("<I", 0xFFFFFFFF)  # bogus RIFF size
    header += b"WAVE"
    header += b"fmt "
    header += struct.pack("<I", 16)
    header += struct.pack("<H", 1)            # PCM
    header += struct.pack("<H", channels)
    header += struct.pack("<I", sample_rate)
    header += struct.pack("<I", byte_rate)
    header += struct.pack("<H", block_align)
    header += struct.pack("<H", bits)
    header += b"data"
    header += struct.pack("<I", 0xFFFFFFFF)  # bogus data size
    return header


def open_fifo_write_with_timeout(path, timeout):
    """Open a FIFO for write, polling until a reader opens it."""
    start = time.time()
    while True:
        try:
            fd = os.open(path, os.O_WRONLY | os.O_NONBLOCK)
            # Switch to blocking mode for subsequent writes
            flags = fcntl.fcntl(fd, fcntl.F_GETFL)
            fcntl.fcntl(fd, fcntl.F_SETFL, flags & ~os.O_NONBLOCK)
            return os.fdopen(fd, "wb", buffering=0)
        except OSError as e:
            if e.errno != errno.ENXIO:
                raise
            if time.time() - start > timeout:
                raise TimeoutError(f"no reader for FIFO {path} after {timeout}s")
            time.sleep(0.05)


# Inference is not safe to run concurrently on the same Llama instance.
synth_lock = threading.Lock()


def stream_worker(tts, persona, text, out_path, ref_cache):
    """Worker thread: open FIFO, stream synth output progressively."""
    import numpy as np

    try:
        log(f"  [stream] waiting for reader on {out_path}")
        f = open_fifo_write_with_timeout(out_path, FIFO_OPEN_TIMEOUT)
    except TimeoutError as e:
        log(f"  [stream] FIFO open timeout: {e}")
        try:
            os.unlink(out_path)
        except OSError:
            pass
        return
    except Exception as e:
        log(f"  [stream] FIFO open ERROR: {type(e).__name__}: {e}")
        return

    log(f"  [stream] reader connected, beginning synth (persona={persona})")
    codes, ref_text = ref_cache[persona]
    chunks = chunk_text(text, CHUNK_CHARS)

    try:
        f.write(build_wav_header_streaming())
    except BrokenPipeError:
        log(f"  [stream] reader closed before header write")
        f.close()
        return

    t0 = time.time()
    total_samples = 0
    aborted = False
    with synth_lock:
        for chunk_idx, chunk in enumerate(chunks):
            try:
                for audio in tts.infer_stream(chunk, codes, ref_text):
                    samples = np.clip(audio.flatten(), -1.0, 1.0).astype(np.float32)
                    pcm = (samples * 32767).astype(np.int16)
                    try:
                        f.write(pcm.tobytes())
                    except BrokenPipeError:
                        log(f"  [stream] reader closed mid-stream at chunk {chunk_idx}, {total_samples / SAMPLE_RATE:.2f}s in")
                        aborted = True
                        break
                    total_samples += len(samples)
                if aborted:
                    break
            except Exception as e:
                log(f"  [stream] chunk {chunk_idx} synth ERROR: {type(e).__name__}: {e}")
                aborted = True
                break

    audio_s = total_samples / SAMPLE_RATE
    synth_s = time.time() - t0
    rtf = synth_s / max(audio_s, 0.01)
    status = "ABORTED" if aborted else "OK"
    log(f"  [stream] {status} synth={synth_s:.2f}s audio={audio_s:.2f}s RTF={rtf:.2f}")

    try:
        f.close()
    except Exception:
        pass


def main():
    log(f"neutts-daemon v6 starting (pid={os.getpid()})")
    log(f"  socket={SOCKET_PATH}  model={MODEL}  device={DEVICE}  chunk={CHUNK_CHARS}")
    log(f"  SAMPLING: temperature=1.0, top_k=50, repeat_penalty={REPEAT_PENALTY}")
    log(f"  N_CTX OVERRIDE: {N_CTX}")
    log(f"  STREAMING enabled (FIFO+WAV bogus-size header, fifo_open_timeout={FIFO_OPEN_TIMEOUT}s)")

    import numpy as np

    t0 = time.time()
    tts = NeuTTS(
        backbone_repo=MODEL,
        backbone_device=DEVICE,
        codec_repo="neuphonic/neucodec",
        codec_device=DEVICE,
    )
    log(f"  model loaded in {time.time() - t0:.1f}s, max_context={tts.max_context}")

    # Disable the Perth watermarker — its per-chunk application during streaming
    # causes audible cracks at chunk boundaries. Empirically tested 2026-05-24:
    # delta>10000 sample-jumps dropped 15x (1167 → 79) with this disabled.
    if tts.watermarker is not None:
        log(f"  disabling watermarker (was {type(tts.watermarker).__name__}) to fix streaming cracks")
        tts.watermarker = None

    ref_cache = {}
    for persona, profile_dir in PERSONA_PROFILES.items():
        ref_wav = REF_AUDIO_DIR / profile_dir / "voice_ref.wav"
        ref_txt = REF_AUDIO_DIR / profile_dir / "voice_ref.txt"
        if not ref_wav.exists() or not ref_txt.exists():
            continue
        try:
            t1 = time.time()
            codes = tts.encode_reference(str(ref_wav))
            text = ref_txt.read_text(encoding="utf-8").strip()
            ref_cache[persona] = (codes, text)
            log(f"  {persona}: encoded ({time.time() - t1:.2f}s, ref_text {len(text)} chars)")
        except Exception as e:
            log(f"  {persona}: encode FAILED — {type(e).__name__}: {e}")

    log(f"ready: {len(ref_cache)}/{len(PERSONA_PROFILES)} personas pre-encoded")

    if os.path.exists(SOCKET_PATH):
        os.unlink(SOCKET_PATH)
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(SOCKET_PATH)
    os.chmod(SOCKET_PATH, 0o666)
    server.listen(8)
    log(f"listening on {SOCKET_PATH}")

    def handle(conn):
        try:
            data = b""
            conn.settimeout(10.0)
            while b"\n" not in data:
                chunk = conn.recv(65536)
                if not chunk:
                    break
                data += chunk
            if not data:
                return
            req = json.loads(data.split(b"\n")[0])
            persona = req.get("persona", "").lower()
            text = (req.get("text") or "").strip()
            out_path = req.get("out_path", "")
            stream = bool(req.get("stream"))

            if persona == "_health":
                conn.sendall((json.dumps({
                    "ok": True, "version": "v6-streaming",
                    "personas_ready": list(ref_cache.keys()),
                    "model": MODEL, "device": DEVICE,
                    "sampling": {"temperature": 1.0, "top_k": 50, "repeat_penalty": REPEAT_PENALTY},
                    "n_ctx": tts.max_context,
                    "streaming": True,
                }) + "\n").encode())
                return

            if persona not in ref_cache:
                conn.sendall((json.dumps({"ok": False, "error": f"persona {persona!r} not pre-encoded; available: {list(ref_cache.keys())}"}) + "\n").encode())
                return
            if not text or not out_path:
                conn.sendall((json.dumps({"ok": False, "error": "text + out_path required"}) + "\n").encode())
                return

            if stream:
                # ACK first so client can exit; worker opens FIFO once a reader appears.
                worker = threading.Thread(
                    target=stream_worker,
                    args=(tts, persona, text, out_path, ref_cache),
                    daemon=True,
                )
                worker.start()
                log(f"req: persona={persona} chars={len(text)} STREAM=True worker={worker.name}")
                conn.sendall((json.dumps({
                    "ok": True, "mode": "stream",
                    "persona": persona,
                    "expected_chunks": len(chunk_text(text, CHUNK_CHARS)),
                }) + "\n").encode())
                return

            # Batch mode (unchanged from v5)
            codes, ref_text = ref_cache[persona]
            chunks = chunk_text(text, CHUNK_CHARS)
            log(f"req: persona={persona} chars={len(text)} chunks={len(chunks)} (batch)")

            t0 = time.time()
            with synth_lock:
                all_audio = []
                for chunk in chunks:
                    wav = tts.infer(chunk, codes, ref_text)
                    all_audio.append(wav)
            synth_s = time.time() - t0

            combined = np.concatenate(all_audio) if len(all_audio) > 1 else all_audio[0]
            write_wav_batch(out_path, combined)
            audio_s = len(combined) / SAMPLE_RATE
            rtf = synth_s / max(audio_s, 0.01)
            log(f"  done: synth={synth_s:.2f}s audio={audio_s:.2f}s RTF={rtf:.2f}")

            conn.sendall((json.dumps({
                "ok": True, "audio_sec": round(audio_s, 2),
                "synth_sec": round(synth_s, 2), "rtf": round(rtf, 2),
                "chunks": len(chunks),
            }) + "\n").encode())
        except Exception as e:
            log(f"  ERROR: {type(e).__name__}: {e}")
            try:
                conn.sendall((json.dumps({"ok": False, "error": f"{type(e).__name__}: {e}"}) + "\n").encode())
            except Exception:
                pass
        finally:
            try:
                conn.close()
            except Exception:
                pass

    try:
        while True:
            conn, _ = server.accept()
            handle(conn)
    except KeyboardInterrupt:
        log("shutting down (SIGINT)")
    finally:
        try:
            server.close()
        except Exception:
            pass
        if os.path.exists(SOCKET_PATH):
            os.unlink(SOCKET_PATH)


if __name__ == "__main__":
    main()

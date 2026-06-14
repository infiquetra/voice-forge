/*
 * ws-audition.js — one-shot WS /v1/tts/stream audition (U9).
 *
 * Opens ws(s)://(host)/v1/tts/stream, sends {voice, sampling}, sends one fixed
 * sample sentence with end:true, and resolves with the FIRST sentence's PCM as
 * a Float32Array + the session sample_rate. This is the ONLY path that honors
 * per-knob sampling overrides — POST /v1/audio/speech carries `speed` only — so
 * the tuning bench hears a knob move here.
 *
 * Returns a HANDLE with .promise and .abort(): a fresh slider release aborts the
 * previous in-flight audition (cancel/replace), so only the latest take plays.
 *
 * Protocol (verified server.py:1402-1567 + tests/unit/test_ws_streaming.py):
 *   client → {"voice", "sampling"?}  then  {"text": "...", "end": true}
 *   server → {"event":"session", sample_rate, ...}
 *            {"event":"sentence_start", ...}  <binary float32-LE PCM>  {"event":"sentence_done", ...}
 *            {"event":"complete", "sentences_total":N}
 *            {"event":"error", "detail":...}  then socket close
 * The sample sentence is ONE sentence → exactly one binary frame
 * (test_ws_basic_single_sentence_round_trip:140), so we take the first frame
 * and resolve — fastest time-to-audio.
 */

const SAMPLE_SENTENCE = "The quick brown fox jumps over the lazy dog.";
const AUDITION_TIMEOUT_MS = 20000;

/**
 * Start an audition. Non-throwing: the promise REJECTS on error/close/timeout/
 * abort with an Error whose `.reason` is one of
 *   "error" | "closed" | "timeout" | "aborted" | "no-audio"
 * Callers branch on `.reason` to decide UI: "aborted" (replaced by a newer
 * release) is silent; the rest clear the hot state and show a failure note.
 *
 * @param {string} voice    registry voice id
 * @param {object} sampling minimal overrides map (may be {} — only moved knobs)
 * @returns {{promise: Promise<{samples: Float32Array, sampleRate: number}>, abort: () => void}}
 */
export function auditionVoice(voice, sampling) {
  const proto = location.protocol === "https:" ? "wss:" : "ws:";
  const ws = new WebSocket(`${proto}//${location.host}/v1/tts/stream`);
  ws.binaryType = "arraybuffer"; // binary PCM frames arrive as ArrayBuffer

  let sampleRate = 24000; // overwritten by the session frame
  let settled = false;
  let timer = null;
  let failRef = null; // set inside the executor so abort() can reject

  const handle = {};
  handle.promise = new Promise((resolve, reject) => {
    const done = (fn, arg) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      // Detach handlers so a late frame/close can't double-settle.
      ws.onopen = ws.onmessage = ws.onerror = ws.onclose = null;
      try {
        ws.close();
      } catch {
        /* already closing */
      }
      fn(arg);
    };
    const fail = (reason) => {
      const e = new Error(`audition ${reason}`);
      e.reason = reason;
      done(reject, e);
    };
    failRef = fail; // expose to abort()

    timer = setTimeout(() => fail("timeout"), AUDITION_TIMEOUT_MS);

    ws.onopen = () => {
      // Only send a non-empty sampling key — keeps request-scope minimal and
      // matches the server's `if init_sampling` guard (server.py:1440).
      const init = { voice };
      if (sampling && Object.keys(sampling).length) init.sampling = sampling;
      ws.send(JSON.stringify(init));
      ws.send(JSON.stringify({ text: SAMPLE_SENTENCE, end: true }));
    };

    ws.onmessage = (ev) => {
      if (typeof ev.data === "string") {
        let msg;
        try {
          msg = JSON.parse(ev.data);
        } catch {
          return;
        }
        if (msg.event === "session") {
          sampleRate = msg.sample_rate || sampleRate;
        } else if (msg.event === "error") {
          fail("error"); // server sends error then closes
        } else if (msg.event === "complete") {
          // No binary arrived before complete (e.g. all-whitespace) → no audio.
          fail("no-audio");
        }
        return;
      }
      // Binary = the first sentence's float32-LE PCM. Take the FIRST frame and
      // resolve — the sample sentence is one sentence, so one frame is the take.
      // ArrayBuffer → Float32Array (LE on every platform this app supports).
      const samples = new Float32Array(ev.data);
      done(resolve, { samples, sampleRate });
    };

    ws.onerror = () => fail("closed");
    ws.onclose = () => fail("closed"); // if we reach here unsettled, the socket died early
  });

  // Abort rejects the promise with reason "aborted" so the caller's single
  // `finally` runs and no promise dangles. A newer audition owns the hot state,
  // so the caller treats "aborted" as silent.
  handle.abort = () => {
    if (failRef) failRef("aborted");
  };

  return handle;
}

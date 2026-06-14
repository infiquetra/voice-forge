/*
 * <forge-waveform> — the take player chip.
 *
 * U3 (the audio layer): a compact ~30px player that replaces raw <audio
 * controls> everywhere a forged take lands. A play/pause button, static peak
 * bars sampled from the take, and a thin ember progress fill that warms the
 * bars it has passed — the take plays "hot" the same way a card forges hot.
 *
 * Feeds, same chip:
 *   - `src="…"` attribute → loads a URL (e.g. /v1/audio/speech output, a ref
 *     WAV) through an off-DOM <audio> element. Peaks are an even placeholder
 *     bar until the real samples arrive.
 *   - setPcm(Float32Array, sampleRate) — or the `pcm` property + `sample-rate`
 *     attribute, the form HTML integrators use — render true peaks straight from
 *     the WS PCM stream (/v1/tts/stream pcm_f32le frames), no decode round-trip.
 *
 * The silence-collapse signal (KTD3): a take whose peak amplitude is below the
 * floor (< 0.05) is a collapsed synthesis, not a quiet one. It renders as a
 * flat --forge-bad line with a "silent" label instead of bars — the one place
 * the player shouts. An integrator that already knows a take is dead can force
 * this path up front with the boolean `flat` attribute, before any audio loads.
 * Everything else stays restrained.
 *
 * Self-contained: no store slices observed. The shell feeds it audio and reads
 * back play()/stop(); local play state drives an on-demand refresh().
 */

import { ForgeElement, esc } from "./base.js";

// Amplitude floor below which a take is a silence-collapse, not a quiet take.
const SILENCE_FLOOR = 0.05;
// How many peak bars the chip draws — fixed so the chip width is predictable.
const BARS = 48;

class ForgeWaveform extends ForgeElement {
  // No store keys: this chip is fed imperatively (src attr + setPcm/play/stop).
  static observe = [];

  static get observedAttributes() {
    // src/sample-rate feed audio; flat forces the silence-collapse render path.
    return ["src", "flat", "sample-rate"];
  }

  constructor() {
    super();
    this._audio = null; // off-DOM <audio>, the playback engine
    this._peaks = null; // Float32Array(BARS) of 0..1 peak heights, or null
    this._peak = 0; // overall max amplitude — drives the silence-collapse test
    this._progress = 0; // 0..1 played fraction, drives the ember fill
    this._playing = false;
    this._flat = false; // `flat` attr present → force the silence-collapse line
    this._pcm = null; // last samples set via the `pcm` property (getter mirror)
  }

  connectedCallback() {
    // Read `flat` before the first paint so a pre-declared silent take renders
    // collapsed immediately (attributeChangedCallback also keeps it in sync).
    this._flat = this.hasAttribute("flat");
    super.connectedCallback();
    const src = this.getAttribute("src");
    if (src) this._loadSrc(src);
  }

  disconnectedCallback() {
    super.disconnectedCallback();
    this._teardownAudio();
  }

  attributeChangedCallback(name, oldVal, newVal) {
    if (newVal === oldVal) return;
    if (name === "src") {
      // Initial src is loaded by connectedCallback; act only once connected.
      if (this._root) this._loadSrc(newVal);
    } else if (name === "flat") {
      this._flat = newVal !== null;
      this.refresh();
    } else if (name === "sample-rate") {
      // Peaks are rate-independent; only the playback WAV header carries the
      // rate, so re-wrap any already-set PCM at the new rate.
      if (this._pcm) this.setPcm(this._pcm, this._sampleRate());
    }
  }

  /* ---- public API (the shell drives these) ---------------------------- */

  /** Render true peaks straight from a PCM take — the WS-stream fast path. */
  setPcm(samples, sampleRate) {
    this._pcm = samples || null;
    this._peaks = this._downsample(samples, BARS);
    this._peak = this._maxAbs(samples);
    this._progress = 0;
    // Wrap the raw PCM in a WAV so the <audio> engine can still play it back.
    this._loadBlob(pcmToWav(samples, sampleRate || 24000));
    this.refresh();
  }

  /**
   * Property feed: `el.pcm = floatArray` renders true peaks the same way setPcm
   * does, but as an assignment — HTML can't carry a typed array, so integrators
   * set it on the upgraded element. Sample rate comes from the `sample-rate`
   * attribute, defaulting to the WS stream's 24 kHz.
   */
  set pcm(samples) {
    if (samples && samples.length) this.setPcm(samples, this._sampleRate());
    else this._pcm = null;
  }

  get pcm() {
    return this._pcm;
  }

  /** Sample rate from the attribute, defaulting to the WS stream's 24 kHz. */
  _sampleRate() {
    return Number(this.getAttribute("sample-rate")) || 24000;
  }

  /** Start playback from the current position. */
  play() {
    if (this._audio) this._audio.play().catch(() => {});
  }

  /** Stop playback and rewind to the head. */
  stop() {
    if (!this._audio) return;
    this._audio.pause();
    this._audio.currentTime = 0;
  }

  /* ---- audio engine --------------------------------------------------- */

  _loadSrc(url) {
    this._loadAudio(url);
    // A URL take starts with placeholder bars; setPcm overrides with real peaks.
    if (!this._peaks) {
      this._peaks = null;
      this._peak = 1;
    }
    this.refresh();
  }

  _loadBlob(blob) {
    this._loadAudio(URL.createObjectURL(blob));
  }

  _loadAudio(url) {
    this._teardownAudio();
    const a = new Audio();
    a.preload = "auto";
    a.src = url;
    a.addEventListener("play", () => this._setPlaying(true));
    a.addEventListener("pause", () => this._setPlaying(false));
    a.addEventListener("ended", () => {
      this._progress = 0;
      this._setPlaying(false);
    });
    a.addEventListener("timeupdate", () => {
      if (a.duration) this._progress = a.currentTime / a.duration;
      this.refresh();
    });
    this._audio = a;
  }

  _teardownAudio() {
    if (!this._audio) return;
    this._audio.pause();
    // Release object URLs minted by setPcm/_loadBlob so blobs don't leak.
    if (this._audio.src.startsWith("blob:")) URL.revokeObjectURL(this._audio.src);
    this._audio = null;
    this._playing = false;
  }

  _setPlaying(on) {
    if (this._playing === on) return;
    this._playing = on;
    // Playback is LOCAL — refresh only this chip's play/pause icon + progress.
    // It must NOT write store.forging: cards and the shell observe that key and
    // replace their whole innerHTML on change, which would destroy this very
    // <forge-waveform> mid-play. store.forging means "a synthesis is in flight"
    // (set by the serve/audition path), not "a finished take is playing back".
    this.refresh();
  }

  /* ---- peak sampling -------------------------------------------------- */

  /** Peak-pick `n` bars out of a sample buffer (max-abs per window). */
  _downsample(samples, n) {
    const out = new Float32Array(n);
    if (!samples || !samples.length) return out;
    const step = samples.length / n;
    for (let i = 0; i < n; i++) {
      const start = Math.floor(i * step);
      const end = Math.max(start + 1, Math.floor((i + 1) * step));
      let peak = 0;
      for (let j = start; j < end && j < samples.length; j++) {
        const v = Math.abs(samples[j]);
        if (v > peak) peak = v;
      }
      out[i] = peak;
    }
    return out;
  }

  _maxAbs(samples) {
    let m = 0;
    if (!samples) return m;
    for (let i = 0; i < samples.length; i++) {
      const v = Math.abs(samples[i]);
      if (v > m) m = v;
    }
    return m;
  }

  /* ---- render --------------------------------------------------------- */

  styles() {
    return `
      :host { display: inline-block; }
      .chip { display: flex; align-items: center; gap: var(--forge-gap-sm); height: 30px; padding: 0 8px; box-sizing: border-box;
          background: var(--forge-inset); border: 1px solid var(--forge-border); border-radius: var(--forge-radius-pill); }

      .play { all: unset; cursor: pointer; display: grid; place-items: center; width: 18px; height: 18px; flex: 0 0 auto;
          color: var(--forge-text-dim); border-radius: var(--forge-radius-pill); }
      .play:hover { color: var(--forge-text); }
      .play[data-playing="true"] { color: var(--forge-ember); filter: drop-shadow(0 0 5px var(--forge-ember-edge)); }
      .play svg { width: 14px; height: 14px; }

      /* The well the bars live in — peak-picked spans, ember on the played side. */
      .bars { flex: 1 1 auto; display: flex; align-items: center; gap: 1px; height: 18px; min-width: 80px; }
      .bar { flex: 1 1 0; background: var(--forge-border-strong); border-radius: 1px; min-height: 2px; transition: background 90ms var(--forge-ease); }
      .bar.hot { background: var(--forge-ember); }

      /* Silence-collapse: not a quiet take, a failed one — the loud signal. */
      .silent { flex: 1 1 auto; display: flex; align-items: center; gap: 6px; min-width: 80px; }
      .silent .line { flex: 1 1 auto; height: 2px; background: var(--forge-bad); border-radius: 1px; }
      .silent .label { font-family: var(--forge-mono); font-size: 10px; letter-spacing: 0.04em; color: var(--forge-bad); }

      .empty { flex: 1 1 auto; min-width: 80px; font-family: var(--forge-mono); font-size: 10px; color: var(--forge-text-faint); }
    `;
  }

  render() {
    const playing = this._playing;
    const icon = playing
      ? `<svg viewBox="0 0 16 16" aria-hidden="true"><rect x="3" y="2.5" width="3.5" height="11" rx="1" fill="currentColor"/><rect x="9.5" y="2.5" width="3.5" height="11" rx="1" fill="currentColor"/></svg>`
      : `<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M4 2.5v11l9-5.5z" fill="currentColor"/></svg>`;

    const button = `<button class="play" data-playing="${playing}" aria-label="${playing ? "pause" : "play"}">${icon}</button>`;

    let track;
    if (this._flat || (this._audio && this._peak < SILENCE_FLOOR)) {
      // Collapsed synthesis — flat bad-line + label, no bars. Either measured
      // (peak below the floor) or forced up front by the `flat` attribute, which
      // wins regardless of peaks so an integrator can pre-declare a dead take.
      track = `<div class="silent" role="img" aria-label="silent take — synthesis collapsed">
          <div class="line"></div><span class="label">silent</span></div>`;
    } else if (this._peaks) {
      track = `<div class="bars" role="img" aria-label="audio peaks">${this._barsHtml()}</div>`;
    } else if (this._audio) {
      // URL take with no decoded peaks yet — neutral even bars as a placeholder.
      track = `<div class="bars" role="img" aria-label="audio peaks">${this._barsHtml(true)}</div>`;
    } else {
      track = `<div class="empty">${esc("no take")}</div>`;
    }

    return `<div class="chip">${button}${track}</div>`;
  }

  /** Build the bar spans; `flat` draws even placeholder bars (no real peaks). */
  _barsHtml(flat) {
    const peaks = this._peaks;
    let html = "";
    for (let i = 0; i < BARS; i++) {
      const amp = flat || !peaks ? 0.4 : peaks[i];
      const h = Math.max(8, Math.round(amp * 100)); // % of the 18px well
      const hot = i / BARS < this._progress ? " hot" : "";
      html += `<div class="bar${hot}" style="height:${h}%"></div>`;
    }
    return html;
  }

  bind() {
    const btn = this.$(".play");
    if (btn) {
      btn.onclick = () => (this._playing ? this.stop() : this.play());
    }
  }
}

/**
 * Wrap mono float32-LE PCM in a 44-byte WAV header so an <audio> element can
 * replay the very samples the WS stream delivered — no re-decode, no re-fetch.
 */
function pcmToWav(samples, sampleRate) {
  const bytesPerSample = 4; // float32
  const dataLen = samples.length * bytesPerSample;
  const buf = new ArrayBuffer(44 + dataLen);
  const view = new DataView(buf);
  const writeStr = (off, s) => {
    for (let i = 0; i < s.length; i++) view.setUint8(off + i, s.charCodeAt(i));
  };
  writeStr(0, "RIFF");
  view.setUint32(4, 36 + dataLen, true);
  writeStr(8, "WAVE");
  writeStr(12, "fmt ");
  view.setUint32(16, 16, true); // fmt chunk size
  view.setUint16(20, 3, true); // format 3 = IEEE float
  view.setUint16(22, 1, true); // channels
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * bytesPerSample, true); // byte rate
  view.setUint16(32, bytesPerSample, true); // block align
  view.setUint16(34, 32, true); // bits per sample
  writeStr(36, "data");
  view.setUint32(40, dataLen, true);
  for (let i = 0; i < samples.length; i++) view.setFloat32(44 + i * bytesPerSample, samples[i], true);
  return new Blob([buf], { type: "audio/wav" });
}

customElements.define("forge-waveform", ForgeWaveform);

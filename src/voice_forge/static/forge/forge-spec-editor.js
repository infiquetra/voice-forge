/*
 * <forge-spec-editor voice-id="..."> — direct-manipulation tuning (U9).
 *
 * The focused voice's "spec sheet": its backend's tunables (from
 * store.backends → the matching backend's `tunables` schema) rendered as
 * labelled DRAG sliders, each carrying a faint ghost tick at the backend
 * default so you can see how far you've pushed it. Plus a description
 * <textarea> for re-describing the voice in words.
 *
 * Hearing a change (U9): a slider thumb-release runs a LOCAL one-shot WS
 * audition (ws-audition.js → /v1/tts/stream), plays the result in this editor's
 * own <forge-waveform>, and manages store.forging itself — mirroring
 * forge-serve-console._run, which owns its synth the same way. The editor owns
 * the audition end to end (fork B): the chip that plays the take must live in a
 * node that does NOT re-render on `forging` (this editor's `observe` excludes
 * it), so a forging flip can't tear the playing chip down mid-play.
 *
 * Both triggers ALSO dispatch a `forge-audition` CustomEvent (bubbles+composed)
 * so the shell keeps an open seam for future host-level listeners (telemetry, a
 * global "auditioning" indicator) — but that event is telemetry, not the
 * load-bearing path; the WS round-trip above is.
 *   - thumb-release on a slider → LOCAL audition + event {voice, sampling:{...}}
 *     (only knobs moved off their default ride along — request-scope, minimal)
 *   - a ~600ms debounced pause typing in the description → event
 *     {voice, description} ONLY. Re-describing is a DESIGN op (ElevenLabs
 *     text→voice) with no request-scope synth — out of scope for U9, so the
 *     editor never opens a WS for it. It stays event-only (the shell logs it).
 *
 * Controls group by intent — Identity (what it is) / Voice (how it sounds) /
 * Lines (how it speaks) — so the bench reads as a spec, not a wall of knobs.
 * Restrained ember: the accent rides the live slider fill, nothing more.
 */

import { ForgeElement, esc } from "./base.js";
import { store } from "./store.js";
import { auditionVoice } from "./ws-audition.js";

// Which group each tunable lands in. Anything unmatched falls to "Voice".
// Keyed on substrings so new backend knobs slot in without a code change.
const GROUPS = [
  { id: "voice", label: "Voice", match: ["cfg", "guidance", "temperature", "exaggeration", "style", "emotion"] },
  { id: "lines", label: "Lines", match: ["speed", "pace", "rate", "fade", "chunk", "pause", "step", "nfe"] },
  { id: "identity", label: "Identity", match: ["seed"] },
];

class ForgeSpecEditor extends ForgeElement {
  static observe = ["voices", "backends", "focused"];

  static get observedAttributes() {
    return ["voice-id"];
  }

  attributeChangedCallback() {
    this.refresh();
  }

  disconnectedCallback() {
    super.disconnectedCallback();
    clearTimeout(this._descTimer);
    // Focus-switching away mid-audition must not leak a socket or leave the
    // anvil stuck hot — abort the in-flight take and clear forging if ours.
    this._teardownAudition();
  }

  /** The voice this editor edits — the attribute wins, else the focused one. */
  _voiceId() {
    return this.getAttribute("voice-id") || store.get("focused") || null;
  }

  _voice() {
    const id = this._voiceId();
    const voices = store.get("voices") || [];
    return voices.find((v) => (v.voice_id || v.id) === id) || null;
  }

  /** The tunables schema for a voice's backend, from the backends snapshot. */
  _schema(voice) {
    // store.backends is normalized to a bare array at the load boundary.
    const list = store.get("backends") || [];
    const b = list.find((x) => x.name === (voice && voice.backend));
    return (b && b.tunables) || {};
  }

  /** Per-knob default tag for the ghost tick + the dispatch diff. */
  _default(spec) {
    return spec.default;
  }

  styles() {
    return `
      :host { display: block; }
      #root { padding: var(--forge-gap); display: flex; flex-direction: column; gap: var(--forge-gap-lg); }

      .empty { color: var(--forge-text-faint); font-size: 13px; }

      /* Audition strip — the local WS take plays here, adjacent to the knobs. */
      .audition { display: flex; align-items: center; gap: var(--forge-gap-sm); }
      .audition-label { font-size: 11px; text-transform: uppercase; letter-spacing: 0.06em; color: var(--forge-text-faint); }
      .audition forge-waveform { flex: 1 1 auto; min-width: 0; }
      .audition-status { font-family: var(--forge-mono); font-size: 10px; color: var(--forge-text-faint); white-space: nowrap; }
      .audition-status[data-state="error"] { color: var(--forge-bad); }

      .group { display: flex; flex-direction: column; gap: var(--forge-gap-sm); }
      .group > h3 { margin: 0; font-size: 11px; text-transform: uppercase; letter-spacing: 0.06em; color: var(--forge-text-faint); font-weight: 600; }

      /* Description — the Identity group's words. */
      textarea { all: unset; box-sizing: border-box; width: 100%; min-height: 76px; resize: vertical;
          background: var(--forge-inset); border: 1px solid var(--forge-border); border-radius: var(--forge-radius-sm);
          padding: 10px 12px; font-family: var(--forge-font); font-size: 13px; line-height: 1.5; color: var(--forge-text); }
      textarea::placeholder { color: var(--forge-text-faint); }
      textarea:focus { border-color: var(--forge-ember-edge); box-shadow: 0 0 0 1px var(--forge-ember-edge); }

      /* Slider rows. The fill rides the ember; the ghost tick marks the default. */
      .knob { display: grid; grid-template-columns: 1fr auto; align-items: baseline; gap: 2px 12px; }
      .knob .name { font-size: 13px; font-weight: 540; color: var(--forge-text); }
      .knob .val { font-family: var(--forge-mono); font-size: 12px; color: var(--forge-text-dim); }
      .knob .val[data-moved="true"] { color: var(--forge-ember); }
      .knob .track { grid-column: 1 / -1; position: relative; }

      input[type="range"] { -webkit-appearance: none; appearance: none; width: 100%; height: 18px; margin: 0; background: transparent; cursor: grab; }
      input[type="range"]:active { cursor: grabbing; }
      input[type="range"]::-webkit-slider-runnable-track { height: 4px; border-radius: var(--forge-radius-pill);
          background: linear-gradient(to right, var(--forge-ember) 0 var(--fill, 0%), var(--forge-border-strong) var(--fill, 0%) 100%); }
      input[type="range"]::-moz-range-track { height: 4px; border-radius: var(--forge-radius-pill); background: var(--forge-border-strong); }
      input[type="range"]::-moz-range-progress { height: 4px; border-radius: var(--forge-radius-pill); background: var(--forge-ember); }
      input[type="range"]::-webkit-slider-thumb { -webkit-appearance: none; appearance: none; width: 14px; height: 14px; margin-top: -5px;
          border-radius: 50%; background: var(--forge-text); border: 2px solid var(--forge-bg); }
      input[type="range"]::-moz-range-thumb { width: 14px; height: 14px; border-radius: 50%; background: var(--forge-text); border: 2px solid var(--forge-bg); }
      input[type="range"]:focus-visible::-webkit-slider-thumb { box-shadow: 0 0 0 3px var(--forge-ember-edge); }
      input[type="range"]:focus-visible::-moz-range-thumb { box-shadow: 0 0 0 3px var(--forge-ember-edge); }

      /* Faint default ghost tick floating over the track. */
      .ghost { position: absolute; top: 7px; width: 2px; height: 8px; margin-left: -1px; border-radius: 1px;
          background: var(--forge-text-faint); opacity: 0.5; pointer-events: none; }
      .knob .desc { grid-column: 1 / -1; font-size: 11px; color: var(--forge-text-faint); line-height: 1.4; }
    `;
  }

  render() {
    const voice = this._voice();
    if (!voice) {
      return `<div class="empty">Select a voice to tune it.</div>`;
    }

    const id = voice.voice_id || voice.id || "";
    const schema = this._schema(voice);
    const sampling = (voice.metadata && voice.metadata.sampling) || {};
    const names = Object.keys(schema);

    // Bucket the knobs into their intent groups, preserving schema order.
    const buckets = { identity: [], voice: [], lines: [] };
    for (const name of names) {
      const g = GROUPS.find((grp) => grp.match.some((m) => name.toLowerCase().includes(m)));
      buckets[g ? g.id : "voice"].push(name);
    }

    // The audition strip: a compact player fed by the LOCAL WS audition, plus a
    // status note. It's a FIXED part of the markup (not inside the per-knob
    // loop) so bind() can re-find and re-wire it on every paint. It must NOT
    // carry untrusted text — the <forge-waveform> is fed PCM imperatively and
    // the status is set from a fixed vocabulary, so no esc() needed here.
    const auditionStrip = `
      <div class="audition" role="group" aria-label="audition">
        <span class="audition-label">audition</span>
        <forge-waveform></forge-waveform>
        <span class="audition-status" data-state="idle" aria-live="polite"></span>
      </div>`;

    // Identity — words first, then the audition strip, then any identity-class
    // knobs (e.g. seed).
    const identity = `
      <section class="group">
        <h3>Identity</h3>
        <textarea id="desc" placeholder="Describe this voice — warm, gravelly, mid-40s narrator…">${esc(voice.description || "")}</textarea>
        ${auditionStrip}
        ${buckets.identity.map((n) => this._knob(n, schema[n], sampling)).join("")}
      </section>`;

    const voiceGroup = this._group("Voice", buckets.voice, schema, sampling);
    const lines = this._group("Lines", buckets.lines, schema, sampling);

    // No tunables at all — still offer the description (always editable).
    const knobNote =
      names.length === 0
        ? `<div class="empty">${esc(voice.backend || "this backend")} has no per-voice tunables — describe it instead.</div>`
        : "";

    return identity + voiceGroup + lines + knobNote;
  }

  _group(label, names, schema, sampling) {
    if (!names.length) return "";
    return `
      <section class="group">
        <h3>${esc(label)}</h3>
        ${names.map((n) => this._knob(n, schema[n], sampling)).join("")}
      </section>`;
  }

  _knob(name, spec, sampling) {
    const def = this._default(spec);
    const min = spec.min ?? 0;
    const max = spec.max ?? 1;
    const step = spec.type === "int" ? 1 : "any";
    // Current value: a persisted override wins, else the backend default.
    const cur = name in sampling ? sampling[name] : def;
    const moved = Number(cur) !== Number(def);
    const span = max - min || 1;
    const fill = (((cur - min) / span) * 100).toFixed(2);
    const ghost = (((def - min) / span) * 100).toFixed(2);
    const nm = esc(name);
    return `
      <div class="knob" data-knob="${nm}">
        <span class="name">${nm}</span>
        <span class="val" data-moved="${moved}">${esc(this._fmt(cur, spec))}</span>
        <div class="track">
          <input type="range" data-knob-input="${nm}" data-type="${esc(spec.type || "")}"
                 min="${esc(min)}" max="${esc(max)}" step="${step}" value="${esc(cur)}"
                 style="--fill:${fill}%" aria-label="${nm}" />
          <span class="ghost" style="left:${ghost}%" title="default ${esc(this._fmt(def, spec))}"></span>
        </div>
        ${spec.description ? `<div class="desc">${esc(spec.description)}</div>` : ""}
      </div>`;
  }

  /** Display formatting — ints stay whole, floats trim to 2 places. */
  _fmt(v, spec) {
    const n = Number(v);
    if (spec.type === "int") return String(Math.round(n));
    return Number.isInteger(n) ? String(n) : n.toFixed(2);
  }

  /** Coerce a slider's string value back to its schema type. */
  _coerce(input) {
    const t = input.dataset.type;
    return t === "int" ? parseInt(input.value, 10) : t === "float" ? parseFloat(input.value) : input.value;
  }

  /**
   * Collect the knobs moved off their default into a minimal overrides map.
   * Default-valued knobs are omitted so request-scope sampling stays lean —
   * same diff discipline as the old /lab knob panel.
   */
  _overrides() {
    const voice = this._voice();
    const schema = this._schema(voice);
    const out = {};
    for (const input of this.$$("input[data-knob-input]")) {
      const name = input.dataset.knobInput;
      const val = this._coerce(input);
      if (Number.isNaN(val)) continue;
      const spec = schema[name];
      if (spec && Number(val) === Number(spec.default)) continue;
      out[name] = val;
    }
    return out;
  }

  /**
   * Open seam for the shell: dispatch a `forge-audition` event (bubbles +
   * composed). Telemetry only — the editor OWNS the actual sampling audition via
   * _runAudition (fork B). The shell logs this; it must NOT open a WS off it or
   * the take would synth twice.
   */
  _audition(detail) {
    const voice = this._voiceId();
    if (!voice) return;
    this.dispatchEvent(
      new CustomEvent("forge-audition", { detail: { voice, ...detail }, bubbles: true, composed: true }),
    );
  }

  /**
   * Run the LOCAL WS audition for the focused voice's current overrides:
   * cancel any in-flight one, synth a fixed sample over /v1/tts/stream, and play
   * the result in this editor's own <forge-waveform>. Mirrors
   * forge-serve-console._run — it owns its synth, its waveform, and its
   * forging flag the same way.
   */
  _runAudition() {
    const voice = this._voiceId();
    if (!voice) return;

    // Cancel/replace: abort the previous socket so only the newest take plays.
    if (this._audHandle) this._audHandle.abort();

    const wave = this.$("forge-waveform");
    const status = this.$(".audition-status");
    const setStatus = (state, text) => {
      if (!status) return;
      status.dataset.state = state;
      status.textContent = text || "";
    };

    // A synth IS in flight → run the focused card/anvil hot. forge-waveform
    // playback itself never writes forging; this audition legitimately does.
    store.set({ forging: true });
    setStatus("busy", "…");

    const handle = auditionVoice(voice, this._overrides());
    this._audHandle = handle;

    handle.promise
      .then(({ samples, sampleRate }) => {
        if (this._audHandle !== handle) return; // a newer audition superseded us
        if (wave) {
          wave.setPcm(samples, sampleRate); // true peaks + auto-WAV for playback
          wave.play?.();
        }
        setStatus("idle", "");
      })
      .catch((e) => {
        if (e.reason === "aborted") return; // replaced by a newer release — stay silent
        if (this._audHandle !== handle) return;
        setStatus("error", e.reason === "timeout" ? "timed out" : "failed");
      })
      .finally(() => {
        // Only the LATEST handle clears the global hot state. An aborted older
        // handle must NOT clear forging — the newer audition still owns it.
        if (this._audHandle === handle) {
          this._audHandle = null;
          store.set({ forging: false });
        }
      });
  }

  /** Abort any in-flight audition and un-stick `forging` if this editor owned it. */
  _teardownAudition() {
    if (!this._audHandle) return;
    this._audHandle.abort();
    this._audHandle = null;
    if (store.get("forging")) store.set({ forging: false });
  }

  bind() {
    // A re-render (new focused voice / registry reload) replaced #root and
    // orphaned any old socket — refresh() rebuilds the DOM but does NOT call
    // disconnectedCallback. Abort the orphan here so it can't play into a chip
    // that no longer exists or leave the anvil stuck hot.
    this._teardownAudition();

    // Sliders: live fill/readout while dragging; audition on thumb-release.
    for (const input of this.$$("input[data-knob-input]")) {
      const knob = input.closest(".knob");
      const val = knob.querySelector(".val");
      const min = Number(input.min);
      const span = Number(input.max) - min || 1;
      const schema = this._schema(this._voice());
      const spec = schema[input.dataset.knobInput] || {};
      const paint = () => {
        const v = this._coerce(input);
        input.style.setProperty("--fill", `${(((v - min) / span) * 100).toFixed(2)}%`);
        val.textContent = this._fmt(v, spec);
        val.dataset.moved = String(Number(v) !== Number(spec.default));
      };
      input.oninput = paint;
      // change fires on thumb-release / keyboard commit — the audition trigger.
      input.onchange = () => {
        paint();
        this._runAudition(); // (B): own the synth locally — play it in our chip
        this._audition({ sampling: this._overrides() }); // keep the shell seam open
      };
    }

    // Description: ~600ms debounced pause emits a forge-audition {description}
    // for the shell to log. Re-describing is a DESIGN op (ElevenLabs text→voice)
    // with no request-scope synth path — out of scope for U9, so this is
    // EVENT-ONLY. Do NOT open a WS here (no _runAudition); the editor only
    // auditions sampling, which the slider path above owns.
    const desc = this.$("#desc");
    if (desc) {
      desc.oninput = () => {
        clearTimeout(this._descTimer);
        this._descTimer = setTimeout(() => {
          this._audition({ description: desc.value });
        }, 600);
      };
    }
  }
}

customElements.define("forge-spec-editor", ForgeSpecEditor);

/*
 * <forge-empty-hero> — the cold-forge empty state + capability-aware door (U7).
 *
 * The first thing a newcomer meets: a centred "cold forge" anvil that WARMS
 * (ember) the instant the registry has its first voice — the same surface, just
 * hotter. The door it offers is capability-aware, read straight off
 * store.backends:
 *   - design-capable path advertised → "describe a voice" is the HERO; cloning
 *     from a clip is the quiet secondary.
 *   - no design path → "clone from a clip" is the HERO and the describe box is
 *     visibly GATED with a one-line reason. Never a dead button — a gate states
 *     why, an action invites.
 *
 * First paint is audible, not silent: a seeded default clip (the integrator
 * provides the URL via the `seed-src` attribute) renders in a <forge-waveform>
 * so the newcomer hears the forge before they touch it.
 *
 * Emits two CustomEvents the shell wires into the design/clone seams:
 *   forge-design  detail:{ description }   — text → voice
 *   forge-clone   detail:{ file }          — clip  → voice
 */

import { ForgeElement, esc } from "./base.js";
import { store } from "./store.js";

class ForgeEmptyHero extends ForgeElement {
  // voices: anvil warms on the first arrival. capabilities: is design ready
  // (the describe-vs-clone door). backends: is clone possible at all.
  // forging: the anvil runs hot while a synth is in flight.
  static observe = ["voices", "backends", "capabilities", "forging"];

  /** True once the registry holds at least one voice — the forge has caught. */
  _warm() {
    return (store.get("voices") || []).length > 0;
  }

  /**
   * Design-from-description readiness, straight off GET /v1/capabilities: a
   * cloud key (elevenlabs_configured) OR a local design model (design_local,
   * #60). This is an authoritative server signal, not a guess from the backend
   * list — ElevenLabs isn't a local backend, so it never appears in /v1/backends.
   * Clone is the always-available fallback; design is the gated capability.
   */
  _designReady() {
    const caps = store.get("capabilities");
    return !!(caps && (caps.elevenlabs_configured || caps.design_local));
  }

  /** Clone needs at least one installed TTS backend (else the forge is unforgeable). */
  _cloneReady() {
    return (store.get("backends") || []).some((b) => b && b.installed);
  }

  styles() {
    return `
      :host { display: block; height: 100%; }

      .hero { height: 100%; display: flex; flex-direction: column; align-items: center; justify-content: center;
          gap: var(--forge-gap); text-align: center; padding: 48px var(--forge-gap-lg); box-sizing: border-box; }

      /* The cold-forge mark — neutral at rest, ember once the forge catches. */
      .anvil { width: 88px; height: 88px; border-radius: 26px; display: grid; place-items: center; color: var(--forge-text-faint);
          background: radial-gradient(130px 96px at 50% 128%, var(--forge-ember-dim), transparent 70%);
          transition: color var(--forge-heat-ms) var(--forge-ease), filter var(--forge-heat-ms) var(--forge-ease); }
      .hero.warm .anvil { color: var(--forge-ember); filter: drop-shadow(0 0 14px var(--forge-ember-edge)); }
      /* While a synth is in flight the mark runs white-hot. */
      .hero.hot .anvil { color: var(--forge-ember-bright); filter: drop-shadow(0 0 18px var(--forge-ember-edge)); }

      h1 { font-size: 22px; font-weight: 620; margin: 0; letter-spacing: -0.01em; }
      .lede { color: var(--forge-text-dim); max-width: 40ch; margin: 0; line-height: 1.55; }

      /* The capability-aware door. Two paths; the hero one is primary, the other quiet. */
      .door { width: 100%; max-width: 460px; display: flex; flex-direction: column; gap: var(--forge-gap); margin-top: 4px; }
      .path-label { font-size: 11px; text-transform: uppercase; letter-spacing: 0.06em; color: var(--forge-text-faint); text-align: left; }

      /* describe-a-voice box */
      .describe { display: flex; flex-direction: column; gap: var(--forge-gap-sm); text-align: left; }
      .describe textarea { resize: none; min-height: 72px; font: inherit; font-size: 14px; color: var(--forge-text);
          background: var(--forge-inset); border: 1px solid var(--forge-border); border-radius: var(--forge-radius);
          padding: 12px 14px; outline: none; box-sizing: border-box; transition: border-color 120ms var(--forge-ease); }
      .describe textarea::placeholder { color: var(--forge-text-faint); }
      .describe textarea:focus { border-color: var(--forge-ember-edge); }
      .describe textarea:disabled { opacity: 0.55; cursor: not-allowed; }

      /* clone-from-a-clip drop-zone */
      .drop { display: grid; place-items: center; gap: 6px; padding: 22px; cursor: pointer; text-align: center;
          background: var(--forge-inset); border: 1px dashed var(--forge-border-strong); border-radius: var(--forge-radius);
          color: var(--forge-text-dim); font-size: 13px; transition: border-color 120ms var(--forge-ease), background 120ms var(--forge-ease); }
      .drop:hover, .drop.over { border-color: var(--forge-ember-edge); background: var(--forge-surface); color: var(--forge-text); }
      .drop strong { color: var(--forge-text); font-weight: 560; }
      .drop .sub { font-size: 12px; color: var(--forge-text-faint); }
      .drop input[type="file"] { display: none; }

      /* the forge button — ember primary */
      .btn { all: unset; cursor: pointer; font: inherit; font-size: 13px; font-weight: 560; align-self: flex-start;
          padding: 9px 18px; border-radius: var(--forge-radius-pill); background: var(--forge-ember); color: #2a1404;
          transition: filter 120ms var(--forge-ease); }
      .btn:hover { filter: brightness(1.08); }
      .btn:disabled { background: var(--forge-surface-2); color: var(--forge-text-faint); cursor: not-allowed; filter: none; }

      /* the gate — a stated reason, never a dead button */
      .gate { text-align: left; background: var(--forge-surface); border: 1px solid var(--forge-border); border-radius: var(--forge-radius);
          padding: 12px 14px; }
      .gate .gate-title { display: flex; align-items: center; gap: 8px; font-size: 13px; font-weight: 560; color: var(--forge-text-dim); }
      .gate .gate-title svg { width: 14px; height: 14px; color: var(--forge-text-faint); }
      .gate .gate-why { font-size: 12px; color: var(--forge-text-faint); margin: 6px 0 0; line-height: 1.5; }
      .gate .gate-why code { font-family: var(--forge-mono); font-size: 11px; color: var(--forge-text-dim); background: var(--forge-inset); border: 1px solid var(--forge-border); border-radius: var(--forge-radius-sm); padding: 1px 5px; }

      .quiet { opacity: 0.85; }

      /* the seeded clip — first paint is audible */
      .seed { width: 100%; max-width: 460px; display: flex; flex-direction: column; gap: 6px; text-align: left; margin-top: 4px; }
      .seed .seed-cap { font-size: 11px; color: var(--forge-text-faint); }
      .seed forge-waveform { display: block; width: 100%; }
    `;
  }

  render() {
    const warm = this._warm();
    const hot = !!store.get("forging");
    const designReady = this._designReady();
    const cloneReady = this._cloneReady();
    const heroClass = `hero${warm ? " warm" : ""}${hot ? " hot" : ""}`;

    // Three doors by capability: design ready → describe-hero; else clone ready →
    // clone-hero with describe gated; else neither → the unforgeable state names
    // what to install. A gate always states why; it is never a dead button.
    let door;
    if (designReady) door = this._designHero();
    else if (cloneReady) door = this._cloneHero();
    else door = this._unforgeable();

    // Identity copy: dark-studio, short, the metaphor lives in the verbs.
    const title = warm ? "The forge is warm" : "The forge is cold";
    const lede = warm
      ? "Your first voice has caught. Forge another — describe one or clone it from a clip."
      : "Forge your first voice. The forge runs cold until a voice catches.";

    return `<div class="${heroClass}">
      <div class="anvil">${this._anvilMark()}</div>
      <h1>${title}</h1>
      <p class="lede">${lede}</p>
      <div class="door">${door}</div>
      ${this._seed()}
    </div>`;
  }

  /** The cold-forge anvil mark — restrained line work, no clipart. */
  _anvilMark() {
    return `<svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 8h12l-1 4H7"/><path d="M12 12v4"/><path d="M8 20h8"/><path d="M19 8h2v3a3 3 0 0 1-3 3"/></svg>`;
  }

  /** Design-capable: describe-a-voice is the hero, clone is the quiet secondary. */
  _designHero() {
    return `${this._describeBlock(false)}${this._cloneBlock(true)}`;
  }

  /** No design path: clone is the hero, the describe box is gated with a reason. */
  _cloneHero() {
    return `${this._cloneBlock(false)}${this._describeGate()}`;
  }

  /**
   * The describe-a-voice path. `quiet` renders it as the secondary option.
   * The forge button stays disabled until there's a description — but the box
   * is always live (this branch only renders when design is ready).
   */
  _describeBlock(quiet) {
    return `<div class="describe${quiet ? " quiet" : ""}">
      <div class="path-label">${quiet ? "Or describe a new voice" : "Describe a voice"}</div>
      <textarea id="desc" placeholder="A warm, gravelly narrator — unhurried, late-night radio."></textarea>
      <button class="btn" id="forge-design" disabled>Forge from description</button>
    </div>`;
  }

  /**
   * The gated describe box — shown when no design path is configured. The
   * textarea is disabled and a one-line reason states WHY (and how to enable it),
   * so the path reads as "not here yet," never a dead button.
   */
  _describeGate() {
    return `<div class="gate quiet">
      <div class="gate-title">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="5" y="11" width="14" height="9" rx="2"/><path d="M8 11V8a4 4 0 0 1 8 0v3"/></svg>
        Describe a voice
      </div>
      <p class="gate-why">Designing a voice from a description needs a design path — set an <code>ELEVENLABS_API_KEY</code> to route to ElevenLabs Voice Design (local design is coming). Clone from a clip above for now.</p>
    </div>`;
  }

  /**
   * The unforgeable state — no design path AND no installed backend. The forge
   * is booted but can't make a voice yet; name the one thing to do (install a
   * backend) so the empty page is an instruction, not a dead end.
   */
  _unforgeable() {
    return `<div class="gate">
      <div class="gate-title">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="5" y="11" width="14" height="9" rx="2"/><path d="M8 11V8a4 4 0 0 1 8 0v3"/></svg>
        No way to forge yet
      </div>
      <p class="gate-why">The forge is running, but no TTS backend is installed — so it can't clone or design a voice. Install one to begin, e.g. <code>pip install "voice-forge-tts[f5]"</code>, then reload.</p>
    </div>`;
  }

  /**
   * The clone-from-a-clip drop-zone. `quiet` renders it as the secondary option.
   * Click opens the file picker; drag-drop is wired in bind().
   */
  _cloneBlock(quiet) {
    return `<div class="${quiet ? "quiet" : ""}">
      <div class="path-label">${quiet ? "Or clone from a clip" : "Clone from a clip"}</div>
      <label class="drop" id="drop">
        <strong>Drop a voice clip</strong>
        <span class="sub">or click to pick a file · 10–30s of clean speech</span>
        <input type="file" id="clip" accept="audio/*" />
      </label>
    </div>`;
  }

  /**
   * The seeded default clip — provided by the integrator via `seed-src`. Renders
   * through a sibling <forge-waveform> so first paint is audible, not a silent
   * empty state. Omitted entirely when no seed URL is supplied.
   */
  _seed() {
    const src = this.getAttribute("seed-src");
    if (!src) return "";
    return `<div class="seed">
      <span class="seed-cap">Hear the forge — a seeded sample</span>
      <forge-waveform src="${esc(src)}"></forge-waveform>
    </div>`;
  }

  bind() {
    // Live the design button only when there's a description to forge from.
    const desc = this.$("#desc");
    const designBtn = this.$("#forge-design");
    if (desc && designBtn) {
      const sync = () => {
        designBtn.disabled = desc.value.trim().length === 0;
      };
      desc.oninput = sync;
      sync();
      designBtn.onclick = () => {
        const description = desc.value.trim();
        if (!description) return;
        this._emit("forge-design", { description });
      };
    }

    // Clone path: file picker + drag-drop, both funnel one File out.
    const clip = this.$("#clip");
    if (clip) {
      clip.onchange = () => {
        const file = clip.files && clip.files[0];
        if (file) this._emit("forge-clone", { file });
      };
    }
    const drop = this.$("#drop");
    if (drop) {
      const over = (on) => (e) => {
        e.preventDefault();
        drop.classList.toggle("over", on);
      };
      drop.ondragover = over(true);
      drop.ondragleave = over(false);
      drop.ondrop = (e) => {
        e.preventDefault();
        drop.classList.remove("over");
        const file = e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0];
        if (file) this._emit("forge-clone", { file });
      };
    }
  }

  /** Fire a bubbling, composed CustomEvent so the shell catches it past the shadow root. */
  _emit(name, detail) {
    this.dispatchEvent(new CustomEvent(name, { detail, bubbles: true, composed: true }));
  }
}

customElements.define("forge-empty-hero", ForgeEmptyHero);

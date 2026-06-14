/*
 * <forge-app> — the studio shell.
 *
 * U1: no-build foundation + capability/voice load.
 * U2 (this unit): the single-shell IA — one layout where the empty newcomer and
 *   the loaded fleet are the SAME surface at different fill. Three regions —
 *   rail (the fleet) / subject (the focused voice or the cold-forge hero) /
 *   inspector (details) — with one Calm/Bench density control. Calm hides the
 *   rail+inspector and centres the canonical flow; Bench reveals the fleet grid
 *   and the inspector. Output docks in the subject, never a far-off scroll (R4).
 *
 * Cards (U4), the audio layer (U3), and the cold-start behaviour (U7) fill these
 * regions in later units; here the regions and the density behaviour are real.
 */

import { ForgeElement, esc, asList } from "./base.js";
import { store, setDensity } from "./store.js";

// Register the component layer (side-effect imports define the custom elements).
import "./forge-waveform.js";
import "./forge-voice-card.js";
import "./forge-backend-chip.js";
import "./forge-empty-hero.js";
import "./forge-spec-editor.js";
import "./forge-serve-console.js";
import "./forge-contact-sheet.js";

class ForgeApp extends ForgeElement {
  // Not "forging": the shell renders nothing off it (cards + hero own their own
  // hot face), and re-rendering the whole fleet on every synth would needlessly
  // rebuild every card — and tear down any take playing inside one.
  static observe = ["voices", "backends", "density", "focused"];

  connectedCallback() {
    super.connectedCallback();
    this._wireEvents();
    this._load();
  }

  // Delegated listeners on the HOST — not in bind(). bind() re-runs on every
  // _paint() (base.js:46), which fires on every voices/backends/density/focused
  // change, so anything wired there would be re-added (and duplicated) on each
  // render. The host element is the stable outermost node: it exists from
  // construction and _paint() only rewrites the shadow root's innerHTML, never
  // touching listeners on `this`. The children dispatch bubbles+composed events,
  // so they re-target here regardless of which re-rendered child fired them.
  _wireEvents() {
    this.addEventListener("forge-clone", (e) => this._onClone(e.detail?.file));
    this.addEventListener("forge-backend-change", (e) => this._onBackendChange(e.detail?.backend));

    // OUT OF SCOPE for this slice: design → contact-sheet → audition → pick, and
    // the serve console run. Those belong to the design/audition unit that
    // introduces their flow (and, for pick/audition, their emitters). Stubbed as
    // logged no-ops so the event is caught at the host — not silently swallowed —
    // and the next unit has an obvious seam to fill.
    this.addEventListener("forge-design", (e) => this._onDesign(e.detail));
    this.addEventListener("forge-serve", (e) => this._onServe(e.detail));
  }

  // forge-clone {file}: register an uploaded clip as a new bound voice.
  // The hero collects neither id nor persona, so derive both from the filename
  // (U7 "born bound": a persona makes the new card land on the `bound` face).
  // The backend is inferred server-side, then passed on register so the voice is
  // created on the right backbone in one shot.
  async _onClone(file) {
    if (!file) return;

    const base = (file.name || "voice").replace(/\.[^.]+$/, "");
    const voiceId =
      base.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "") || "voice";
    const persona = base.replace(/[-_]+/g, " ").trim() || voiceId;

    // Pre-focus the would-be card, then run the anvil hot. Until _load() returns
    // there is no card for voiceId, so the hero runs hot during the in-flight
    // window (forge-empty-hero reads `forging`) — the correct cold-start signal.
    store.set({ focused: voiceId, forging: true });

    try {
      // Recommend a backend (cold-start one-tap). Best-effort: if it fails the
      // server falls back to the configured default on register anyway.
      let backend = "";
      try {
        const inf = await fetch("/v1/forge/infer-backend").then((r) => (r.ok ? r.json() : null));
        backend = inf?.backend || "";
      } catch {
        backend = "";
      }

      const form = new FormData();
      form.append("ref_audio", file); // server Form field (server.py:764)
      form.append("persona", persona); // born bound (server.py:772)
      if (backend) form.append("backend", backend); // inferred backbone (server.py:769)

      // No Content-Type header — the browser sets the multipart boundary.
      const res = await fetch(`/voices/${encodeURIComponent(voiceId)}`, {
        method: "POST",
        body: form,
      });

      if (res.ok) {
        await this._load(); // re-pull /v1/audio/voices → the new bound card appears
        store.set({ focused: voiceId, forging: false });
      } else {
        // e.g. 503 when Whisper is missing, 409 on a name collision. Un-stick the
        // anvil so the UI isn't left dead, and surface why.
        store.set({ forging: false });
        this._noteError(res);
      }
    } catch (err) {
      store.set({ forging: false });
      this._noteError(err);
    }
  }

  // forge-backend-change {backend}: override the focused voice's backend in place.
  // The chip's event carries only the backend name — no voice id — so the target
  // is store.focused (clicking a card focuses it before its chip is reachable).
  async _onBackendChange(backend) {
    const voiceId = store.get("focused");
    if (!voiceId || !backend) return; // a chip can sit on an unfocused card — guard it

    store.set({ forging: true });
    try {
      const res = await fetch(`/voices/${encodeURIComponent(voiceId)}/backend`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ backend }),
      });
      if (res.ok) {
        await this._load(); // re-pull the registry so the card + chip re-render from server truth
      } else {
        this._noteError(res);
      }
    } catch (err) {
      this._noteError(err);
    } finally {
      store.set({ forging: false });
    }
  }

  // OUT OF SCOPE — these belong to the design/audition unit (the flow + the
  // pick/audition emitters land there). Caught here so they aren't silently
  // dropped; intentionally not implemented in this slice.
  _onDesign(detail) {
    console.info("forge-design received (design flow not wired yet)", detail);
  }

  _onServe(detail) {
    console.info("forge-serve received (serve flow not wired yet)", detail);
  }

  // Minimal error surface for this slice: log it, no new UI. A future unit adds a
  // store error key + hero banner (e.g. 503 → "Cloning needs Whisper"). The
  // forging:false already taken by callers un-sticks the anvil so the UI is live.
  _noteError(errOrRes) {
    if (errOrRes instanceof Response) {
      console.error(`forge: request failed (${errOrRes.status} ${errOrRes.statusText})`, errOrRes);
    } else {
      console.error("forge: request error", errOrRes);
    }
  }

  async _load() {
    try {
      const [backends, voices, capabilities] = await Promise.all([
        fetch("/v1/backends").then((r) => (r.ok ? r.json() : null)),
        fetch("/v1/audio/voices").then((r) => (r.ok ? r.json() : null)),
        fetch("/v1/capabilities").then((r) => (r.ok ? r.json() : null)),
      ]);
      // The list endpoints answer with an OpenAI-style {data:[…]} envelope
      // (VoicesList / BackendsList). Normalize to bare arrays here — the one
      // place that knows the wire shape — so every component reads a clean
      // store.voices / store.backends array, never re-derives the envelope.
      // /v1/capabilities is a flat object (design-readiness) — kept as-is.
      store.set({ backends: asList(backends), voices: asList(voices), capabilities });
    } catch {
      store.set({ backends: [], voices: [], capabilities: null });
    }
  }

  styles() {
    return `
      :host { display: block; min-height: 100vh; background: var(--forge-bg); color: var(--forge-text); font-family: var(--forge-font); }
      #root { display: flex; flex-direction: column; min-height: 100vh; }

      header { display: flex; align-items: center; gap: var(--forge-gap); padding: 14px var(--forge-gap-lg); border-bottom: 1px solid var(--forge-border); }
      .mark { display: flex; align-items: center; gap: 10px; font-weight: 650; letter-spacing: -0.01em; }
      .spark { width: 16px; height: 16px; color: var(--forge-ember); filter: drop-shadow(0 0 6px var(--forge-ember-edge)); }
      .mark small { color: var(--forge-text-faint); font-weight: 500; margin-left: 2px; }
      .spacer { flex: 1; }
      .density { display: flex; gap: 2px; background: var(--forge-inset); border: 1px solid var(--forge-border); border-radius: var(--forge-radius-pill); padding: 3px; }
      .density button { all: unset; cursor: pointer; font: inherit; font-size: 12px; color: var(--forge-text-dim); padding: 4px 12px; border-radius: var(--forge-radius-pill); }
      .density button[aria-pressed="true"] { background: var(--forge-surface-2); color: var(--forge-text); }

      /* The single-shell grid. Calm = subject only; Bench = rail | subject | inspector. */
      .shell { flex: 1; display: grid; min-height: 0; grid-template-columns: 1fr; }
      .shell.bench { grid-template-columns: 260px minmax(0, 1fr) 300px; }

      .rail, .inspector { display: none; flex-direction: column; min-height: 0; overflow-y: auto; }
      .shell.bench .rail { display: flex; border-right: 1px solid var(--forge-border); }
      .shell.bench .inspector { display: flex; border-left: 1px solid var(--forge-border); }
      .region-label { font-size: 11px; text-transform: uppercase; letter-spacing: 0.06em; color: var(--forge-text-faint); padding: 14px var(--forge-gap) 6px; }

      .rail ul { list-style: none; margin: 0; padding: 0 var(--forge-gap-sm) var(--forge-gap); display: flex; flex-direction: column; gap: 2px; }
      .rail li { padding: 8px 10px; border-radius: var(--forge-radius-sm); cursor: pointer; }
      .rail li:hover { background: var(--forge-surface); }
      .rail li[aria-selected="true"] { background: var(--forge-surface-2); }
      .rail .vid { font-size: 13px; font-weight: 560; }
      .rail .vmeta { font-size: 11px; color: var(--forge-text-dim); }

      .subject { display: flex; flex-direction: column; min-height: 0; }

      /* Cold-forge hero — the empty state warms when the first voice lands (U7). */
      .hero { flex: 1; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 14px; text-align: center; padding: 48px; }
      .anvil { width: 96px; height: 96px; color: var(--forge-text-faint); border-radius: 28px; display: grid; place-items: center;
          background: radial-gradient(140px 100px at 50% 130%, var(--forge-ember-dim), transparent 70%); transition: color var(--forge-heat-ms) var(--forge-ease); }
      .hero h1 { font-size: 22px; font-weight: 620; margin: 0; }
      .hero p { color: var(--forge-text-dim); max-width: 38ch; margin: 0; line-height: 1.55; }
      .count { font-family: var(--forge-mono); color: var(--forge-text-faint); font-size: 12px; }

      /* Fleet grid in the subject (Calm shows it here; Bench leans on the rail).
         Each cell is a self-contained <forge-voice-card>. */
      .fleet { padding: var(--forge-gap-lg); display: grid; gap: var(--forge-gap-sm); grid-template-columns: repeat(var(--forge-cols), minmax(0, 1fr)); align-content: start; }

      /* Inspector: the focused voice's bench — spec editor stacked over the serve console. */
      .inspector .empty { color: var(--forge-text-faint); font-size: 13px; padding: var(--forge-gap); }
      .inspector .focused { padding: var(--forge-gap); display: flex; flex-direction: column; gap: var(--forge-gap); }
    `;
  }

  render() {
    const density = store.get("density");
    document.documentElement.dataset.density = density;
    const voices = store.get("voices") || [];
    const focused = store.get("focused");
    const bench = density === "bench";

    const header = `
      <header>
        <div class="mark">
          <svg class="spark" viewBox="0 0 16 16" aria-hidden="true"><path fill="currentColor" d="M8 0l1.6 4.9L14.5 3 11 7l3.5 4-4.9-1.6L8 16l-1.6-6.6L1.5 11 5 7 1.5 3l4.9 1.9z"/></svg>
          <span>forge<small>voice-forge studio</small></span>
        </div>
        <div class="spacer"></div>
        <div class="density" role="group" aria-label="density">
          <button data-density="calm" aria-pressed="${density === "calm"}">Calm</button>
          <button data-density="bench" aria-pressed="${bench}">Bench</button>
        </div>
      </header>`;

    const rail = `
      <aside class="rail">
        <div class="region-label">Fleet · ${voices.length}</div>
        <ul>${voices.map((v) => this._railItem(v, focused)).join("")}</ul>
      </aside>`;

    const subject = `<section class="subject">${
      voices.length === 0 ? this._hero() : this._fleet(voices)
    }</section>`;

    const inspector = `<aside class="inspector">${this._inspector(voices, focused)}</aside>`;

    return header + `<div class="shell${bench ? " bench" : ""}">${rail}${subject}${inspector}</div>`;
  }

  _railItem(v, focused) {
    const id = esc(v.voice_id || v.id || "");
    const persona = esc(v.persona || "—");
    return `<li data-voice="${id}" aria-selected="${id === focused}"><div class="vid">${id}</div><div class="vmeta">${persona}</div></li>`;
  }

  _hero() {
    // The cold-start hero is its own component (U7): the capability-aware door
    // (describe vs clone, gated by what's installed) over a cold forge that
    // warms when the first voice lands. Self-contained — reads store itself and
    // emits forge-design / forge-clone for the shell to route.
    return `<forge-empty-hero></forge-empty-hero>`;
  }

  _fleet(voices) {
    // Each voice is a self-contained <forge-voice-card>: it reads its own record
    // from store.voices, paints its own face (ghost/forging/forged/bound), and
    // sets store.focused on click — the shell only lays them out.
    return `<div class="fleet">${voices
      .map((v) => `<forge-voice-card voice-id="${esc(v.voice_id || v.id || "")}"></forge-voice-card>`)
      .join("")}</div>`;
  }

  _inspector(voices, focused) {
    const v = voices.find((x) => (x.voice_id || x.id) === focused);
    if (!v) return `<div class="empty">Select a voice to tune and serve it.</div>`;
    // The inspector is the focused voice's bench: its tunables spec sheet over
    // the serve console. Both follow store.focused on their own — the
    // voice-id attribute just pins this instance to the current subject.
    const id = esc(v.voice_id || v.id || "");
    return `<div class="focused">
      <forge-spec-editor voice-id="${id}"></forge-spec-editor>
      <forge-serve-console></forge-serve-console>
    </div>`;
  }

  bind() {
    for (const btn of this.$$(".density button")) {
      btn.onclick = () => setDensity(btn.dataset.density);
    }
    for (const el of this.$$("[data-voice]")) {
      el.onclick = () => store.set({ focused: el.dataset.voice });
    }
  }
}

customElements.define("forge-app", ForgeApp);

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

import { ForgeElement, esc } from "./base.js";
import { store, setDensity } from "./store.js";

class ForgeApp extends ForgeElement {
  static observe = ["voices", "backends", "density", "focused", "forging"];

  connectedCallback() {
    super.connectedCallback();
    this._load();
  }

  async _load() {
    try {
      const [backends, voices] = await Promise.all([
        fetch("/v1/backends").then((r) => (r.ok ? r.json() : null)),
        fetch("/v1/audio/voices").then((r) => (r.ok ? r.json() : null)),
      ]);
      store.set({ backends, voices: (voices && (voices.voices || voices)) || [] });
    } catch {
      store.set({ backends: null, voices: [] });
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

      /* Fleet grid in the subject (Calm shows it here; Bench leans on the rail). */
      .fleet { padding: var(--forge-gap-lg); display: grid; gap: var(--forge-gap-sm); grid-template-columns: repeat(var(--forge-cols), minmax(0, 1fr)); align-content: start; }
      .vcard { background: var(--forge-surface); border: 1px solid var(--forge-border); border-radius: var(--forge-radius); padding: var(--forge-card-pad); cursor: pointer; }
      .vcard:hover { border-color: var(--forge-border-strong); }
      .vcard[aria-selected="true"] { border-color: var(--forge-ember-edge); }
      .vcard .vid { font-weight: 600; }
      .vcard .vmeta { color: var(--forge-text-dim); font-size: 12px; margin-top: 4px; }

      .inspector .empty { color: var(--forge-text-faint); font-size: 13px; padding: var(--forge-gap); }
      .inspector .focused { padding: var(--forge-gap); }
      .inspector .focused .vid { font-weight: 620; }
      .inspector .focused dl { margin: 12px 0 0; display: grid; grid-template-columns: auto 1fr; gap: 6px 12px; font-size: 13px; }
      .inspector .focused dt { color: var(--forge-text-faint); }
    `;
  }

  render() {
    const density = store.get("density");
    document.documentElement.dataset.density = density;
    const voices = store.get("voices") || [];
    const backends = store.get("backends");
    const focused = store.get("focused");
    const installed = backends && backends.backends ? backends.backends.filter((b) => b.installed).length : 0;
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
      voices.length === 0 ? this._hero(installed) : this._fleet(voices, focused)
    }</section>`;

    const inspector = `<aside class="inspector">${this._inspector(voices, focused)}</aside>`;

    return header + `<div class="shell${bench ? " bench" : ""}">${rail}${subject}${inspector}</div>`;
  }

  _railItem(v, focused) {
    const id = esc(v.voice_id || v.id || "");
    const persona = esc(v.persona || "—");
    return `<li data-voice="${id}" aria-selected="${id === focused}"><div class="vid">${id}</div><div class="vmeta">${persona}</div></li>`;
  }

  _hero(installed) {
    return `<div class="hero">
      <div class="anvil">
        <svg width="42" height="42" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M3 8h12l-1 4H7"/><path d="M12 12v4"/><path d="M8 20h8"/><path d="M19 8h2v3a3 3 0 0 1-3 3"/></svg>
      </div>
      <h1>The forge is cold</h1>
      <p>Forge your first voice — design one from a description or clone it from a clip, then bind it to an agent persona. ${installed} backend${installed === 1 ? "" : "s"} ready.</p>
      <div class="count">empty registry · same surface, no data yet</div>
    </div>`;
  }

  _fleet(voices, focused) {
    return `<div class="fleet">${voices
      .map((v) => {
        const id = esc(v.voice_id || v.id || "");
        const persona = esc(v.persona || "—");
        const backend = esc(v.backend || "");
        return `<div class="vcard" data-voice="${id}" aria-selected="${id === focused}"><div class="vid">${id}</div><div class="vmeta">${persona} · ${backend}</div></div>`;
      })
      .join("")}</div>`;
  }

  _inspector(voices, focused) {
    const v = voices.find((x) => (x.voice_id || x.id) === focused);
    if (!v) return `<div class="empty">Select a voice to inspect it.</div>`;
    return `<div class="focused">
      <div class="vid">${esc(v.voice_id || v.id || "")}</div>
      <dl>
        <dt>persona</dt><dd>${esc(v.persona || "—")}</dd>
        <dt>backend</dt><dd>${esc(v.backend || "—")}</dd>
        <dt>language</dt><dd>${esc(v.language || "—")}</dd>
      </dl>
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

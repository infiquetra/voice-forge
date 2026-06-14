/*
 * <forge-app> — the studio shell.
 *
 * U1 (this unit): the dark-studio chrome + the store + capability/voice loading,
 * proving the no-build foundation serves and talks to the existing API. The
 * real rail / subject / inspector layout and the Calm/Bench density behaviour
 * land in U2; the cold-forge hero becomes audible + interactive in U7.
 */

import { ForgeElement, esc } from "./base.js";
import { store, setDensity } from "./store.js";

class ForgeApp extends ForgeElement {
  static observe = ["voices", "backends", "density", "forging"];

  connectedCallback() {
    super.connectedCallback();
    this._load();
  }

  async _load() {
    // Capability snapshot (drives the capability-aware door, U7) + the registry.
    try {
      const [backends, voices] = await Promise.all([
        fetch("/v1/backends").then((r) => (r.ok ? r.json() : null)),
        fetch("/v1/audio/voices").then((r) => (r.ok ? r.json() : null)),
      ]);
      store.set({
        backends,
        voices: (voices && (voices.voices || voices)) || [],
      });
    } catch (e) {
      // Booted-but-API-unreachable is itself a state worth showing, not a crash.
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
      main { flex: 1; display: flex; flex-direction: column; }
      .hero { flex: 1; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 14px; text-align: center; padding: 48px; }
      .anvil { width: 88px; height: 88px; color: var(--forge-text-faint); border-radius: 24px; display: grid; place-items: center; background:
          radial-gradient(120px 90px at 50% 120%, var(--forge-ember-dim), transparent 70%); transition: color var(--forge-heat-ms) var(--forge-ease); }
      .hero h1 { font-size: 22px; font-weight: 620; margin: 0; }
      .hero p { color: var(--forge-text-dim); max-width: 36ch; margin: 0; line-height: 1.5; }
      .count { font-family: var(--forge-mono); color: var(--forge-text-faint); font-size: 12px; }
      ul.voices { list-style: none; margin: 0; padding: var(--forge-gap-lg); display: grid; gap: var(--forge-gap-sm); grid-template-columns: repeat(var(--forge-cols), 1fr); }
      ul.voices li { background: var(--forge-surface); border: 1px solid var(--forge-border); border-radius: var(--forge-radius); padding: var(--forge-card-pad); }
      ul.voices .vid { font-weight: 600; }
      ul.voices .meta { color: var(--forge-text-dim); font-size: 12px; margin-top: 4px; }
    `;
  }

  render() {
    const density = store.get("density");
    document.documentElement.dataset.density = density;
    const voices = store.get("voices") || [];
    const backends = store.get("backends");
    const installed = backends && backends.backends
      ? backends.backends.filter((b) => b.installed).length
      : 0;

    const header = `
      <header>
        <div class="mark">
          <svg class="spark" viewBox="0 0 16 16" aria-hidden="true"><path fill="currentColor" d="M8 0l1.6 4.9L14.5 3 11 7l3.5 4-4.9-1.6L8 16l-1.6-6.6L1.5 11 5 7 1.5 3l4.9 1.9z"/></svg>
          <span>forge<small>voice-forge studio</small></span>
        </div>
        <div class="spacer"></div>
        <div class="density" role="group" aria-label="density">
          <button data-density="calm" aria-pressed="${density === "calm"}">Calm</button>
          <button data-density="bench" aria-pressed="${density === "bench"}">Bench</button>
        </div>
      </header>`;

    const body = voices.length === 0
      ? `<div class="hero">
           <div class="anvil">
             <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M3 8h12l-1 4H7"/><path d="M12 12v4"/><path d="M8 20h8"/><path d="M19 8h2v3a3 3 0 0 1-3 3"/></svg>
           </div>
           <h1>The forge is cold</h1>
           <p>Forge your first voice — design one from a description or clone it from a clip, then bind it to an agent persona. ${installed} backend${installed === 1 ? "" : "s"} ready.</p>
           <div class="count">empty registry · foundation online</div>
         </div>`
      : `<ul class="voices">${voices.map((v) => {
          const id = esc(v.voice_id || v.id || "");
          const persona = esc(v.persona || "—");
          const backend = esc(v.backend || "");
          return `<li><div class="vid">${id}</div><div class="meta">${persona} · ${backend}</div></li>`;
        }).join("")}</ul>`;

    return header + `<main>${body}</main>`;
  }

  bind() {
    for (const btn of this.$$(".density button")) {
      btn.onclick = () => setDensity(btn.dataset.density);
    }
  }
}

customElements.define("forge-app", ForgeApp);

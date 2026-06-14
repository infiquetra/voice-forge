/*
 * <forge-backend-chip> — the inferred-backend "why" chip.
 *
 * U6: the engine that gets picked is inferred, not chosen — so the pick has to
 * EXPLAIN itself and stay overridable in place. At rest it's a small monospace
 * pill: the engine name + a one-line plain-language rationale ("kept the
 * accent"). Click flips it IN PLACE into an inline override — a <select> of the
 * installed backends, the why text alongside — then settles back to a pill once
 * a choice lands (or the user dismisses it).
 *
 * Override dispatches a bubbling `forge-backend-change` (detail:{backend}); the
 * integrator owns the re-inference + re-synthesis. The chip just states the
 * pick and lets you contest it. Restrained ember: the pill runs a faint hot
 * border, not a glow — this is metadata, not the forge fire.
 *
 * Attributes:
 *   backend  — inferred engine id (e.g. "f5"); the current pick.
 *   why      — one-line plain rationale for the pick.
 * Reads store.backends for the installed/not-installed option set (so it stays
 * in sync as backends load); not-installed backends render as ghost/disabled.
 */

import { ForgeElement, esc } from "./base.js";
import { store } from "./store.js";

class ForgeBackendChip extends ForgeElement {
  static observe = ["backends"];

  static get observedAttributes() {
    return ["backend", "why"];
  }

  constructor() {
    super();
    // local-only flip state (not in the shared store): pill <-> override.
    this._editing = false;
  }

  attributeChangedCallback() {
    // Re-render when the integrator swaps the inferred pick or rationale.
    this.refresh();
  }

  /** The currently-displayed engine: attribute is the source of truth. */
  get _backend() {
    return this.getAttribute("backend") || "";
  }

  get _why() {
    return this.getAttribute("why") || "";
  }

  /** Installed-backends snapshot from the store (drives the option set). */
  _options() {
    const b = store.get("backends");
    return (b && b.backends) || [];
  }

  styles() {
    return `
      :host { display: inline-block; vertical-align: middle; font-family: var(--forge-mono); }

      /* --- resting pill --- */
      .chip { all: unset; box-sizing: border-box; display: inline-flex; align-items: center; gap: 7px;
        max-width: 100%; cursor: pointer; font-size: 12px; line-height: 1; color: var(--forge-text-dim);
        background: var(--forge-inset); border: 1px solid var(--forge-ember-edge);
        border-radius: var(--forge-radius-pill); padding: 5px 11px; }
      .chip:hover { background: var(--forge-surface); border-color: var(--forge-ember); color: var(--forge-text); }
      .chip:focus-visible { outline: 2px solid var(--forge-ember-edge); outline-offset: 1px; }
      .chip .engine { color: var(--forge-ember); font-weight: 600; letter-spacing: 0.01em; }
      .chip .why { color: var(--forge-text-faint); font-weight: 400; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
      .chip .caret { color: var(--forge-text-faint); font-size: 10px; flex: none; }

      /* --- flipped: inline override --- */
      .override { display: inline-flex; align-items: center; gap: var(--forge-gap-sm);
        background: var(--forge-inset); border: 1px solid var(--forge-ember); border-radius: var(--forge-radius-pill);
        padding: 4px 6px 4px 11px; font-size: 12px; }
      .override select { all: unset; cursor: pointer; font: inherit; font-family: var(--forge-mono);
        color: var(--forge-text); background: var(--forge-surface-2); border: 1px solid var(--forge-border);
        border-radius: var(--forge-radius-sm); padding: 3px 8px; }
      .override select:focus-visible { outline: 2px solid var(--forge-ember-edge); outline-offset: 1px; }
      .override select option { background: var(--forge-surface); color: var(--forge-text); }
      .override select option:disabled { color: var(--forge-text-faint); }
      .override .why { color: var(--forge-text-faint); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
      .override .x { all: unset; cursor: pointer; flex: none; color: var(--forge-text-faint); font-size: 13px;
        line-height: 1; padding: 2px 5px; border-radius: var(--forge-radius-sm); }
      .override .x:hover { color: var(--forge-text); background: var(--forge-surface-2); }
      .override .x:focus-visible { outline: 2px solid var(--forge-ember-edge); outline-offset: 1px; }
    `;
  }

  render() {
    return this._editing ? this._renderOverride() : this._renderPill();
  }

  _renderPill() {
    const engine = esc(this._backend || "auto");
    const why = this._why;
    const whyHtml = why ? `<span class="why" title="${esc(why)}">${esc(why)}</span>` : "";
    return `<button class="chip" type="button" aria-label="backend ${engine}${
      why ? " — " + esc(why) : ""
    }, click to override">
      <span class="engine">${engine}</span>${whyHtml}
      <span class="caret" aria-hidden="true">▾</span>
    </button>`;
  }

  _renderOverride() {
    const current = this._backend;
    const why = this._why;
    const opts = this._options()
      .map((b) => {
        const name = esc(b.name || "");
        const installed = !!b.installed;
        const sel = b.name === current ? " selected" : "";
        const dis = installed ? "" : " disabled";
        const ghost = installed ? "" : " · not installed";
        return `<option value="${name}"${sel}${dis}>${name}${ghost}</option>`;
      })
      .join("");
    const whyHtml = why ? `<span class="why" title="${esc(why)}">${esc(why)}</span>` : "";
    return `<span class="override" role="group" aria-label="override backend">
      <select aria-label="backend">${opts}</select>${whyHtml}
      <button class="x" type="button" aria-label="cancel override">✕</button>
    </span>`;
  }

  bind() {
    const chip = this.$(".chip");
    if (chip) chip.onclick = () => this._open();

    const select = this.$("select");
    if (select) {
      // Focus + open the picker immediately on flip — the click that flipped us
      // shouldn't cost a second click to start choosing.
      select.focus();
      select.onchange = () => this._commit(select.value);
    }

    const x = this.$(".x");
    if (x) x.onclick = () => this._close();
  }

  _open() {
    this._editing = true;
    this.refresh();
  }

  _close() {
    this._editing = false;
    this.refresh();
  }

  _commit(backend) {
    // No-op if nothing changed; otherwise tell the integrator to re-infer.
    if (backend && backend !== this._backend) {
      this.dispatchEvent(
        new CustomEvent("forge-backend-change", {
          detail: { backend },
          bubbles: true,
          composed: true,
        }),
      );
    }
    this._close();
  }
}

customElements.define("forge-backend-chip", ForgeBackendChip);

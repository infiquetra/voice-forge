/*
 * <forge-contact-sheet> — the audition contact sheet (U8).
 *
 * The harness forges N candidates for one prompt; this is the wall you cull them
 * against. A responsive grid of tiles — each a <forge-waveform> + label — with
 * the photographer's-loupe register: keyboard-driven, fast, throwaway. Move
 * focus (J/K or arrows), Space auditions the focused tile, X rejects it (the
 * tile dims and slides into a reject tray so the eye stops returning to it),
 * Enter keeps it and dispatches `forge-pick`.
 *
 * Silence-collapse (LLM-backbone TTS sometimes emits a flat, near-silent take)
 * is the dominant failure mode, so dead candidates — peak < 0.05 — arrive
 * PRE-GREYED and struck: the <forge-waveform> renders them flat and the tile
 * starts dimmed, so the eye skips them before a key is ever pressed.
 *
 * Driven by a `candidates` PROPERTY (set imperatively by the integrator), not a
 * store slice — the audition set is transient and per-run. Local cull state
 * (focus index, rejected ids) lives on the instance and re-paints via refresh().
 */

import { ForgeElement, esc } from "./base.js";
import { store } from "./store.js";

const SILENCE_PEAK = 0.05; // below this the take has collapsed to silence

class ForgeContactSheet extends ForgeElement {
  // forging drives the ember "hot" wash while a take auditions; the rest is local.
  static observe = ["forging"];

  constructor() {
    super();
    this._candidates = [];
    this._focus = 0; // index into the live (non-rejected) tiles
    this._rejected = new Set(); // candidate ids slid to the tray
    this._audio = null; // the single audition <audio>, reused per play
  }

  /** Imperative property: the audition set for this run. */
  set candidates(list) {
    this._candidates = (Array.isArray(list) ? list : []).map((c, i) => this._prep(c, i));
    this._focus = 0;
    this._rejected.clear();
    this.refresh();
  }

  get candidates() {
    return this._candidates;
  }

  /** Normalise one candidate + decide silence up front (eye skips dead takes). */
  _prep(c, i) {
    const id = c.id != null ? String(c.id) : `cand-${i}`;
    const silent = c.silent === true || this._peak(c.pcm) < SILENCE_PEAK;
    return { id, src: c.src || null, pcm: c.pcm || null, sampleRate: c.sampleRate || 24000, label: c.label || id, silent };
  }

  /** Peak amplitude of a float32 PCM frame; null pcm reads as loud (not silent). */
  _peak(pcm) {
    if (!pcm || !pcm.length) return Infinity;
    let peak = 0;
    for (let i = 0; i < pcm.length; i++) {
      const a = Math.abs(pcm[i]);
      if (a > peak) peak = a;
    }
    return peak;
  }

  connectedCallback() {
    super.connectedCallback();
    this.tabIndex = 0; // the sheet itself takes the keyboard
    this._onKey = (e) => this._key(e);
    this.addEventListener("keydown", this._onKey);
  }

  disconnectedCallback() {
    super.disconnectedCallback();
    this.removeEventListener("keydown", this._onKey);
    if (this._audio) this._audio.pause();
  }

  /** Live tiles, in display order — rejected ones are tucked in the tray. */
  _live() {
    return this._candidates.filter((c) => !this._rejected.has(c.id));
  }

  _key(e) {
    const live = this._live();
    if (!live.length) return;
    const k = e.key;
    if (k === "j" || k === "J" || k === "ArrowRight" || k === "ArrowDown") {
      this._move(1, live.length);
    } else if (k === "k" || k === "K" || k === "ArrowLeft" || k === "ArrowUp") {
      this._move(-1, live.length);
    } else if (k === " " || k === "Spacebar") {
      this._play(live[this._focus]);
    } else if (k === "x" || k === "X") {
      this._reject(live[this._focus]);
    } else if (k === "Enter") {
      this._keep(live[this._focus]);
    } else {
      return; // let everything else bubble
    }
    e.preventDefault();
  }

  _move(delta, len) {
    this._focus = (this._focus + delta + len) % len;
    this.refresh();
    const tile = this.$(`[data-cand="${CSS.escape(this._live()[this._focus].id)}"]`);
    if (tile) tile.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }

  /** Audition: prefer a real src; silent takes don't bother (nothing to hear). */
  _play(c) {
    if (!c || c.silent || !c.src) return;
    if (!this._audio) this._audio = new Audio();
    this._audio.src = c.src;
    this._audio.currentTime = 0;
    this._audio.play().catch(() => {}); // autoplay/decoder hiccups stay silent
  }

  /** Slide a take to the reject tray; keep focus on a still-live neighbour. */
  _reject(c) {
    if (!c) return;
    this._rejected.add(c.id);
    const remaining = this._live().length;
    if (this._focus >= remaining) this._focus = Math.max(0, remaining - 1);
    this.refresh();
  }

  /** The keep: hand the chosen candidate up the tree and out of the sheet. */
  _keep(c) {
    if (!c) return;
    this.dispatchEvent(
      new CustomEvent("forge-pick", { detail: { candidate: c }, bubbles: true, composed: true }),
    );
  }

  styles() {
    return `
      :host { display: block; outline: none; }
      :host(:focus-visible) .sheet { box-shadow: inset 0 0 0 1px var(--forge-ember-edge); }

      .sheet { display: grid; gap: var(--forge-gap); padding: var(--forge-gap-lg);
        grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); align-content: start; }

      /* The hint strip — the loupe register: this is a keyboard surface. */
      .hint { grid-column: 1 / -1; display: flex; align-items: center; gap: 14px; flex-wrap: wrap;
        font-size: 11px; color: var(--forge-text-faint); padding-bottom: 2px; }
      .hint kbd { font-family: var(--forge-mono); font-size: 11px; color: var(--forge-text-dim);
        background: var(--forge-inset); border: 1px solid var(--forge-border); border-bottom-color: var(--forge-border-strong);
        border-radius: var(--forge-radius-sm); padding: 1px 6px; margin-right: 4px; }

      /* A tile: photo-contact-sheet cell — waveform proof + label, framed. */
      .tile { background: var(--forge-surface); border: 1px solid var(--forge-border);
        border-radius: var(--forge-radius); padding: var(--forge-card-pad);
        display: flex; flex-direction: column; gap: var(--forge-gap-sm); cursor: pointer;
        transition: border-color 140ms var(--forge-ease), opacity 200ms var(--forge-ease),
          transform 200ms var(--forge-ease), background 140ms var(--forge-ease); }
      .tile:hover { border-color: var(--forge-border-strong); }
      .tile[data-focused="true"] { border-color: var(--forge-ember-edge); background: var(--forge-surface-2);
        box-shadow: 0 0 0 1px var(--forge-ember-edge), 0 0 18px var(--forge-ember-dim); }

      /* The well the waveform sits in — matches the console/waveform inset token. */
      .well { background: var(--forge-inset); border-radius: var(--forge-radius-sm); overflow: hidden;
        min-height: 72px; display: flex; }
      forge-waveform { flex: 1; display: block; width: 100%; }

      .label { display: flex; align-items: baseline; gap: 8px; font-size: 13px; color: var(--forge-text); }
      .label .n { font-family: var(--forge-mono); font-size: 11px; color: var(--forge-text-faint); }
      .label .txt { font-weight: 560; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }

      /* Silence-collapse: the dead take arrives greyed + struck so the eye skips it. */
      .tile.silent { opacity: 0.42; }
      .tile.silent .label .txt { text-decoration: line-through; text-decoration-color: var(--forge-bad); color: var(--forge-text-dim); }
      .tag { margin-left: auto; font-size: 10px; text-transform: uppercase; letter-spacing: 0.06em;
        color: var(--forge-bad); border: 1px solid var(--forge-bad); border-radius: var(--forge-radius-pill); padding: 0 7px; }

      /* The hot signal: while forging, the focused tile's well runs ember. */
      :host-context([data-density]) .tile[data-focused="true"].hot .well { box-shadow: inset 0 0 0 1px var(--forge-ember-edge); }
      .tile.hot[data-focused="true"] .well { box-shadow: inset 0 0 0 1px var(--forge-ember-edge); }

      /* The reject tray — culled takes slide here, dimmed, one-click recoverable. */
      .tray { grid-column: 1 / -1; border-top: 1px dashed var(--forge-border); margin-top: var(--forge-gap-sm);
        padding-top: var(--forge-gap); display: flex; flex-direction: column; gap: var(--forge-gap-sm); }
      .tray .tray-label { font-size: 11px; text-transform: uppercase; letter-spacing: 0.06em; color: var(--forge-text-faint); }
      .tray .rows { display: flex; flex-wrap: wrap; gap: var(--forge-gap-sm); }
      .tray .chip { display: flex; align-items: center; gap: 8px; font-size: 12px; color: var(--forge-text-dim);
        background: var(--forge-surface); border: 1px solid var(--forge-border); border-radius: var(--forge-radius-pill);
        padding: 4px 6px 4px 12px; opacity: 0.7; transition: opacity 140ms var(--forge-ease); }
      .tray .chip:hover { opacity: 1; }
      .tray .chip .txt { text-decoration: line-through; text-decoration-color: var(--forge-bad); max-width: 18ch;
        white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
      .tray .undo { all: unset; cursor: pointer; font: inherit; font-size: 11px; color: var(--forge-text-faint);
        border: 1px solid var(--forge-border); border-radius: var(--forge-radius-pill); padding: 2px 9px; }
      .tray .undo:hover { color: var(--forge-text); border-color: var(--forge-border-strong); }

      .empty { grid-column: 1 / -1; color: var(--forge-text-faint); font-size: 13px; padding: var(--forge-gap); }
    `;
  }

  render() {
    if (!this._candidates.length) {
      return `<div class="sheet"><div class="empty">No candidates yet — forge a take to fill the sheet.</div></div>`;
    }
    const hot = store.get("forging");
    const live = this._live();
    const focusedId = live.length ? live[this._focus].id : null;

    const hint = `
      <div class="hint">
        <span><kbd>J</kbd><kbd>K</kbd>move</span>
        <span><kbd>Space</kbd>audition</span>
        <span><kbd>X</kbd>reject</span>
        <span><kbd>Enter</kbd>keep</span>
        <span>${live.length} live${this._rejected.size ? ` · ${this._rejected.size} culled` : ""}</span>
      </div>`;

    const tiles = live.map((c, i) => this._tile(c, c.id === focusedId, hot)).join("");
    const tray = this._tray();

    return `<div class="sheet">${hint}${tiles}${tray}</div>`;
  }

  _tile(c, focused, hot) {
    const cls = `tile${c.silent ? " silent" : ""}${hot ? " hot" : ""}`;
    const flat = c.silent ? ` flat` : "";
    // <forge-waveform> is a sibling: it reads pcm/src via attributes/props once
    // upgraded; flat= tells it to render the silence-collapse flat-line.
    const wave = `<forge-waveform${
      c.src ? ` src="${esc(c.src)}"` : ""
    } sample-rate="${esc(c.sampleRate)}"${flat} aria-hidden="true"></forge-waveform>`;
    return `
      <div class="${cls}" data-cand="${esc(c.id)}" data-focused="${focused}" role="button"
           aria-label="${esc(c.label)}${c.silent ? " (silent — collapsed take)" : ""}" aria-pressed="${focused}">
        <div class="well">${wave}</div>
        <div class="label">
          <span class="txt">${esc(c.label)}</span>
          ${c.silent ? `<span class="tag">silent</span>` : ""}
        </div>
      </div>`;
  }

  _tray() {
    if (!this._rejected.size) return "";
    const chips = this._candidates
      .filter((c) => this._rejected.has(c.id))
      .map(
        (c) => `
        <span class="chip" data-tray="${esc(c.id)}">
          <span class="txt">${esc(c.label)}</span>
          <button class="undo" data-undo="${esc(c.id)}" type="button" aria-label="restore ${esc(c.label)}">undo</button>
        </span>`,
      )
      .join("");
    return `<div class="tray"><div class="tray-label">Rejected · ${this._rejected.size}</div><div class="rows">${chips}</div></div>`;
  }

  bind() {
    // Click is the mouse path through the same three verbs: select, then act.
    for (const tile of this.$$(".tile")) {
      const id = tile.dataset.cand;
      tile.onclick = () => {
        const live = this._live();
        const idx = live.findIndex((c) => c.id === id);
        if (idx < 0) return;
        if (idx === this._focus) {
          this._play(live[idx]); // a click on the already-focused tile auditions it
        } else {
          this._focus = idx;
          this.refresh();
        }
      };
    }
    for (const btn of this.$$("[data-undo]")) {
      btn.onclick = (e) => {
        e.stopPropagation();
        this._rejected.delete(btn.dataset.undo);
        this.refresh();
      };
    }
    // Push pcm frames into the sibling waveforms as a property (can't go in HTML).
    const live = this._live();
    for (const el of this.$$("forge-waveform")) {
      const id = el.parentElement?.parentElement?.dataset.cand;
      const c = live.find((x) => x.id === id);
      if (c && c.pcm) el.pcm = c.pcm;
    }
  }
}

customElements.define("forge-contact-sheet", ForgeContactSheet);

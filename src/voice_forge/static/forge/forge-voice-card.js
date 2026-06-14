/*
 * <forge-voice-card voice-id="…"> — the atomic voice card.
 *
 * U4: the one tile the whole studio is built from. It reads its voice from
 * store.voices and renders ONE of four faces by state:
 *   ghost   — no/placeholder data: a dashed "forge a voice" CTA (cold anvil).
 *   forging — store.forging is hot for THIS card: skeleton + ember heat-shimmer.
 *   forged  — name + a <forge-backend-chip> + language, marked unbound.
 *   bound   — forged + a persona chip + a small "serve" affordance.
 *
 * No waveform on the card: a voice at rest has no take to play (a VoiceInfo
 * carries no audio). Takes are heard via the serve console's inline run-and-hear
 * in the inspector — that's where <forge-waveform> is fed a real take.
 *
 * Clicking the card focuses it (store.focused = id); aria-selected reflects
 * focus so the rail, inspector, and serve console all follow the same subject.
 *
 * Identity: dark studio at rest, ember as the active-synthesis "hot" signal.
 * The card runs hot only while it is forging — no permanent smithy theming.
 */

import { ForgeElement, esc } from "./base.js";
import { store } from "./store.js";

class ForgeVoiceCard extends ForgeElement {
  // focused drives selection; forging drives the hot face; voices feeds the data;
  // justForged drives the one-shot forge-complete bloom on the just-landed card.
  static observe = ["voices", "focused", "forging", "justForged"];

  /** The voice record this card reflects (or null → ghost face). */
  _voice() {
    const id = this.getAttribute("voice-id");
    if (!id) return null;
    const voices = store.get("voices") || [];
    return voices.find((v) => (v.voice_id || v.id) === id) || null;
  }

  /** A voice is a placeholder until it has a backend to be served from. */
  _isGhost(v) {
    return !v || !(v.voice_id || v.id) || !v.backend;
  }

  /** Which of the four faces to paint for the current store snapshot. */
  _face(v) {
    if (this._isGhost(v)) return "ghost";
    const id = v.voice_id || v.id;
    // Hot only when synthesis is live AND this is the focused subject.
    if (store.get("forging") && store.get("focused") === id) return "forging";
    return v.persona ? "bound" : "forged";
  }

  styles() {
    return `
      :host { display: block; }

      .card {
        position: relative;
        background: var(--forge-surface);
        border: 1px solid var(--forge-border);
        border-radius: var(--forge-radius);
        padding: var(--forge-card-pad);
        cursor: pointer;
        transition: border-color 120ms var(--forge-ease), background 120ms var(--forge-ease);
        outline: none;
      }
      .card:hover { border-color: var(--forge-border-strong); }
      .card:focus-visible { box-shadow: 0 0 0 2px var(--forge-ember-edge); }
      :host([aria-selected="true"]) .card { border-color: var(--forge-ember-edge); background: var(--forge-surface-2); }

      .top { display: flex; align-items: center; gap: var(--forge-gap-sm); }
      .vid { font-weight: 600; letter-spacing: -0.01em; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
      .spacer { flex: 1; }

      .meta { color: var(--forge-text-dim); font-size: 12px; margin-top: 6px; display: flex; align-items: center; gap: var(--forge-gap-sm); flex-wrap: wrap; }
      .persona { color: var(--forge-text); }

      /* bound: a small "serve" affordance — present only once a persona is bound. */
      .serve {
        all: unset; cursor: pointer; font: inherit; font-size: 12px; line-height: 1;
        color: var(--forge-ember); border: 1px solid var(--forge-ember-edge);
        border-radius: var(--forge-radius-pill); padding: 5px 11px;
        transition: background 120ms var(--forge-ease);
      }
      .serve:hover { background: var(--forge-ember-dim); }
      .serve:focus-visible { box-shadow: 0 0 0 2px var(--forge-ember-edge); }
      .bound-dot { width: 6px; height: 6px; border-radius: 50%; background: var(--forge-ok); flex: none; }

      /* ghost: a cold, dashed call to forge — same footprint as a real card. */
      .ghost {
        border-style: dashed; background: transparent; color: var(--forge-text-faint);
        display: flex; flex-direction: column; align-items: center; justify-content: center;
        gap: 8px; text-align: center; min-height: var(--forge-row-h);
      }
      .ghost:hover { color: var(--forge-text-dim); border-color: var(--forge-border-strong); }
      .ghost svg { color: var(--forge-text-faint); }
      .ghost .cta { font-size: 13px; font-weight: 560; }

      /* forging: the card runs HOT — ember border + heat-shimmer over a skeleton. */
      .card.hot { border-color: var(--forge-ember); }
      .card.hot::after {
        content: ""; position: absolute; inset: 0; border-radius: inherit; pointer-events: none;
        background: linear-gradient(110deg, transparent 30%, var(--forge-ember-edge) 50%, transparent 70%);
        background-size: 220% 100%;
        animation: heat var(--forge-heat-ms) var(--forge-ease) infinite;
      }
      @keyframes heat { from { background-position: 220% 0; } to { background-position: -120% 0; } }

      /* forged: the one-shot quench — heat settling into the finished piece.
         A single ~600ms ember bloom on the just-landed card, then back to rest.
         It plays OVER the aria-selected state and releases to it (no forwards
         fill, so the selected-ember border at :host([aria-selected]) wins after). */
      .card.just-forged {
        animation: forge-complete 600ms var(--forge-ease) 1;
      }
      @keyframes forge-complete {
        0%   { border-color: var(--forge-ember-bright);
               box-shadow: 0 0 0 1px var(--forge-ember-bright), 0 0 22px var(--forge-ember-edge); }
        60%  { border-color: var(--forge-ember);
               box-shadow: 0 0 0 1px var(--forge-ember-edge), 0 0 12px var(--forge-ember-edge); }
        100% { border-color: var(--forge-border);
               box-shadow: 0 0 0 1px transparent, 0 0 0 transparent; }
      }

      .skel { background: var(--forge-inset); border-radius: var(--forge-radius-sm); height: 12px; overflow: hidden; }
      .skel.w-half { width: 50%; }
      .skel.tall { height: 40px; margin-top: 12px; }
      .heat-label { color: var(--forge-ember-bright); font-size: 11px; font-weight: 560; letter-spacing: 0.04em; text-transform: uppercase; }

      @media (prefers-reduced-motion: reduce) {
        .card.hot::after { animation: none; opacity: 0.4; }
        /* spark → a single static border tint that fades, no keyframe motion. */
        .card.just-forged { animation: none; border-color: var(--forge-ember-edge); transition: border-color 400ms var(--forge-ease); }
      }
    `;
  }

  render() {
    const v = this._voice();
    const face = this._face(v);
    if (face === "ghost") return this._ghost();

    const id = esc(v.voice_id || v.id || "");
    if (face === "forging") return this._forging(id);

    const backend = esc(v.backend || "");
    const persona = v.persona ? esc(v.persona) : "";
    const lang = v.language ? esc(v.language) : "";

    // forged + bound share the body; bound adds the persona chip + serve affordance.
    const chip = backend ? `<forge-backend-chip backend="${backend}"></forge-backend-chip>` : "";
    const head = `
      <div class="top">
        <span class="vid">${id}</span>
        <span class="spacer"></span>
        ${face === "bound" ? `<button class="serve" type="button" aria-label="serve ${id}">serve</button>` : ""}
      </div>`;

    const meta =
      face === "bound"
        ? `<div class="meta"><span class="bound-dot" aria-hidden="true"></span><span class="persona">${persona}</span>${
            lang ? ` · ${lang}` : ""
          } ${chip}</div>`
        : `<div class="meta">${chip}${lang ? `<span>${lang}</span>` : ""}<span>unbound</span></div>`;

    // The one-shot quench: when this voice is the just-forged subject, paint the
    // bloom class. It's part of the render OUTPUT, so it survives base.js rebuilding
    // innerHTML across _load()'s repaints — the flag stays set in the store until
    // bind() clears it after the animation. esc() is moot here (id-equality on a
    // store flag, no interpolation), but the class is gated on a strict match so a
    // stale flag never blooms the wrong card.
    const justForged = store.get("justForged") === (v.voice_id || v.id);
    return `<div class="card${justForged ? " just-forged" : ""}">${head}${meta}</div>`;
  }

  _ghost() {
    // No id to focus on a ghost — it invites a forge, it isn't a subject yet.
    return `<div class="card ghost">
      <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 8h12l-1 4H7"/><path d="M12 12v4"/><path d="M8 20h8"/><path d="M19 8h2v3a3 3 0 0 1-3 3"/></svg>
      <span class="cta">Forge a voice</span>
    </div>`;
  }

  _forging(id) {
    return `<div class="card hot">
      <div class="top"><span class="vid">${id}</span><span class="spacer"></span><span class="heat-label">forging</span></div>
      <div class="skel tall"></div>
      <div class="meta"><span class="skel w-half" style="width:40%"></span></div>
    </div>`;
  }

  bind() {
    const card = this.$(".card");
    if (!card) return;

    // A ghost has no subject to focus; everything else is selectable.
    if (card.classList.contains("ghost")) {
      this.removeAttribute("tabindex");
      this.removeAttribute("role");
      this.removeAttribute("aria-selected");
      return;
    }

    const id = this.getAttribute("voice-id");
    this.setAttribute("role", "option");
    this.setAttribute("tabindex", "0");
    this.setAttribute("aria-selected", String(store.get("focused") === id));

    const focus = () => store.set({ focused: id });
    card.onclick = focus;
    this.onkeydown = (e) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        focus();
      }
    };

    // "serve" is its own action — focus the subject but don't double-handle the card.
    const serve = this.$(".serve");
    if (serve) {
      serve.onclick = (e) => {
        e.stopPropagation();
        store.set({ focused: id });
        this.dispatchEvent(new CustomEvent("forge-serve", { detail: { id }, bubbles: true, composed: true }));
      };
    }

    // One-shot quench: the spark rode in via the rendered class (it survives
    // _load()'s repaint because the store flag is still set). Clear it once, after
    // the bloom, so the next paint lands the card on its clean resting face. Guard
    // on this card's id so only the just-forged card schedules the clear — and the
    // clear re-checks the flag, so a stale flag from a fast double-forge self-heals
    // on the next success. 650ms > the 600ms anim (and the 400ms reduced-motion
    // transition) so the clearing repaint never truncates the bloom.
    if (store.get("justForged") === id) {
      setTimeout(() => {
        if (store.get("justForged") === id) store.set({ justForged: null });
      }, 650);
    }
  }
}

customElements.define("forge-voice-card", ForgeVoiceCard);

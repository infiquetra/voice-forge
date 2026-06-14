/*
 * <forge-serve-console> — the serve handoff (U10).
 *
 * The end of the canonical path: "call it from the API." Follows store.focused
 * and shows the EXACT call for that voice — curl / Python / JS tabs over the
 * real POST /v1/audio/speech body, plus the WS /v1/tts/stream snippet — with a
 * one-click Copy and a Run that actually fires the request and plays the result
 * through a nested <forge-waveform>. For an API-builder, the call is the
 * deliverable, so it stays current with the focused voice and lives on a dark
 * console surface (reclaiming what the old #log was the right material for).
 */

import { ForgeElement, esc } from "./base.js";
import { store } from "./store.js";

const SAMPLE_INPUT = "Hello — this is my voice.";
const TABS = ["curl", "python", "js"];

class ForgeServeConsole extends ForgeElement {
  static observe = ["focused", "voices"];

  constructor() {
    super();
    this._tab = "curl";
    this._copied = false;
  }

  _focusedVoice() {
    const id = store.get("focused");
    if (!id) return null;
    return (store.get("voices") || []).find((v) => (v.voice_id || v.id) === id) || { id };
  }

  /** The literal call for the focused voice, per tab. Strings are escaped at render. */
  _snippet(voiceId, tab) {
    const origin = location.origin;
    const body = JSON.stringify(
      { model: "voice-forge", input: SAMPLE_INPUT, voice: voiceId, response_format: "wav" },
      null,
      2,
    );
    if (tab === "python") {
      return [
        "import requests",
        `r = requests.post("${origin}/v1/audio/speech", json={`,
        '    "model": "voice-forge",',
        `    "input": ${JSON.stringify(SAMPLE_INPUT)},`,
        `    "voice": ${JSON.stringify(voiceId)},`,
        '    "response_format": "wav",',
        "})",
        'open("speech.wav", "wb").write(r.content)',
      ].join("\n");
    }
    if (tab === "js") {
      return [
        `const r = await fetch("${origin}/v1/audio/speech", {`,
        '  method: "POST",',
        '  headers: { "Content-Type": "application/json" },',
        `  body: JSON.stringify(${body.replace(/\n/g, "\n  ")}),`,
        "});",
        "const wav = await r.blob();",
      ].join("\n");
    }
    // curl
    return [
      `curl ${origin}/v1/audio/speech \\`,
      `  -H "Content-Type: application/json" \\`,
      `  -d '${JSON.stringify({ model: "voice-forge", input: SAMPLE_INPUT, voice: voiceId, response_format: "wav" })}' \\`,
      "  --output speech.wav",
    ].join("\n");
  }

  styles() {
    return `
      :host { display: block; }
      .panel { display: flex; flex-direction: column; min-height: 0; background: var(--forge-inset); border: 1px solid var(--forge-border); border-radius: var(--forge-radius); overflow: hidden; }
      .head { display: flex; align-items: center; gap: var(--forge-gap-sm); padding: 8px 10px; border-bottom: 1px solid var(--forge-border); }
      .tabs { display: flex; gap: 2px; }
      .tabs button { all: unset; cursor: pointer; font: inherit; font-size: 12px; font-family: var(--forge-mono); color: var(--forge-text-dim); padding: 3px 10px; border-radius: var(--forge-radius-sm); }
      .tabs button[aria-selected="true"] { background: var(--forge-surface-2); color: var(--forge-text); }
      .spacer { flex: 1; }
      .act { all: unset; cursor: pointer; font: inherit; font-size: 12px; color: var(--forge-text-dim); padding: 3px 10px; border: 1px solid var(--forge-border); border-radius: var(--forge-radius-sm); }
      .act:hover { color: var(--forge-text); border-color: var(--forge-border-strong); }
      .act.run { color: var(--forge-ember); border-color: var(--forge-ember-edge); }
      .act.run[data-failed="true"] { color: var(--forge-bad); border-color: var(--forge-bad); }
      pre { margin: 0; padding: 12px 14px; overflow-x: auto; font-family: var(--forge-mono); font-size: 12px; line-height: 1.55; color: var(--forge-text); }
      .foot { display: flex; align-items: center; gap: var(--forge-gap-sm); padding: 8px 10px; border-top: 1px solid var(--forge-border); }
      .empty { padding: 18px 14px; color: var(--forge-text-faint); font-size: 13px; }
      .label { font-size: 11px; text-transform: uppercase; letter-spacing: 0.06em; color: var(--forge-text-faint); }
    `;
  }

  render() {
    const v = this._focusedVoice();
    if (!v) {
      return `<div class="panel"><div class="empty">Select a voice — its API call appears here, ready to copy and run.</div></div>`;
    }
    const id = v.voice_id || v.id || "";
    const snippet = this._snippet(id, this._tab);
    const tabs = TABS.map(
      (t) => `<button data-tab="${t}" aria-selected="${t === this._tab}">${esc(t)}</button>`,
    ).join("");
    return `
      <div class="panel">
        <div class="head">
          <div class="tabs">${tabs}</div>
          <div class="spacer"></div>
          <button class="act copy">${this._copied ? "copied" : "copy"}</button>
          <button class="act run">▶ run</button>
        </div>
        <pre>${esc(snippet)}</pre>
        <div class="foot">
          <span class="label">serve · ${esc(id)}</span>
          <div class="spacer"></div>
          <forge-waveform></forge-waveform>
        </div>
      </div>`;
  }

  bind() {
    for (const b of this.$$(".tabs button")) {
      b.onclick = () => {
        this._tab = b.dataset.tab;
        this._copied = false;
        this.refresh();
      };
    }
    const copy = this.$(".copy");
    if (copy) {
      copy.onclick = async () => {
        const v = this._focusedVoice();
        if (!v) return;
        const text = this._snippet(v.voice_id || v.id || "", this._tab);
        try {
          await navigator.clipboard.writeText(text);
          this._copied = true;
          this.refresh();
        } catch {
          /* clipboard blocked — leave the snippet selectable in the <pre> */
        }
      };
    }
    const run = this.$(".run");
    if (run) run.onclick = () => this._run();
  }

  async _run() {
    const v = this._focusedVoice();
    if (!v) return;
    const id = v.voice_id || v.id || "";
    const wave = this.$("forge-waveform");
    const runBtn = this.$(".run");
    // Surface a failure on the Run button directly (not via re-render — the
    // console repaints on focus/voices and would wipe a flagged state). This is
    // the canonical "call it from the API" path; a silent failure here reads as a
    // dead button, so a failed Run must say so.
    const fail = () => {
      if (!runBtn) return;
      runBtn.dataset.failed = "true";
      runBtn.textContent = "✕ failed";
      setTimeout(() => {
        if (runBtn.isConnected) {
          delete runBtn.dataset.failed;
          runBtn.textContent = "▶ run";
        }
      }, 2500);
    };
    store.set({ forging: true });
    try {
      const r = await fetch("/v1/audio/speech", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          model: "voice-forge",
          input: SAMPLE_INPUT,
          voice: id,
          response_format: "wav",
        }),
      });
      if (!r.ok) {
        fail();
        return;
      }
      const blob = await r.blob();
      if (wave) {
        wave.setAttribute("src", URL.createObjectURL(blob));
        wave.play?.();
      }
    } catch {
      fail(); // network/synth error — show it, don't leave a dead-feeling button
    } finally {
      store.set({ forging: false });
    }
  }
}

customElements.define("forge-serve-console", ForgeServeConsole);

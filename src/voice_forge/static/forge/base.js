/*
 * The Forge — vanilla custom-element base (no framework, no build).
 *
 * Replaces Lit: a ~50-line base that gives each <forge-*> component a shadow
 * root, scoped styles, a declarative render() string, and auto re-render on the
 * store slices it observes. Components override styles()/render() and the
 * optional bind() hook for event wiring (re-run after each paint).
 *
 * Why vanilla over Lit: the architecture's hard rule is "ships ready, no build,
 * runs offline." Every CDN "single-file Lit" is a re-export wrapper that chains
 * to network URLs at runtime; a self-contained file needs a bundler (the build
 * step we forbid). Browser-native custom elements need nothing vendored.
 */

import { store } from "./store.js";

export class ForgeElement extends HTMLElement {
  /** Store keys that trigger a re-render when they change. */
  static observe = [];

  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._unsub = null;
    this._root = null;
  }

  connectedCallback() {
    this.shadowRoot.innerHTML = `<style>${this.styles()}</style><div id="root"></div>`;
    this._root = this.shadowRoot.getElementById("root");
    this._paint();
    const keys = this.constructor.observe;
    if (keys.length) {
      this._unsub = store.subscribe((changed) => {
        if (changed.some((k) => keys.includes(k))) this._paint();
      });
    }
  }

  disconnectedCallback() {
    if (this._unsub) this._unsub();
  }

  _paint() {
    this._root.innerHTML = this.render();
    if (this.bind) this.bind();
  }

  /** Re-render on demand (for local state not in the store). */
  refresh() {
    if (this._root) this._paint();
  }

  $(sel) {
    return this._root.querySelector(sel);
  }

  $$(sel) {
    return [...this._root.querySelectorAll(sel)];
  }

  /** Scoped CSS string for this component's shadow root. */
  styles() {
    return "";
  }

  /** HTML string for this component's content. */
  render() {
    return "";
  }
}

/** Escape untrusted text for safe interpolation into render() strings. */
export function esc(s) {
  return String(s ?? "").replace(
    /[&<>"']/g,
    (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c],
  );
}

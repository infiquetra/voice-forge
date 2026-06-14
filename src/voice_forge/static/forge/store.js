/*
 * The Forge — tiny reactive store (~no deps, no build).
 *
 * One shared state object the shell and every <forge-*> component subscribe to.
 * Replaces the per-panel ad-hoc state of the old /lab page. Deliberately ~40
 * lines: get / set (shallow-merge) / subscribe. Components re-render on the
 * slices they care about. This is the "tiny shared store" of KTD2 — vanilla,
 * not a framework.
 */

const _state = {
  // installed backends (GET /v1/backends → normalized array) — per-backend
  // installed/tunables; clone-availability is derived from these.
  backends: [],
  // design-readiness snapshot (GET /v1/capabilities) — drives the cold-start door
  capabilities: null,
  // registry voices (GET /v1/audio/voices)
  voices: [],
  // the voice currently in focus (id) — the inspector + serve console follow it
  focused: null,
  // Calm (default) vs Bench — persisted in localStorage
  density: localStorage.getItem("forge-density") || "calm",
  // is anything synthesizing right now? (drives the ember "hot" signal)
  forging: false,
  // transient audition set (POST /v1/forge/design → []); non-empty swaps the
  // subject to <forge-contact-sheet>. Cleared on pick/cancel. NOT a registry
  // slice. Always set a FRESH array (store.set's identity check, line 38, will
  // not notify on a re-set of the same reference) so the subject swap fires.
  candidates: [],
};

const _subs = new Set();

export const store = {
  get(key) {
    return key === undefined ? _state : _state[key];
  },

  /** Shallow-merge a patch and notify subscribers with the changed keys. */
  set(patch) {
    const changed = [];
    for (const k of Object.keys(patch)) {
      if (_state[k] !== patch[k]) {
        _state[k] = patch[k];
        changed.push(k);
      }
    }
    if (changed.length) {
      for (const fn of _subs) fn(changed, _state);
    }
  },

  /** Subscribe to changes. Returns an unsubscribe fn. */
  subscribe(fn) {
    _subs.add(fn);
    return () => _subs.delete(fn);
  },
};

/** Persisted density toggle — the one control behind Calm/Bench (KTD8). */
export function setDensity(density) {
  localStorage.setItem("forge-density", density);
  store.set({ density });
}

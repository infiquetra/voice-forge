"""Voice-mixing spec parser.

Kokoro-style syntax: ``name(weight)+name(weight)``. Bare ``name`` is
implicit ``(1)``. Whitespace around ``+`` is permitted but not required.
Weights must be non-negative; a single weight may be a float (e.g. ``1.5``).

The parser is library-agnostic — only the backend (Kokoro) knows how to
interpret the parsed tuples (typically by loading per-voice embedding
tensors, weighted-averaging, and passing the result to the inference call).
"""

from __future__ import annotations

import re

_TOKEN = re.compile(r"^([a-zA-Z0-9_-]+)(?:\((\d+(?:\.\d+)?)\))?$")


def parse_mix(spec: str) -> list[tuple[str, float]]:
    """Parse a voice-mix spec into ``[(name, weight), ...]``.

    Examples:
        >>> parse_mix("af_bella")
        [('af_bella', 1.0)]
        >>> parse_mix("af_bella+af_sky")
        [('af_bella', 1.0), ('af_sky', 1.0)]
        >>> parse_mix("af_bella(2)+af_sky(0.5)")
        [('af_bella', 2.0), ('af_sky', 0.5)]

    Raises:
        ValueError: spec is empty or any token is malformed.
    """
    spec = (spec or "").strip()
    if not spec:
        raise ValueError("voice-mix spec is empty")
    parts = [p.strip() for p in spec.split("+")]
    out: list[tuple[str, float]] = []
    for p in parts:
        if not p:
            raise ValueError(f"voice-mix spec has empty token: {spec!r}")
        m = _TOKEN.match(p)
        if not m:
            raise ValueError(f"unparseable voice-mix token: {p!r} (in {spec!r})")
        name = m.group(1)
        weight = float(m.group(2)) if m.group(2) is not None else 1.0
        if weight < 0:
            raise ValueError(f"voice-mix weight must be non-negative: {p!r}")
        out.append((name, weight))
    return out

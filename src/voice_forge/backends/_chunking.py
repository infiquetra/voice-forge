"""Shared sentence-boundary text chunker.

Used by every backend's ``synthesize_stream`` to split long inputs into
sentence-grouped chunks so the first audio chunk arrives faster than the
full-utterance synth time. Originally inlined in ``neutts.py``; promoted
to a shared module when F5 / Dia / XTTS started using the same pattern.

The chunker preserves sentence boundaries — we never split mid-sentence
because that causes cloning-quality drift (the model loses prosodic
context). A single sentence longer than ``max_chars`` goes into its own
chunk regardless.

Empty / whitespace-only input returns ``[]`` (not ``[""]``) so callers
don't waste an inference pass on nothing.
"""

from __future__ import annotations

import re

_SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?])\s+")


def chunk_text(text: str, max_chars: int) -> list[str]:
    """Split text at sentence boundaries, respecting ``max_chars`` per chunk.

    Args:
        text: input. Whitespace-trimmed; empty/whitespace-only returns ``[]``.
        max_chars: target maximum chars per chunk. A single sentence longer
            than this still gets its own chunk (we don't split mid-sentence).

    Returns:
        List of strings, each a sentence-grouped chunk preserving the
        original sentence punctuation. Joining them with `" "` reassembles
        a close approximation of the input (modulo collapsed whitespace).
    """
    stripped = text.strip()
    if not stripped:
        return []
    sentences = _SENTENCE_BOUNDARY.split(stripped)
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0
    for sentence in sentences:
        if current and current_len + len(sentence) + 1 > max_chars:
            chunks.append(" ".join(current))
            current = [sentence]
            current_len = len(sentence)
        else:
            current.append(sentence)
            current_len += len(sentence) + 1
    if current:
        chunks.append(" ".join(current))
    return chunks

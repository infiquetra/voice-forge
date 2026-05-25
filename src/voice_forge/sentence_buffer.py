"""Incremental sentence buffer for WS layer-2 streaming.

Text arrives one chunk at a time (e.g. tokens from an upstream LLM stream).
We want to emit each *complete* sentence as soon as it forms so synthesis
can start before the rest of the utterance has even been generated.

The contract:

- ``feed(chunk)`` appends text and returns any complete sentences that
  just formed. "Complete" means the buffer holds ``[.!?]+`` followed by
  whitespace — the whitespace is the disambiguator that tells us "the
  next sentence has started". Without the trailing whitespace, the
  punctuation might still be an abbreviation ("Dr.") or sentence-internal
  ("etc.").
- ``flush()`` returns whatever is left in the buffer (no punctuation
  required). Callers invoke this when the upstream stream is done, so
  trailing partial text gets one last synth pass.

This is the streaming-input counterpart to ``backends._chunking.chunk_text``,
which operates on a known-up-front string and is allowed to split
non-trailing punctuation freely.
"""

from __future__ import annotations

import re

# "[.!?]+\s+" matches one-or-more terminal punctuation glyphs followed by
# at least one whitespace char. The whitespace requirement is what makes
# this stream-safe — we never emit a sentence whose trailing punctuation
# might still be sentence-internal ("e.g." with the space not yet arrived).
_SENTENCE_BOUNDARY = re.compile(r"[.!?]+\s+")


class SentenceBuffer:
    """Append text incrementally; drain complete sentences as they form."""

    def __init__(self) -> None:
        self._buf: str = ""

    def feed(self, chunk: str) -> list[str]:
        """Append ``chunk`` to the buffer; return any complete sentences.

        Each returned sentence has its trailing whitespace + punctuation
        preserved on the punctuation, but no leading/trailing whitespace
        — i.e. the same shape a synth backend would expect to receive.
        """
        if not chunk:
            return []
        self._buf += chunk
        sentences: list[str] = []
        while True:
            m = _SENTENCE_BOUNDARY.search(self._buf)
            if not m:
                break
            # Take everything up through the end of the boundary match
            # (punctuation + trailing whitespace). strip() removes the
            # trailing whitespace; the punctuation stays.
            sentences.append(self._buf[: m.end()].strip())
            self._buf = self._buf[m.end() :]
        return sentences

    def flush(self) -> str | None:
        """Return whatever non-empty text remains; resets the buffer.

        Used when the upstream stream signals end-of-input. Returns
        ``None`` if there is no trailing text (entirely empty or only
        whitespace).
        """
        remaining = self._buf.strip()
        self._buf = ""
        return remaining or None

    @property
    def pending(self) -> str:
        """Visible-for-tests: what's currently buffered."""
        return self._buf

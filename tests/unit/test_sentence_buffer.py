"""Unit tests for SentenceBuffer — streaming text → complete sentences."""

from __future__ import annotations

from voice_forge.sentence_buffer import SentenceBuffer


def test_single_sentence_then_whitespace_emits():
    buf = SentenceBuffer()
    assert buf.feed("Hello world.") == []  # no trailing whitespace yet
    assert buf.feed(" ") == ["Hello world."]
    assert buf.pending == ""


def test_period_without_following_whitespace_holds():
    """A bare period at end-of-buffer is held — it might still be an abbreviation."""
    buf = SentenceBuffer()
    assert buf.feed("Talk to Dr") == []
    assert buf.feed(".") == []
    # Still no whitespace — could be "Dr. Stone" coming next.
    assert buf.pending == "Talk to Dr."


def test_punctuation_then_whitespace_arriving_separately():
    """Sentence terminator can be split across multiple feed() calls."""
    buf = SentenceBuffer()
    assert buf.feed("Hello") == []
    assert buf.feed(".") == []  # punctuation arrived, but no space yet
    assert buf.feed(" ") == ["Hello."]  # space completes the boundary


def test_multiple_sentences_in_one_chunk():
    buf = SentenceBuffer()
    out = buf.feed("First. Second! Third? Fourth.")
    # The final "Fourth." has no trailing whitespace yet, so it stays buffered.
    assert out == ["First.", "Second!", "Third?"]
    assert buf.pending == "Fourth."


def test_emit_then_continue_buffering():
    buf = SentenceBuffer()
    out1 = buf.feed("Done. ")
    assert out1 == ["Done."]
    # Subsequent feed continues from empty buffer.
    out2 = buf.feed("More text")
    assert out2 == []
    assert buf.pending == "More text"


def test_flush_returns_remaining_text():
    buf = SentenceBuffer()
    buf.feed("Partial sentence with no period")
    assert buf.flush() == "Partial sentence with no period"
    assert buf.pending == ""  # flush resets


def test_flush_strips_whitespace():
    buf = SentenceBuffer()
    buf.feed("   trailing  ")
    assert buf.flush() == "trailing"


def test_flush_returns_none_on_empty_buffer():
    buf = SentenceBuffer()
    assert buf.flush() is None


def test_flush_returns_none_on_whitespace_only_buffer():
    buf = SentenceBuffer()
    buf.feed("   \n\t  ")
    assert buf.flush() is None


def test_feed_empty_chunk_is_noop():
    buf = SentenceBuffer()
    buf.feed("Half ")
    assert buf.feed("") == []
    assert buf.pending == "Half "


def test_token_by_token_feed_emits_at_boundary():
    """Mimics an LLM streaming one token at a time."""
    buf = SentenceBuffer()
    tokens = ["Once", " upon", " a", " time", ",", " Loki", " stole", " the", " apples", "."]
    emitted: list[str] = []
    for t in tokens:
        emitted.extend(buf.feed(t))
    # No whitespace after final period yet → still buffered.
    assert emitted == []
    # Add the trailing space (e.g. next sentence starting) → boundary fires.
    emitted.extend(buf.feed(" "))
    assert emitted == ["Once upon a time, Loki stole the apples."]


def test_realistic_multi_sentence_streaming():
    buf = SentenceBuffer()
    emitted: list[str] = []
    # Simulated arrival in bursts
    for chunk in [
        "I am Saga,",
        " keeper of",
        " stories.",
        " I record",
        " what",
        " happens",
        " here.",
        " Long ago, Loki",
        " visited my archive.",
    ]:
        emitted.extend(buf.feed(chunk))
    # Final chunk has no trailing whitespace, so last sentence is still buffered.
    assert emitted == [
        "I am Saga, keeper of stories.",
        "I record what happens here.",
    ]
    assert buf.flush() == "Long ago, Loki visited my archive."


def test_consecutive_punctuation_is_one_boundary():
    """'!!!' or '...' counts as one sentence end."""
    buf = SentenceBuffer()
    out = buf.feed("Wow!!! Really?")
    assert out == ["Wow!!!"]
    assert buf.pending == "Really?"


def test_no_sentence_boundary_keeps_text_buffered():
    """Long text without any . ! ? stays buffered until flush."""
    buf = SentenceBuffer()
    text = "no terminator just words and commas, more words"
    assert buf.feed(text) == []
    assert buf.flush() == text

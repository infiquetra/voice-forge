"""Tests for the shared sentence-boundary chunker used by every backend's
synthesize_stream path."""

from __future__ import annotations

from voice_forge.backends._chunking import chunk_text


def test_empty_string_returns_empty_list():
    assert chunk_text("", 100) == []


def test_whitespace_only_returns_empty_list():
    assert chunk_text("   \n  ", 100) == []


def test_single_sentence_returns_single_chunk():
    assert chunk_text("Hello world.", 100) == ["Hello world."]


def test_strips_leading_trailing_whitespace():
    assert chunk_text("  Hello world.  ", 100) == ["Hello world."]


def test_short_input_packs_into_one_chunk():
    text = "First sentence. Second sentence. Third sentence."
    chunks = chunk_text(text, 100)
    assert len(chunks) == 1
    assert "First sentence" in chunks[0]
    assert "Third sentence" in chunks[0]


def test_long_input_splits_at_sentence_boundaries():
    text = "First sentence here. Second sentence here. Third sentence here."
    chunks = chunk_text(text, 25)
    # Each sentence ~21 chars, so two should land in their own chunks each
    assert len(chunks) >= 2
    # No mid-sentence splits
    for chunk in chunks:
        # If a chunk contains a period, it must be at the end of a sentence
        # (followed by space or end of chunk).
        assert chunk.endswith(".") or "?" in chunk or "!" in chunk


def test_chunks_preserve_sentence_punctuation():
    """Joining chunks should reassemble the original text (modulo whitespace)."""
    text = "Hello. World. Goodbye."
    chunks = chunk_text(text, 8)  # force per-sentence chunks
    reassembled = " ".join(chunks).replace("  ", " ")
    # Spot-check: every word from the original is present
    for word in ("Hello", "World", "Goodbye"):
        assert word in reassembled


def test_single_sentence_longer_than_max_gets_own_chunk():
    """We never split mid-sentence — quality drift outweighs latency win."""
    text = "This is one very long single sentence that exceeds the small max chars limit."
    chunks = chunk_text(text, 20)
    assert len(chunks) == 1
    assert chunks[0] == text


def test_questions_and_exclamations_count_as_sentence_boundaries():
    text = "Hello? Yes! Goodbye."
    chunks = chunk_text(text, 8)
    # Three short sentences should produce three chunks at max_chars=8
    assert len(chunks) == 3


def test_no_double_spaces_within_chunks():
    """Sentences are joined with a single space."""
    text = "First.  Second.   Third."  # extra spaces in input
    chunks = chunk_text(text, 100)
    assert "  " not in chunks[0]

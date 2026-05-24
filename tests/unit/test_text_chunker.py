"""Tests for the text chunker used inside the NeuTTS backend."""

import pytest


def test_chunker_handles_empty_text():
    pytest.importorskip("neutts", reason="NeuTTS not installed")
    from voice_forge.backends.neutts import _chunk_text

    assert _chunk_text("", 100) == []


def test_chunker_keeps_short_input_as_one_chunk():
    pytest.importorskip("neutts", reason="NeuTTS not installed")
    from voice_forge.backends.neutts import _chunk_text

    chunks = _chunk_text("Hello world.", 100)
    assert chunks == ["Hello world."]


def test_chunker_splits_at_sentence_boundaries():
    pytest.importorskip("neutts", reason="NeuTTS not installed")
    from voice_forge.backends.neutts import _chunk_text

    text = "First sentence. Second sentence. Third sentence."
    chunks = _chunk_text(text, 25)
    # Each sentence ~15-17 chars, so two should fit per chunk
    assert len(chunks) >= 2
    # Reassembled text equals original (ignoring whitespace)
    reassembled = " ".join(chunks)
    assert reassembled.replace(" ", "") == text.replace(" ", "")


def test_chunker_long_single_sentence_gets_own_chunk():
    """A sentence longer than max_chars goes into its own chunk (we don't split mid-sentence)."""
    pytest.importorskip("neutts", reason="NeuTTS not installed")
    from voice_forge.backends.neutts import _chunk_text

    long_sentence = (
        "This is a very long single sentence that exceeds the max chars limit "
        "and has no period in the middle."
    )
    chunks = _chunk_text(long_sentence, 20)
    assert len(chunks) == 1
    assert chunks[0] == long_sentence

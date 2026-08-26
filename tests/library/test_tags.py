from pathlib import Path

import pytest

from skywave.library.tags import read_tags

FIXTURES = Path(__file__).parent.parent / "fixtures" / "library"


@pytest.mark.parametrize("filename", ["full-tags.mp3", "full-tags.flac"])
def test_reads_full_tags(filename: str) -> None:
    tags = read_tags(FIXTURES / filename)

    assert tags["artist"] == "Test Artist"
    assert tags["title"] == "Test Title"
    assert tags["album"] == "Test Album"
    assert tags["date"] == "1999"
    assert tags["duration_seconds"] == pytest.approx(1.0, abs=0.1)


def test_missing_tags_are_none_not_a_crash() -> None:
    tags = read_tags(FIXTURES / "no-tags.mp3")

    assert tags["artist"] is None
    assert tags["title"] is None
    assert tags["album"] is None
    assert tags["date"] is None
    assert tags["duration_seconds"] == pytest.approx(1.0, abs=0.1)


def test_partial_tags_only_fills_whats_present() -> None:
    tags = read_tags(FIXTURES / "partial-tags.flac")

    assert tags["title"] == "Solo Title"
    assert tags["artist"] is None
    assert tags["album"] is None
    assert tags["date"] is None

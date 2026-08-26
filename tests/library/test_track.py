import dataclasses
from pathlib import Path

import pytest

from skywave.library.track import Track


def _tags(**overrides: object) -> dict:
    base = {"artist": None, "title": None, "album": None, "date": None, "duration_seconds": 200.0}
    return {**base, **overrides}


def test_from_tags_uses_tags_when_present() -> None:
    path = Path("/music/Queen - Sheer Heart Attack/01 - Brighton Rock.flac")
    tags = _tags(artist="Queen", title="Brighton Rock", album="Sheer Heart Attack", date="1974")

    track = Track.from_tags(path, tags)

    assert track.artist == "Queen"
    assert track.title == "Brighton Rock"
    assert track.album == "Sheer Heart Attack"
    assert track.year == 1974
    assert track.duration_seconds == 200.0
    assert track.path == path


def test_from_tags_falls_back_to_folder_and_filename_when_missing() -> None:
    path = Path("/music/Electric Light Orchestra - Time/01 - Prologue.wav")

    track = Track.from_tags(path, _tags())

    assert track.artist == "Electric Light Orchestra"
    assert track.album == "Time"
    assert track.title == "Prologue"
    assert track.year is None


def test_from_tags_filename_track_number_without_dash() -> None:
    # "REO Speedwagon The Hits/14 Ridin' the Storm Out.wav" en la práctica:
    # solo un espacio entre el número y el título, sin guion.
    path = Path("/music/REO Speedwagon The Hits/14 Ridin the Storm Out.wav")

    track = Track.from_tags(path, _tags())

    assert track.title == "Ridin the Storm Out"


def test_from_tags_filename_disc_track_number_prefix() -> None:
    # "Electric Light Orchestra - Time/5-11 21st Century Man.wav" en la
    # práctica: rip de un box set con prefijo "disco-pista".
    path = Path("/music/Electric Light Orchestra - Time/5-11 21st Century Man.wav")

    track = Track.from_tags(path, _tags())

    assert track.title == "21st Century Man"


def test_from_tags_folder_without_separator_is_all_artist() -> None:
    path = Path("/music/Megadeth/03 - Symphony of Destruction.flac")

    track = Track.from_tags(path, _tags())

    assert track.artist == "Megadeth"
    assert track.album is None


def test_from_tags_partial_tags_only_falls_back_for_whats_missing() -> None:
    path = Path("/music/Europe - The Final Countdown/02 - Rock the Night.flac")
    tags = _tags(artist="Europe")

    track = Track.from_tags(path, tags)

    assert track.artist == "Europe"
    assert track.album == "The Final Countdown"
    assert track.title == "Rock the Night"


def test_track_is_frozen() -> None:
    track = Track.from_tags(Path("/music/x/01 - y.mp3"), _tags(artist="a", title="b"))

    with pytest.raises(dataclasses.FrozenInstanceError):
        track.title = "otro"  # type: ignore[misc]


def test_tracks_with_same_fields_are_equal() -> None:
    path = Path("/music/x/01 - y.mp3")
    tags = _tags(artist="a", title="b")

    assert Track.from_tags(path, tags) == Track.from_tags(path, tags)

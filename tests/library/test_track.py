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


def test_from_tags_nested_artist_album_folders_needs_root() -> None:
    # Megadeth/Rust In Peace/06 Lucretia.wav: sin root, no hay forma de
    # distinguir esto de "la carpeta entera es el artista" (caso de
    # arriba) — se mantiene el comportamiento viejo.
    path = Path("/music/Megadeth/Rust In Peace/06 Lucretia.wav")

    track = Track.from_tags(path, _tags())

    assert track.artist == "Rust In Peace"
    assert track.album is None


def test_from_tags_nested_artist_album_folders_with_root() -> None:
    # Con root, "Rust In Peace" (sin separador) se reconoce como álbum y
    # se sube un nivel a buscar el artista real.
    path = Path("/music/Megadeth/Rust In Peace/06 Lucretia.wav")

    track = Track.from_tags(path, _tags(), root=Path("/music"))

    assert track.artist == "Megadeth"
    assert track.album == "Rust In Peace"


def test_from_tags_flat_artist_album_folder_ignores_root() -> None:
    # Pasar root no debería romper el caso simple de una sola carpeta
    # "Artista - Álbum" ya resuelto sin necesidad de subir de nivel.
    path = Path("/music/Electric Light Orchestra - Time/01 - Prologue.wav")

    track = Track.from_tags(path, _tags(), root=Path("/music"))

    assert track.artist == "Electric Light Orchestra"
    assert track.album == "Time"


def test_from_tags_grandparent_folder_itself_has_artist_album_separator() -> None:
    # Queen - Sheer Heart Attack.../Sheer Heart Attack/track.flac: la
    # carpeta de arriba también tiene "Artista - Álbum" — se parsea igual,
    # no se toma el string entero como artista.
    path = Path(
        "/music/Queen - Sheer Heart Attack 2011- Remastered/Sheer Heart Attack/"
        "01 Brighton Rock.flac"
    )

    track = Track.from_tags(path, _tags(), root=Path("/music"))

    assert track.artist == "Queen"
    assert track.album == "Sheer Heart Attack"


def test_from_tags_root_equal_to_immediate_folder_does_not_climb() -> None:
    # Si la carpeta inmediata YA es la raíz del escaneo (se escaneó
    # apuntando directo a la carpeta del álbum), no hay carpeta de arriba
    # dentro de lo escaneado a la que subir — subir usaría algo fuera del
    # árbol escaneado.
    path = Path("/music/Rust In Peace/06 Lucretia.wav")

    track = Track.from_tags(path, _tags(), root=Path("/music/Rust In Peace"))

    assert track.artist == "Rust In Peace"
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

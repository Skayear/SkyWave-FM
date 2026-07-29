from pathlib import Path

from skywave.library.scanner import find_audio_files


def _touch(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch()


def test_finds_audio_files_recursively(tmp_path: Path) -> None:
    _touch(tmp_path / "artist" / "album" / "track.mp3")
    _touch(tmp_path / "artist" / "album" / "track.flac")
    _touch(tmp_path / "other.ogg")

    found = set(find_audio_files(tmp_path))

    assert found == {
        tmp_path / "artist" / "album" / "track.mp3",
        tmp_path / "artist" / "album" / "track.flac",
        tmp_path / "other.ogg",
    }


def test_ignores_non_audio_files(tmp_path: Path) -> None:
    _touch(tmp_path / "cover.jpg")
    _touch(tmp_path / "readme.txt")
    _touch(tmp_path / "track.mp3")

    found = list(find_audio_files(tmp_path))

    assert found == [tmp_path / "track.mp3"]


def test_ignores_hidden_files_and_eadir(tmp_path: Path) -> None:
    _touch(tmp_path / ".hidden.mp3")
    _touch(tmp_path / "@eaDir" / "thumbnail.mp3")
    _touch(tmp_path / "track.mp3")

    found = list(find_audio_files(tmp_path))

    assert found == [tmp_path / "track.mp3"]


def test_extension_matching_is_case_insensitive(tmp_path: Path) -> None:
    _touch(tmp_path / "track.MP3")

    found = list(find_audio_files(tmp_path))

    assert found == [tmp_path / "track.MP3"]

import shutil
from pathlib import Path

from typer.testing import CliRunner

from skywave.cli import app

FIXTURES = Path(__file__).parent / "fixtures" / "library"
runner = CliRunner()


def test_scan_then_list_shows_the_scanned_track(tmp_path: Path) -> None:
    musica = tmp_path / "musica"
    musica.mkdir()
    shutil.copy(FIXTURES / "full-tags.mp3", musica / "full-tags.mp3")
    db_path = tmp_path / "library.db"

    scan_result = runner.invoke(app, ["scan", str(musica), "--db", str(db_path)])
    assert scan_result.exit_code == 0
    assert "1 tracks" in scan_result.output

    list_result = runner.invoke(app, ["list", "--db", str(db_path)])
    assert list_result.exit_code == 0
    assert "Test Artist" in list_result.output
    assert "Test Title" in list_result.output


def test_rescanning_the_same_folder_does_not_duplicate_rows(tmp_path: Path) -> None:
    musica = tmp_path / "musica"
    musica.mkdir()
    shutil.copy(FIXTURES / "full-tags.flac", musica / "full-tags.flac")
    db_path = tmp_path / "library.db"

    runner.invoke(app, ["scan", str(musica), "--db", str(db_path)])
    runner.invoke(app, ["scan", str(musica), "--db", str(db_path)])

    list_result = runner.invoke(app, ["list", "--db", str(db_path)])
    assert list_result.output.count("Test Artist") == 1


def test_list_on_empty_library_shows_a_hint(tmp_path: Path) -> None:
    db_path = tmp_path / "library.db"

    result = runner.invoke(app, ["list", "--db", str(db_path)])

    assert result.exit_code == 0
    assert "vacía" in result.output


def test_scan_on_nonexistent_folder_fails_cleanly(tmp_path: Path) -> None:
    result = runner.invoke(
        app, ["scan", str(tmp_path / "no-existe"), "--db", str(tmp_path / "library.db")]
    )

    assert result.exit_code != 0

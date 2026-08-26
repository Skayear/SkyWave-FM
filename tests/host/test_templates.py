import random
from datetime import datetime
from pathlib import Path

import pytest

from skywave.host.templates import _franja, render_script
from skywave.library.track import Track


def _track(artist: str, title: str, year: int | None = None) -> Track:
    return Track(
        path=Path(f"/music/{artist}/{title}.flac"),
        artist=artist,
        title=title,
        album=None,
        year=year,
        duration_seconds=180.0,
    )


QUEEN = _track("Queen", "Brighton Rock", year=1974)
SIN_ANIO = _track("Electric Light Orchestra", "Prologue")
TARDE = datetime(2026, 8, 26, 15, 0)


def test_menciona_al_tema_que_arranca() -> None:
    script = render_script(None, QUEEN, now=TARDE, rng=random.Random(1))

    assert "Queen" in script
    assert "Brighton Rock" in script


def test_con_tema_anterior_lo_despide() -> None:
    script = render_script(SIN_ANIO, QUEEN, now=TARDE, rng=random.Random(1))

    assert "Prologue" in script
    assert "Brighton Rock" in script


def test_sin_tema_anterior_no_hay_despedida() -> None:
    # Al arrancar la radio no hay nada que despedir: el guion abre
    # directamente con la presentación.
    for seed in range(10):
        script = render_script(None, QUEEN, now=TARDE, rng=random.Random(seed))
        assert script.startswith(("Ahora", "Le sigue", "A continuación", "Seguimos", "Viajamos"))


def test_nunca_aparece_none_en_el_guion() -> None:
    # Track sin año ni álbum: ninguna plantilla debe filtrar un "None".
    for seed in range(50):
        script = render_script(SIN_ANIO, SIN_ANIO, now=TARDE, rng=random.Random(seed))
        assert "None" not in script
        assert script  # nunca vacío


def test_deterministico_con_seed() -> None:
    a = render_script(SIN_ANIO, QUEEN, now=TARDE, rng=random.Random(7))
    b = render_script(SIN_ANIO, QUEEN, now=TARDE, rng=random.Random(7))

    assert a == b


@pytest.mark.parametrize(
    ("hour", "esperada"),
    [(3, "madrugada"), (9, "mañana"), (15, "tarde"), (22, "noche")],
)
def test_franja_por_hora(hour: int, esperada: str) -> None:
    assert _franja(hour) == esperada

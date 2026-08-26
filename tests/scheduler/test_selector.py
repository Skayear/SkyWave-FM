import random
from datetime import datetime
from pathlib import Path

import pytest

from skywave.library.track import Track
from skywave.scheduler.selector import pick_next


def _track(artist: str, title: str, duration: float = 180.0) -> Track:
    return Track(
        path=Path(f"/music/{artist}/{title}.flac"),
        artist=artist,
        title=title,
        album=None,
        year=None,
        duration_seconds=duration,
    )


QUEEN = _track("Queen", "Brighton Rock")
QUEEN_2 = _track("Queen", "Misfire")
EUROPE = _track("Europe", "The Final Countdown")
ELO = _track("ELO", "Twilight")
CATALOG = [QUEEN, QUEEN_2, EUROPE, ELO]


def test_respects_no_repeat_window() -> None:
    # Queen y Europe sonaron en los últimos 2 temas: el único artista
    # elegible es ELO, así que el resultado es determinístico.
    history = [QUEEN, EUROPE]

    track = pick_next(CATALOG, history, no_repeat_artist=2, rng=random.Random(1))

    assert track == ELO


def test_relaxes_window_when_no_candidate_qualifies() -> None:
    # Los 3 artistas del catálogo sonaron dentro de la ventana: con la regla
    # estricta no habría candidatos. Debe relajar y devolver algo igual.
    history = [QUEEN, EUROPE, ELO]

    track = pick_next(CATALOG, history, no_repeat_artist=3, rng=random.Random(1))

    assert track in CATALOG


def test_final_relaxation_avoids_repeating_the_exact_same_track() -> None:
    # Catálogo de un solo artista: la regla de artista nunca califica y se
    # relaja hasta el final, pero al menos no repite el mismo tema seguido.
    catalog = [QUEEN, QUEEN_2]
    history = [QUEEN_2]

    for seed in range(20):
        track = pick_next(catalog, history, no_repeat_artist=3, rng=random.Random(seed))
        assert track == QUEEN


def test_single_track_catalog_still_plays() -> None:
    # Caso extremo: un solo tema en la biblioteca. Repetirlo es inevitable
    # y preferible a quedarse muda.
    track = pick_next([QUEEN], [QUEEN], no_repeat_artist=3, rng=random.Random(1))

    assert track == QUEEN


def test_deterministic_with_fixed_seed() -> None:
    history: list[Track] = []

    first = pick_next(CATALOG, history, no_repeat_artist=2, rng=random.Random(42))
    second = pick_next(CATALOG, history, no_repeat_artist=2, rng=random.Random(42))

    assert first == second


def test_empty_catalog_raises() -> None:
    with pytest.raises(ValueError, match="vacío"):
        pick_next([], [], rng=random.Random(1))


MADRUGADA = datetime(2026, 8, 26, 3, 0)
TARDE = datetime(2026, 8, 26, 15, 0)
EPICO = _track("Iron Maiden", "Rime of the Ancient Mariner", duration=810.0)
CORTO = _track("Ramones", "Blitzkrieg Bop", duration=132.0)


def test_night_block_prefers_short_tracks() -> None:
    catalog = [EPICO, CORTO]

    for seed in range(20):
        track = pick_next(catalog, [], rng=random.Random(seed), now=MADRUGADA)
        assert track == CORTO


def test_daytime_has_no_duration_restriction() -> None:
    # De tarde el tema largo tiene que poder sonar: con el corto recién
    # tocado en el historial, el largo es el único candidato elegible.
    catalog = [EPICO, CORTO]

    track = pick_next(catalog, [CORTO], no_repeat_artist=1, rng=random.Random(1), now=TARDE)

    assert track == EPICO


def test_night_block_is_ignored_if_no_short_tracks_exist() -> None:
    # Solo temas largos en la biblioteca: la regla de madrugada se ignora
    # antes que dejar la radio muda.
    catalog = [EPICO]

    track = pick_next(catalog, [], rng=random.Random(1), now=MADRUGADA)

    assert track == EPICO

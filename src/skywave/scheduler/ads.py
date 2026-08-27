import random
from collections.abc import Sequence
from pathlib import Path


def should_play_ad(tracks_since_last_ad: int, *, every: int = 8) -> bool:
    """True cuando ya pasaron `every` temas musicales desde la última
    publicidad — el contador lo lleva el llamador (`skywave play`), esto
    solo dice si ya toca."""
    return tracks_since_last_ad >= every


def pick_next_ad(
    ads: Sequence[Path],
    history: Sequence[Path],
    *,
    no_repeat: int = 2,
    rng: random.Random | None = None,
) -> Path:
    """Elige la próxima publicidad al azar entre las que no sonaron en las
    últimas `no_repeat` publicidades.

    Mismo patrón de relajación que `pick_next()` de temas musicales (Fase
    3): si la ventana pedida deja el pool vacío, se achica de a uno hasta
    encontrar candidatos — nunca se queda sin publicidad para elegir. Acá
    no hay ventana por "artista": la publicidad entera es la unidad que no
    se repite, así que la ventana es más chica por default (con solo un
    puñado de publicidades curadas a mano, una ventana grande las agotaría
    en seguida).
    """
    if not ads:
        raise ValueError("no hay publicidades para elegir")
    if rng is None:
        rng = random.Random()

    for window in range(min(no_repeat, len(ads) - 1), -1, -1):
        recent = set(history[-window:]) if window > 0 else set()
        candidates = [ad for ad in ads if ad not in recent]

        if window == 0 and history and len(candidates) > 1:
            # Última relajación: al menos no repetir la que sonó recién.
            candidates = [ad for ad in candidates if ad != history[-1]]

        if candidates:
            return rng.choice(candidates)

    raise AssertionError("inalcanzable: con window=0 siempre hay candidatos")

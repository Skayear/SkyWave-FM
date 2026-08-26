import random
from collections.abc import Sequence

from skywave.library.track import Track


def pick_next(
    catalog: Sequence[Track],
    history: Sequence[Track],
    *,
    no_repeat_artist: int = 3,
    rng: random.Random | None = None,
) -> Track:
    """Elige la próxima pista: al azar entre las que su artista no sonó en
    los últimos `no_repeat_artist` temas.

    Si ningún track califica (biblioteca chica, ventana muy grande), la
    ventana se achica de a uno hasta encontrar candidatos — la radio nunca
    se queda muda por una regla demasiado estricta.

    `rng` se inyecta como parámetro (en vez de usar el módulo `random`
    global) para que los tests puedan pasar `random.Random(seed)` y ser
    determinísticos. En producción se omite y usa azar real.
    """
    if not catalog:
        raise ValueError("el catálogo está vacío, no hay nada para elegir")
    if rng is None:
        rng = random.Random()

    for window in range(no_repeat_artist, -1, -1):
        # Ojo con window=0: history[-0:] NO es una lista vacía, es la lista
        # entera (el slice -0 equivale a 0). Por eso el caso se maneja aparte.
        recent = history[-window:] if window > 0 else []
        recent_artists = {track.artist for track in recent}
        candidates = [track for track in catalog if track.artist not in recent_artists]

        if window == 0 and history and len(candidates) > 1:
            # Última relajación: ya no filtramos por artista, pero al menos
            # evitamos repetir exactamente el mismo tema que recién sonó.
            candidates = [track for track in candidates if track != history[-1]]

        if candidates:
            return rng.choice(candidates)

    raise AssertionError("inalcanzable: con window=0 siempre hay candidatos")

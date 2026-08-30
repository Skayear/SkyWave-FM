import random
from collections.abc import Sequence
from datetime import datetime

from skywave.library.track import Track

# Bloque "madrugada": de 0 a 5 inclusive se prefieren temas cortos.
# Regla mínima a propósito — la interfaz de bloques horarios queda
# preparada, pero configurar bloques por género/franja necesita metadata
# que la biblioteca todavía no tiene. Se profundiza cuando crezca.
_NIGHT_HOURS = range(0, 6)
_NIGHT_MAX_DURATION_SECONDS = 240.0


def _hourly_pool(catalog: Sequence[Track], now: datetime) -> Sequence[Track]:
    """Reduce el catálogo según la franja horaria. Si la regla dejaría el
    pool vacío, se ignora — mismo principio que la ventana de artista: la
    radio nunca se queda muda por una regla."""
    if now.hour in _NIGHT_HOURS:
        short = [t for t in catalog if t.duration_seconds <= _NIGHT_MAX_DURATION_SECONDS]
        if short:
            return short
    return catalog


def pick_next(
    catalog: Sequence[Track],
    history: Sequence[Track],
    *,
    no_repeat_artist: int = 3,
    rng: random.Random | None = None,
    now: datetime | None = None,
) -> Track:
    """Elige la próxima pista: al azar entre las que su artista no sonó en
    los últimos `no_repeat_artist` temas, dentro del pool de la franja
    horaria actual.

    Si ningún track califica (biblioteca chica, ventana muy grande), la
    ventana se achica de a uno hasta encontrar candidatos — la radio nunca
    se queda muda por una regla demasiado estricta.

    `rng` y `now` se inyectan como parámetros (en vez de usar `random` y
    `datetime.now()` globales adentro) para que los tests puedan fijar
    seed y hora y ser determinísticos. En producción se omiten y usan el
    azar y el reloj reales.
    """
    if not catalog:
        raise ValueError("el catálogo está vacío, no hay nada para elegir")
    if rng is None:
        rng = random.Random()
    if now is None:
        now = datetime.now()

    catalog = _hourly_pool(catalog, now)

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


def plan_queue(
    catalog: Sequence[Track],
    history: Sequence[Track],
    already_queued: Sequence[Track],
    *,
    target_depth: int,
    no_repeat_artist: int = 3,
    rng: random.Random | None = None,
    now: datetime | None = None,
) -> list[Track]:
    """Temas nuevos para completar la cola planificada hasta
    `target_depth` (issue #40) -- no toca nada persistido, quien llama
    decide qué hacer con el resultado (`library.db.enqueue_track`).

    `already_queued` son los temas que ya están en la cola pero todavía
    no sonaron: cuentan para la ventana de no-repetición igual que
    `history`, así no se planifica el mismo artista dos veces seguidas
    dentro de la cola. Si la cola ya llegó a `target_depth`, devuelve
    una lista vacía."""
    missing = target_depth - len(already_queued)
    if missing <= 0:
        return []
    if rng is None:
        rng = random.Random()

    working_history = list(history) + list(already_queued)
    planned: list[Track] = []
    for _ in range(missing):
        track = pick_next(
            catalog, working_history, no_repeat_artist=no_repeat_artist, rng=rng, now=now
        )
        planned.append(track)
        working_history.append(track)
    return planned

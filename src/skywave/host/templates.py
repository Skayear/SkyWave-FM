import random
from datetime import datetime

from skywave.library.track import Track

# El piso del locutor: si el LLM (issue #18) falla o no está, esto es lo
# que sale al aire. Por eso vive en su propio módulo sin dependencias: no
# puede fallar por nada externo.

# Sin artículo: las plantillas ponen el que corresponde ("esta madrugada").
# Las cuatro son femeninas, así que "esta {franja}" siempre concuerda.
_FRANJAS = (
    (range(0, 6), "madrugada"),
    (range(6, 12), "mañana"),
    (range(12, 20), "tarde"),
    (range(20, 24), "noche"),
)

_DESPEDIDAS = (
    "Eso fue «{title}», de {artist}.",
    "Escuchamos a {artist} con «{title}».",
    "Sonaba «{title}», por {artist}.",
)

_PRESENTACIONES = (
    "Ahora, {artist} con «{title}».",
    "Le sigue «{title}», de {artist}.",
    "A continuación, {artist}: «{title}».",
    "Seguimos con «{title}», de {artist}.",
)

# Solo entran al pool cuando el track tiene año: así nunca hay que
# rellenar un {year} que no existe.
_PRESENTACIONES_CON_ANIO = (
    "Ahora, del año {year}: {artist} con «{title}».",
    "Viajamos al {year}. {artist}: «{title}».",
)

_COLETILLAS = (
    "Esto es SkyWave FM.",
    "Seguimos juntos en esta {franja}, acá en SkyWave FM.",
    "",  # a veces el locutor no agrega nada, para no sonar repetitivo
)


def _franja(hour: int) -> str:
    for horas, nombre in _FRANJAS:
        if hour in horas:
            return nombre
    raise ValueError(f"hora fuera de rango: {hour}")


def render_script(
    ending: Track | None,
    starting: Track,
    *,
    now: datetime | None = None,
    rng: random.Random | None = None,
) -> str:
    """Genera un guion corto de locutor desde plantillas fijas.

    `ending` es None al arrancar la radio (no hay tema que despedir).
    `rng` y `now` inyectables, mismo patrón que el selector del scheduler.
    """
    if rng is None:
        rng = random.Random()
    if now is None:
        now = datetime.now()

    parts: list[str] = []

    if ending is not None:
        despedida = rng.choice(_DESPEDIDAS)
        parts.append(despedida.format(title=ending.title, artist=ending.artist))

    presentaciones = _PRESENTACIONES + (
        _PRESENTACIONES_CON_ANIO if starting.year is not None else ()
    )
    presentacion = rng.choice(presentaciones)
    parts.append(
        presentacion.format(title=starting.title, artist=starting.artist, year=starting.year)
    )

    coletilla = rng.choice(_COLETILLAS).format(franja=_franja(now.hour))
    if coletilla:
        parts.append(coletilla)

    return " ".join(parts)

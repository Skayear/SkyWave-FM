import random
from datetime import datetime
from pathlib import Path

import pytest

from skywave.host.scripts import (
    ClaudeGenerator,
    ResilientScriptWriter,
    TemplateGenerator,
    _base_title,
    _mentions_track,
    english_terms_for,
)
from skywave.library.track import Track

TARDE = datetime(2026, 8, 26, 15, 0)
QUEEN = Track(
    path=Path("/music/Queen/Brighton Rock.flac"),
    artist="Queen",
    title="Brighton Rock",
    album=None,
    year=1974,
    duration_seconds=311.0,
)
MECHANIX_REMIX = Track(
    path=Path("/music/Megadeth/Mechanix [2002 Remix].flac"),
    artist="Megadeth",
    title="Mechanix [2002 Remix]",
    album=None,
    year=2002,
    duration_seconds=280.0,
)
RIDIN = Track(
    path=Path("/music/REO Speedwagon The Hits/Ridin’ the Storm Out.wav"),
    artist="REO Speedwagon The Hits",
    title="Ridin’ the Storm Out",
    album=None,
    year=None,
    duration_seconds=260.0,
)


class _RespuestaClaudeFalsa:
    """Imita la forma mínima de una respuesta de `client.messages.create`
    (`response.content[0].text`) sin depender del SDK real."""

    def __init__(self, text: str) -> None:
        self.content = [type("Bloque", (), {"text": text})()]


class _MessagesFalso:
    def __init__(self, text: str | None, error: Exception | None) -> None:
        self._text = text
        self._error = error

    def create(self, **kwargs: object) -> _RespuestaClaudeFalsa:
        if self._error is not None:
            raise self._error
        assert self._text is not None
        return _RespuestaClaudeFalsa(self._text)


class ClienteClaudeFalso:
    """Doble del cliente `anthropic.Anthropic`: nunca pega a la API real,
    solo expone `.messages.create(...)` con la respuesta o el error que
    se le pida de antemano."""

    def __init__(self, text: str | None = None, error: Exception | None = None) -> None:
        self.messages = _MessagesFalso(text, error)


class GeneradorRoto:
    def generate(self, ending: Track | None, starting: Track, now: datetime) -> str:
        raise ConnectionError("Ollama no responde")


class GeneradorFijo:
    def generate(self, ending: Track | None, starting: Track, now: datetime) -> str:
        return "Guion del LLM."


def test_usa_el_primario_cuando_funciona() -> None:
    writer = ResilientScriptWriter(GeneradorFijo(), TemplateGenerator(random.Random(1)))

    assert writer.generate(None, QUEEN, TARDE) == "Guion del LLM."


def test_cae_a_plantillas_si_el_primario_explota() -> None:
    writer = ResilientScriptWriter(GeneradorRoto(), TemplateGenerator(random.Random(1)))

    script = writer.generate(None, QUEEN, TARDE)

    assert "Brighton Rock" in script  # vino de las plantillas, no del LLM


def test_sin_primario_va_directo_a_plantillas() -> None:
    writer = ResilientScriptWriter(None, TemplateGenerator(random.Random(1)))

    script = writer.generate(None, QUEEN, TARDE)

    assert "Brighton Rock" in script


def test_mentions_track_encuentra_el_titulo_sin_importar_mayusculas() -> None:
    assert _mentions_track("Ahora escuchamos BRIGHTON ROCK de Queen", QUEEN)


def test_mentions_track_detecta_un_tema_inventado() -> None:
    # Caso real: el LLM alucinó "El Amante" de Juan Luis Guerra en vez del
    # tema real que se le pasó en el prompt.
    assert not _mentions_track("Ahora un clásico: El Amante de Juan Luis Guerra", QUEEN)


def test_mentions_track_ignora_el_sufijo_entre_corchetes() -> None:
    # Caso real: el LLM dijo "la versión remezclada de 'Mechanix'" — dato
    # correcto, pero nadie dice "corchete 2002 remix corchete" al aire.
    assert _mentions_track("la versión remezclada de 'Mechanix' de Megadeth", MECHANIX_REMIX)


def test_base_title_saca_el_sufijo_entre_corchetes() -> None:
    assert _base_title("Mechanix [2002 Remix]") == "Mechanix"


def test_base_title_sin_corchetes_no_cambia() -> None:
    assert _base_title("Brighton Rock") == "Brighton Rock"


def test_mentions_track_normaliza_comillas_tipograficas() -> None:
    # Caso real: el título viene con comilla curva (U+2019, típico de
    # nombres de archivo de Apple Music/iTunes) pero el LLM escribe con
    # apóstrofo recto normal — mismo texto para un oído humano.
    assert _mentions_track('A continuación, "Ridin\' the Storm Out" de REO Speedwagon', RIDIN)


def test_english_terms_for_incluye_titulo_y_artista_del_entrante() -> None:
    assert english_terms_for(None, QUEEN) == ["Brighton Rock", "Queen"]


def test_english_terms_for_incluye_tambien_el_saliente() -> None:
    terms = english_terms_for(QUEEN, MECHANIX_REMIX)

    assert "Mechanix" in terms  # sin el sufijo entre corchetes
    assert "Megadeth" in terms
    assert "Brighton Rock" in terms
    assert "Queen" in terms


def test_english_terms_for_normaliza_comillas_y_no_duplica() -> None:
    # RIDIN tiene comilla curva en el título; el artista repite "REO
    # Speedwagon The Hits" completo -- no hay título/artista duplicado
    # entre saliente y entrante en este caso, pero el mismo string no
    # debería aparecer dos veces si ending == starting.
    terms = english_terms_for(RIDIN, RIDIN)

    assert terms.count("REO Speedwagon The Hits") == 1
    assert "Ridin' the Storm Out" in terms  # comilla recta, no curva


def test_template_generator_cumple_la_interfaz() -> None:
    # El Protocol no se hereda: alcanza con tener la firma. Esto verifica
    # que TemplateGenerator la tiene de verdad.
    generator = TemplateGenerator(random.Random(1))

    script = generator.generate(QUEEN, QUEEN, TARDE)

    assert isinstance(script, str) and script


def test_claude_generator_cumple_la_interfaz() -> None:
    generator = ClaudeGenerator(
        client=ClienteClaudeFalso(text="Ahora suena Brighton Rock de Queen.")
    )

    assert generator.generate(None, QUEEN, TARDE) == "Ahora suena Brighton Rock de Queen."


def test_claude_generator_detecta_un_tema_inventado() -> None:
    generator = ClaudeGenerator(
        client=ClienteClaudeFalso(text="Ahora un clásico: El Amante de Juan Luis Guerra")
    )

    with pytest.raises(ValueError):
        generator.generate(None, QUEEN, TARDE)


def test_claude_generator_detecta_respuesta_vacia() -> None:
    generator = ClaudeGenerator(client=ClienteClaudeFalso(text="   "))

    with pytest.raises(ValueError):
        generator.generate(None, QUEEN, TARDE)


def test_claude_generator_propaga_errores_de_red() -> None:
    generator = ClaudeGenerator(client=ClienteClaudeFalso(error=ConnectionError("sin red")))

    with pytest.raises(ConnectionError):
        generator.generate(None, QUEEN, TARDE)

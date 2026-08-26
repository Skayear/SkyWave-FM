import random
from datetime import datetime
from pathlib import Path

from skywave.host.scripts import ResilientScriptWriter, TemplateGenerator
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


def test_template_generator_cumple_la_interfaz() -> None:
    # El Protocol no se hereda: alcanza con tener la firma. Esto verifica
    # que TemplateGenerator la tiene de verdad.
    generator = TemplateGenerator(random.Random(1))

    script = generator.generate(QUEEN, QUEEN, TARDE)

    assert isinstance(script, str) and script

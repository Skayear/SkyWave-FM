import json
import logging
import random
import urllib.request
from datetime import datetime
from typing import Protocol

from skywave.host.templates import render_script
from skywave.library.track import Track

logger = logging.getLogger(__name__)


class ScriptGenerator(Protocol):
    """Interfaz común de los generadores de guiones.

    Un Protocol es duck typing tipado: cualquier clase con un método
    `generate` de esta firma califica, sin heredar de nada. Permite
    intercambiar Ollama / API de Claude / plantillas sin tocar el resto.
    """

    def generate(self, ending: Track | None, starting: Track, now: datetime) -> str: ...


class TemplateGenerator:
    """Las plantillas de templates.py detrás de la interfaz común."""

    def __init__(self, rng: random.Random | None = None) -> None:
        self._rng = rng if rng is not None else random.Random()

    def generate(self, ending: Track | None, starting: Track, now: datetime) -> str:
        return render_script(ending, starting, now=now, rng=self._rng)


def _prompt(ending: Track | None, starting: Track, now: datetime) -> str:
    lines = [
        "Sos el locutor de SkyWave FM, una radio de rock en español rioplatense.",
        "Escribí UNA intervención breve (una o dos oraciones) para decir al aire entre dos temas.",
        "Sin emojis, sin comillas alrededor, sin explicaciones: solo lo que dice el locutor.",
        "No inventes datos, películas ni anécdotas: usá solo la información de acá abajo.",
        f"Hora actual: {now.strftime('%H:%M')}.",
    ]
    if ending is not None:
        lines.append(f"Acaba de terminar: «{ending.title}» de {ending.artist}.")
    extra = f" (año {starting.year})" if starting.year else ""
    lines.append(f"Ahora empieza: «{starting.title}» de {starting.artist}{extra}.")
    return "\n".join(lines)


class OllamaGenerator:
    """Guiones contra la API HTTP local de Ollama (/api/generate).

    Cualquier problema (Ollama apagado, timeout, respuesta vacía) sale
    como excepción: el que decide qué hacer con eso es el fallback de
    ResilientScriptWriter, no esta clase.
    """

    def __init__(
        self,
        model: str = "llama3.2:3b",
        base_url: str = "http://localhost:11434",
        timeout_seconds: float = 30.0,
    ) -> None:
        self._model = model
        self._base_url = base_url
        self._timeout = timeout_seconds

    def generate(self, ending: Track | None, starting: Track, now: datetime) -> str:
        payload = {
            "model": self._model,
            "prompt": _prompt(ending, starting, now),
            "stream": False,
            # num_predict acota la respuesta: un guion de radio son un par
            # de oraciones, no un ensayo. También acota la latencia, que
            # en CPU es proporcional a los tokens generados.
            "options": {"num_predict": 80, "temperature": 0.9},
        }
        request = urllib.request.Request(
            f"{self._base_url}/api/generate",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=self._timeout) as response:
            data = json.load(response)
        text = data.get("response", "").strip().strip('"').strip()
        if not text:
            raise ValueError("Ollama devolvió un guion vacío")
        return text


class ResilientScriptWriter:
    """Intenta el generador primario (LLM); si falla por lo que sea, cae a
    las plantillas. La radio nunca se queda muda ni esperando."""

    def __init__(self, primary: ScriptGenerator | None, fallback: ScriptGenerator) -> None:
        self._primary = primary
        self._fallback = fallback

    def generate(self, ending: Track | None, starting: Track, now: datetime) -> str:
        if self._primary is not None:
            try:
                return self._primary.generate(ending, starting, now)
            except Exception as error:
                # Una línea al aire logs; el traceback completo solo en debug
                # — con Ollama apagado esto pasa en cada tema y no es un bug.
                logger.warning("Generador primario falló (%s), caigo a plantillas", error)
                logger.debug("Detalle del fallo del generador primario", exc_info=True)
        return self._fallback.generate(ending, starting, now)

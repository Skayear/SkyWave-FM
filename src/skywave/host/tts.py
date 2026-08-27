import re
import warnings
from pathlib import Path

import numpy as np
import soundfile as sf

# Warnings de torch al cargar el modelo (dropout con 1 capa, weight_norm
# deprecado) son ruido interno de Kokoro, no algo que este proyecto pueda
# arreglar — se silencian para no ensuciar la consola en cada arranque.
warnings.filterwarnings("ignore", category=UserWarning, module="torch")
warnings.filterwarnings("ignore", category=FutureWarning, module="torch")

from kokoro import KPipeline  # noqa: E402

DEFAULT_LANG_CODE = "e"  # español
DEFAULT_VOICE = "ef_dora"
_REPO_ID = "hexgrad/Kokoro-82M"
_SAMPLE_RATE = 24000

# Kokoro parte el texto en fragmentos por cada salto de línea (su
# `split_pattern` default es r'\n+') y sintetiza cada uno por separado sin
# silencio entre medio al pegarlos — un guion guardado en un .txt con
# saltos de línea "de lectura" (para que no queden líneas eternas en el
# archivo) suena cortado en lugares que no tienen nada que ver con la
# puntuación real. Colapsar los saltos de línea a espacios antes de
# sintetizar evita ese corte.
_WHITESPACE = re.compile(r"\s+")


def _normalize_text(text: str) -> str:
    return _WHITESPACE.sub(" ", text).strip()


class Synthesizer:
    """Convierte texto a WAV con Kokoro (voz `ef_dora`, español).

    Reemplaza a Piper (Fase 4): comparadas en ramas separadas contra
    XTTS-v2 (issue #24), Kokoro sonó mejor a la escucha y fue ~10x más
    rápido que XTTS-v2 en CPU (~9s vs ~91s por guion) — aunque sigue
    siendo más lento que Piper (~1.8s). El modelo (~82M de parámetros)
    se carga UNA vez acá y se reusa en cada síntesis: un pipeline nuevo
    por guion lo recargaría cada vez, igual que pasaba con Piper.

    El WAV sale a 24000Hz mono, el formato nativo de Kokoro; no hace
    falta convertirlo, el Decoder del mixer resamplea cualquier cosa a
    44100Hz estéreo de todos modos.
    """

    def __init__(self, lang_code: str = DEFAULT_LANG_CODE, voice: str = DEFAULT_VOICE) -> None:
        self._voice = voice
        try:
            self._pipeline = KPipeline(lang_code=lang_code, repo_id=_REPO_ID)
        except Exception as error:
            # Kokoro baja el modelo de Hugging Face la primera vez que se
            # usa: sin red (o si nunca se bajó) esto explota acá. Mismo
            # contrato que tenía Piper: FileNotFoundError es lo que
            # _build_locutor() en cli.py atrapa para arrancar sin locutor
            # en vez de crashear.
            raise FileNotFoundError(f"No se pudo cargar el modelo de Kokoro: {error}") from error

    def synthesize(self, text: str, wav_path: Path) -> Path:
        wav_path.parent.mkdir(parents=True, exist_ok=True)
        text = _normalize_text(text)
        chunks = [audio for _, _, audio in self._pipeline(text, voice=self._voice)]
        audio = np.concatenate(chunks)
        sf.write(str(wav_path), audio, _SAMPLE_RATE)
        return wav_path

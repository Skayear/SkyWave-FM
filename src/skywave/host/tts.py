import re
import warnings
from collections.abc import Sequence
from pathlib import Path

import numpy as np
import soundfile as sf

# Warnings de torch al cargar el modelo (dropout con 1 capa, weight_norm
# deprecado) son ruido interno de Kokoro, no algo que este proyecto pueda
# arreglar — se silencian para no ensuciar la consola en cada arranque.
warnings.filterwarnings("ignore", category=UserWarning, module="torch")
warnings.filterwarnings("ignore", category=FutureWarning, module="torch")

from kokoro import KPipeline  # noqa: E402
from misaki import en as misaki_en  # noqa: E402

DEFAULT_LANG_CODE = "e"  # español
DEFAULT_VOICE = "ef_dora"
_REPO_ID = "hexgrad/Kokoro-82M"
_SAMPLE_RATE = 24000
# Límite duro de KPipeline.generate_from_tokens para una cadena de
# fonemas cruda: pasarse explota con ValueError en vez de truncar solo.
_MAX_PHONEME_LENGTH = 510

_QUOTE_NORMALIZE = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"'})

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


def _split_by_terms(text: str, terms: Sequence[str]) -> list[tuple[str, bool]]:
    """Parte `text` en segmentos `(fragmento, es_inglés)`, alternando el
    texto en español con los `terms` (títulos/artistas) que aparezcan tal
    cual dentro — sin importar mayúsculas ni el estilo de apóstrofo.
    Términos más largos primero, para no partir "REO Speedwagon" por la
    mitad si "REO" también fuera un término."""
    unique_terms = sorted({t for t in terms if t}, key=len, reverse=True)
    if not unique_terms:
        return [(text, False)]
    pattern = "|".join(re.escape(t) for t in unique_terms)
    parts = re.split(f"({pattern})", text, flags=re.IGNORECASE)
    # re.split con grupo de captura alterna: par=texto sin matchear,
    # impar=el término que matcheó.
    return [(part, index % 2 == 1) for index, part in enumerate(parts) if part]


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
        # G2P de inglés aparte del de español (self._pipeline.g2p): con
        # voz en español, Kokoro fonemiza TODO con reglas de español —
        # los títulos/artistas en inglés (`english_terms`) se fonemizan
        # acá para que se pronuncien de verdad como en inglés.
        self._en_g2p = misaki_en.G2P(british=False, fallback=None, unk="")

    def synthesize(self, text: str, wav_path: Path, english_terms: Sequence[str] = ()) -> Path:
        wav_path.parent.mkdir(parents=True, exist_ok=True)
        text = _normalize_text(text)
        audio = self._synthesize_mixed(text, english_terms) if english_terms else None
        if audio is None:
            chunks = [chunk for _, _, chunk in self._pipeline(text, voice=self._voice)]
            audio = np.concatenate(chunks)
        sf.write(str(wav_path), audio, _SAMPLE_RATE)
        return wav_path

    def _synthesize_mixed(self, text: str, english_terms: Sequence[str]) -> np.ndarray | None:
        """Fonemiza `text` a mano, con el motor de inglés para
        `english_terms` y el de español (el de `self._pipeline`) para el
        resto, y sintetiza esa cadena de fonemas de una sola vez.

        Devuelve None si el resultado no entra en el límite del modelo
        (510 caracteres de fonemas) para que el llamador caiga a la
        síntesis normal — peor pronunciación del título, pero sigue
        sonando en vez de perder la intervención entera por un guion
        largo.
        """
        phonemes = self._phonemize(text, english_terms)
        if not phonemes or len(phonemes) > _MAX_PHONEME_LENGTH:
            return None
        results = list(self._pipeline.generate_from_tokens(phonemes, voice=self._voice))
        return np.concatenate([result.audio.numpy() for result in results])

    def _phonemize(self, text: str, english_terms: Sequence[str]) -> str:
        text = text.translate(_QUOTE_NORMALIZE)
        terms = [t.translate(_QUOTE_NORMALIZE) for t in english_terms]
        parts = []
        for segment, is_english in _split_by_terms(text, terms):
            segment = segment.strip()
            if not segment:
                continue
            g2p = self._en_g2p if is_english else self._pipeline.g2p
            phonemes, _ = g2p(segment)
            if phonemes:
                parts.append(phonemes)
        return " ".join(parts)

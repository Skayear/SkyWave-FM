import hashlib
from collections.abc import Callable, Sequence
from pathlib import Path


class VoiceCache:
    """Cache en disco de WAVs sintetizados, keyed por hash del texto.

    Con plantillas, los mismos guiones se repiten muchísimo: sintetizar
    una sola vez y servir el WAV cacheado el resto de las veces.

    La función de síntesis se INYECTA (cualquier callable con la firma de
    Synthesizer.synthesize) — mismo patrón que el rng del selector, pero
    con una función: los tests pasan una fake y no necesitan Kokoro ni su
    modelo.

    La voz forma parte de la clave del hash: cambiar de voz no debe
    servir WAVs viejos de la anterior.
    """

    def __init__(
        self,
        synthesize: Callable[[str, Path, Sequence[str]], Path],
        voice_id: str,
        cache_dir: Path = Path("cache"),
    ) -> None:
        self._synthesize = synthesize
        self._voice_id = voice_id
        self._cache_dir = cache_dir

    def wav_for(self, text: str, english_terms: Sequence[str] = ()) -> Path:
        key = hashlib.sha256(f"{self._voice_id}\n{text}".encode()).hexdigest()
        wav_path = self._cache_dir / f"{key}.wav"
        if not wav_path.exists():
            # Sintetizar a un temporal y renombrar: si la síntesis explota a
            # mitad de camino no queda un WAV corrupto con el nombre final,
            # que el cache serviría para siempre. El rename dentro del mismo
            # directorio es atómico en POSIX.
            tmp_path = wav_path.with_suffix(".tmp.wav")
            self._synthesize(text, tmp_path, english_terms)
            tmp_path.replace(wav_path)
        return wav_path

import wave
from pathlib import Path

from piper import PiperVoice

DEFAULT_VOICE = Path("voices/es_AR-daniela-high.onnx")


class Synthesizer:
    """Convierte texto a WAV con una voz de Piper.

    Usa la API de Python de piper en vez de invocar el CLI por subprocess:
    el modelo (~114MB de ONNX) se carga UNA vez acá y se reusa en cada
    síntesis. Un proceso nuevo por guion lo recargaría cada vez — segundos
    de latencia por intervención del locutor, al pedo.

    El WAV sale con el formato nativo de la voz (22050Hz mono para
    es_AR-daniela-high); no hace falta convertirlo, el Decoder del mixer
    resamplea cualquier cosa a 44100Hz estéreo de todos modos.
    """

    def __init__(self, model_path: Path = DEFAULT_VOICE) -> None:
        if not model_path.exists():
            raise FileNotFoundError(
                f"No está el modelo de voz {model_path}. Bajalo con: "
                f"uv run python -m piper.download_voices --download-dir voices "
                f"{model_path.stem}"
            )
        self._voice = PiperVoice.load(model_path)

    def synthesize(self, text: str, wav_path: Path) -> Path:
        wav_path.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(wav_path), "wb") as wav_file:
            self._voice.synthesize_wav(text, wav_file)
        return wav_path

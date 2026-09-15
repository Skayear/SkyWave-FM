"""Spike descartable (issue #35): generar un clip corto con MusicGen-small
en CPU para comparar contra Stable Audio Open más adelante. No es parte
del CLI real de skywave -- vive solo en la rama spike/audiocraft."""

import time
from pathlib import Path

from audiocraft.data.audio import audio_write
from audiocraft.models import MusicGen

PROMPT = "upbeat synth radio station ID jingle, three seconds, energetic"
OUT_DIR = Path(__file__).parent / "spike-audio"
OUT_DIR.mkdir(exist_ok=True)

print(f"Cargando MusicGen-small...")
t0 = time.monotonic()
model = MusicGen.get_pretrained("facebook/musicgen-small")
model.set_generation_params(duration=3)
t_load = time.monotonic() - t0
print(f"Modelo cargado en {t_load:.1f}s")

print(f"Generando: {PROMPT!r}")
t0 = time.monotonic()
wav = model.generate([PROMPT])
t_gen = time.monotonic() - t0
print(f"Generado en {t_gen:.1f}s")

out_path = OUT_DIR / "musicgen-small"
audio_write(
    str(out_path), wav[0].cpu(), model.sample_rate, strategy="loudness", loudness_compressor=True
)
print(f"Guardado en {out_path}.wav")
print(f"TIEMPOS -- carga: {t_load:.1f}s, generación: {t_gen:.1f}s")

"""Spike descartable (issue #35): genera un clip corto con Stable Audio
Open para comparar contra el spike de MusicGen (rama spike/audiocraft).
No es parte del CLI real de skywave -- vive solo en esta rama."""

import time

import soundfile as sf
import torch
from diffusers import StableAudioPipeline

MODEL_ID = "stabilityai/stable-audio-open-1.0"
PROMPT = "upbeat synth radio station ID jingle, three seconds, energetic"
DURATION_S = 3.0
OUT_PATH = "spike-audio/stable-audio-open.wav"

print(f"Cargando {MODEL_ID} (CPU, float32)...")
t0 = time.time()
pipe = StableAudioPipeline.from_pretrained(MODEL_ID, torch_dtype=torch.float32)
pipe = pipe.to("cpu")
load_s = time.time() - t0
print(f"Modelo cargado en {load_s:.1f}s")

generator = torch.Generator("cpu").manual_seed(0)

print(f"Generando {DURATION_S}s de audio para: {PROMPT!r}")
t0 = time.time()
audio = pipe(
    prompt=PROMPT,
    negative_prompt="Low quality.",
    num_inference_steps=100,
    audio_end_in_s=DURATION_S,
    num_waveforms_per_prompt=1,
    generator=generator,
).audios
gen_s = time.time() - t0
print(f"Generación real: {gen_s:.1f}s")

output = audio[0].T.float().cpu().numpy()
sf.write(OUT_PATH, output, pipe.vae.sampling_rate)
print(f"Guardado en {OUT_PATH}")
print(f"RESUMEN load_s={load_s:.1f} gen_s={gen_s:.1f}")

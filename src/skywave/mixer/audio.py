from __future__ import annotations

import numpy as np

# Todo el PCM del proyecto es s16le, 44100Hz, estéreo (ver mixer/decoder.py,
# mixer/encoder.py). Acá vive como np.int16 con shape (frames, 2).
_CHANNELS = 2


def bytes_to_samples(pcm: bytes) -> np.ndarray:
    """PCM s16le crudo -> array int16 con shape (frames, 2)."""
    return np.frombuffer(pcm, dtype=np.int16).reshape(-1, _CHANNELS)


def samples_to_bytes(samples: np.ndarray) -> bytes:
    """Array int16 (frames, 2) -> PCM s16le crudo, listo para el pipe del Encoder."""
    return samples.astype(np.int16).tobytes()


def apply_gain(samples: np.ndarray, gain: float) -> np.ndarray:
    """Escala el volumen por `gain` (1.0 = sin cambio).

    Pasa a float64 antes de escalar: escalar directo en int16 desborda
    (envuelve, no clipea) apenas `gain` > 1 con una señal ya alta. Clipear
    al rango de int16 antes de volver a castear evita ese wraparound.
    """
    scaled = samples.astype(np.float64) * gain
    return np.clip(scaled, np.iinfo(np.int16).min, np.iinfo(np.int16).max).astype(np.int16)


def mix(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Suma dos señales (mismo largo) con clipping controlado."""
    if a.shape != b.shape:
        raise ValueError(f"las señales deben tener el mismo shape: {a.shape} != {b.shape}")
    summed = a.astype(np.float64) + b.astype(np.float64)
    return np.clip(summed, np.iinfo(np.int16).min, np.iinfo(np.int16).max).astype(np.int16)


def fade_in(samples: np.ndarray) -> np.ndarray:
    """Aplica una rampa lineal de 0 a 1 a lo largo de toda la señal."""
    return _apply_ramp(samples, start=0.0, end=1.0)


def fade_out(samples: np.ndarray) -> np.ndarray:
    """Aplica una rampa lineal de 1 a 0 a lo largo de toda la señal."""
    return _apply_ramp(samples, start=1.0, end=0.0)


def _apply_ramp(samples: np.ndarray, *, start: float, end: float) -> np.ndarray:
    envelope = np.linspace(start, end, num=len(samples))[:, np.newaxis]
    scaled = samples.astype(np.float64) * envelope
    return np.clip(scaled, np.iinfo(np.int16).min, np.iinfo(np.int16).max).astype(np.int16)

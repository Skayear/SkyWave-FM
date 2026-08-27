from __future__ import annotations

import wave
from collections.abc import Sequence
from pathlib import Path

import numpy as np

from skywave.mixer.audio import bytes_to_samples, fade_in, fade_out, mix, samples_to_bytes
from skywave.mixer.decoder import Decoder

_SAMPLE_RATE = 44100
_CHANNELS = 2

# Colchón: acorde de Do mayor (Do4-Mi4-Sol4) sostenido y bien atenuado —
# va debajo de la voz, no tiene que competir con ella.
_BED_CHORD_HZ = (261.63, 329.63, 392.00)
_BED_AMPLITUDE = 0.12
_BED_EDGE_SECONDS = 0.6

# Stinger de apertura/cierre: arpegio cortito tipo campanita de radio,
# para llamar la atención antes y después de la voz de la publicidad.
_STINGER_NOTES_HZ = (659.25, 987.77)  # Mi5, Si5
_STINGER_NOTE_SECONDS = 0.18
_STINGER_AMPLITUDE = 0.35


def _tone(frequency_hz: float, duration_seconds: float, *, amplitude: float) -> np.ndarray:
    """Un tono senoidal estéreo (mismo valor en los dos canales)."""
    frame_count = int(_SAMPLE_RATE * duration_seconds)
    t = np.arange(frame_count) / _SAMPLE_RATE
    mono = (np.sin(2 * np.pi * frequency_hz * t) * amplitude * np.iinfo(np.int16).max).astype(
        np.int16
    )
    return np.repeat(mono[:, np.newaxis], _CHANNELS, axis=1)


def _chord(
    frequencies_hz: Sequence[float], duration_seconds: float, *, amplitude: float
) -> np.ndarray:
    """Varios tonos sonando juntos (mix), no en secuencia."""
    notes = [_tone(f, duration_seconds, amplitude=amplitude) for f in frequencies_hz]
    chord = notes[0]
    for note in notes[1:]:
        chord = mix(chord, note)
    return chord


def _fade_edges(samples: np.ndarray, edge_seconds: float) -> np.ndarray:
    """Fade-in/fade-out solo en los bordes, sostenido a volumen pleno en
    el medio — a diferencia de `fade_in`/`fade_out` de audio.py, que
    rampean la señal entera de punta a punta (pensadas para crossfade
    entre temas, no para un colchón sostenido)."""
    edge_frames = min(int(_SAMPLE_RATE * edge_seconds), len(samples) // 2)
    if edge_frames == 0:
        return samples
    head = fade_in(samples[:edge_frames])
    tail = fade_out(samples[-edge_frames:])
    middle = samples[edge_frames:-edge_frames]
    return np.concatenate([head, middle, tail])


def generate_bed(duration_seconds: float) -> np.ndarray:
    """Colchón musical sostenido para poner debajo de la voz."""
    chord = _chord(_BED_CHORD_HZ, duration_seconds, amplitude=_BED_AMPLITUDE)
    return _fade_edges(chord, _BED_EDGE_SECONDS)


def generate_stinger() -> np.ndarray:
    """SFX cortito de apertura/cierre: un arpegio ascendente tipo campanita."""
    notes = [
        _tone(f, _STINGER_NOTE_SECONDS, amplitude=_STINGER_AMPLITUDE) for f in _STINGER_NOTES_HZ
    ]
    return np.concatenate(notes)


def _write_wav(path: Path, pcm: bytes) -> None:
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(_CHANNELS)
        wav_file.setsampwidth(2)
        wav_file.setframerate(_SAMPLE_RATE)
        wav_file.writeframes(pcm)


def produce_ad(voice_wav_path: Path) -> None:
    """Arma el WAV final de una publicidad: stinger de apertura, la voz
    sobre un colchón musical atenuado, stinger de cierre. Sobreescribe
    `voice_wav_path` (que ya tiene la voz sola, recién sintetizada) con
    el resultado mezclado.

    Decodifica la voz con el `Decoder` del mixer en vez de leer el WAV a
    mano: normaliza a PCM s16le/44100Hz/estéreo igual que el resto del
    proyecto, sin importar el formato nativo de la voz (24000Hz mono con
    Kokoro).
    """
    voice = b"".join(Decoder(voice_wav_path).chunks())
    voice_samples = bytes_to_samples(voice)
    bed = generate_bed(len(voice_samples) / _SAMPLE_RATE)
    frames = min(len(voice_samples), len(bed))
    with_bed = mix(voice_samples[:frames], bed[:frames])
    stinger = generate_stinger()
    final = np.concatenate([stinger, with_bed, stinger])
    _write_wav(voice_wav_path, samples_to_bytes(final))

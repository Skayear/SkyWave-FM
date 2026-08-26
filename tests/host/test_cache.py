from pathlib import Path

import pytest

from skywave.host.cache import VoiceCache


class FakeSynth:
    """Doble de prueba de Synthesizer.synthesize: escribe un archivo trucho
    y cuenta cuántas veces la llamaron."""

    def __init__(self, fail: bool = False) -> None:
        self.calls = 0
        self.fail = fail

    def __call__(self, text: str, wav_path: Path) -> Path:
        self.calls += 1
        if self.fail:
            raise RuntimeError("síntesis rota")
        wav_path.parent.mkdir(parents=True, exist_ok=True)
        wav_path.write_bytes(f"WAV de: {text}".encode())
        return wav_path


def test_primera_llamada_sintetiza(tmp_path: Path) -> None:
    synth = FakeSynth()
    cache = VoiceCache(synth, voice_id="daniela", cache_dir=tmp_path)

    wav = cache.wav_for("Hola radio")

    assert synth.calls == 1
    assert wav.read_bytes() == b"WAV de: Hola radio"


def test_segunda_llamada_no_vuelve_a_sintetizar(tmp_path: Path) -> None:
    synth = FakeSynth()
    cache = VoiceCache(synth, voice_id="daniela", cache_dir=tmp_path)

    first = cache.wav_for("Hola radio")
    second = cache.wav_for("Hola radio")

    assert synth.calls == 1
    assert first == second


def test_textos_distintos_van_a_archivos_distintos(tmp_path: Path) -> None:
    cache = VoiceCache(FakeSynth(), voice_id="daniela", cache_dir=tmp_path)

    assert cache.wav_for("guion uno") != cache.wav_for("guion dos")


def test_cambiar_de_voz_no_sirve_wavs_viejos(tmp_path: Path) -> None:
    synth = FakeSynth()
    daniela = VoiceCache(synth, voice_id="daniela", cache_dir=tmp_path)
    otra = VoiceCache(synth, voice_id="otra-voz", cache_dir=tmp_path)

    wav_daniela = daniela.wav_for("Hola radio")
    wav_otra = otra.wav_for("Hola radio")

    assert wav_daniela != wav_otra
    assert synth.calls == 2


def test_sintesis_rota_no_deja_archivo_corrupto_cacheado(tmp_path: Path) -> None:
    roto = FakeSynth(fail=True)
    cache = VoiceCache(roto, voice_id="daniela", cache_dir=tmp_path)

    with pytest.raises(RuntimeError):
        cache.wav_for("Hola radio")

    # El reintento vuelve a sintetizar (no quedó nada cacheado a medias)
    sano = FakeSynth()
    cache_sano = VoiceCache(sano, voice_id="daniela", cache_dir=tmp_path)
    cache_sano.wav_for("Hola radio")

    assert sano.calls == 1

import numpy as np

from skywave.mixer.audio import (
    apply_gain,
    bytes_to_samples,
    fade_in,
    fade_out,
    mix,
    samples_to_bytes,
)


def _samples(*frames: tuple[int, int]) -> np.ndarray:
    return np.array(frames, dtype=np.int16)


def test_round_trip_bytes_array_bytes() -> None:
    original = _samples((100, -100), (0, 32000), (-32768, 32767))

    pcm = samples_to_bytes(original)
    back = bytes_to_samples(pcm)

    assert np.array_equal(back, original)


def test_ganancia_media_baja_la_amplitud_a_la_mitad() -> None:
    samples = _samples((1000, -1000), (2000, -2000))

    result = apply_gain(samples, 0.5)

    assert np.array_equal(result, _samples((500, -500), (1000, -1000)))


def test_ganancia_alta_clipea_sin_desbordar() -> None:
    samples = _samples(
        (30000, -30000),
    )

    result = apply_gain(samples, 2.0)

    maximo = np.iinfo(np.int16).max
    minimo = np.iinfo(np.int16).min
    assert result[0, 0] == maximo
    assert result[0, 1] == minimo
    # Si desbordara (wraparound) en vez de clipear, darían valores negativos/positivos
    # inesperados en vez de quedarse pegados al límite.
    assert result[0, 0] != -1


def test_mix_de_dos_senales_a_maximo_no_desborda() -> None:
    maximo = np.iinfo(np.int16).max
    a = _samples((maximo, maximo))
    b = _samples((maximo, maximo))

    result = mix(a, b)

    assert np.array_equal(result, _samples((maximo, maximo)))


def test_mix_suma_normal_sin_clipping() -> None:
    a = _samples((100, -100), (0, 0))
    b = _samples((50, -50), (10, -10))

    result = mix(a, b)

    assert np.array_equal(result, _samples((150, -150), (10, -10)))


def test_fade_in_arranca_en_silencio_y_termina_a_volumen_completo() -> None:
    samples = np.full((4, 2), 1000, dtype=np.int16)

    result = fade_in(samples)

    assert result[0, 0] == 0
    assert result[-1, 0] == 1000


def test_fade_out_arranca_a_volumen_completo_y_termina_en_silencio() -> None:
    samples = np.full((4, 2), 1000, dtype=np.int16)

    result = fade_out(samples)

    assert result[0, 0] == 1000
    assert result[-1, 0] == 0

import numpy as np

from skywave.ads.jingle import (
    _SAMPLE_RATE,
    _chord,
    _fade_edges,
    _tone,
    generate_bed,
    generate_stinger,
)


def test_tone_genera_la_cantidad_de_frames_esperada() -> None:
    samples = _tone(440.0, 1.0, amplitude=0.5)

    assert len(samples) == _SAMPLE_RATE
    assert samples.shape[1] == 2


def test_tone_no_excede_la_amplitud_pedida() -> None:
    samples = _tone(440.0, 0.5, amplitude=0.5)

    limite = 0.5 * np.iinfo(np.int16).max
    assert np.abs(samples).max() <= limite + 1  # +1 de margen por redondeo


def test_chord_sostiene_el_largo_de_una_sola_nota() -> None:
    chord = _chord([261.63, 329.63, 392.0], 0.5, amplitude=0.1)

    assert len(chord) == int(_SAMPLE_RATE * 0.5)


def test_chord_no_clipea_con_varias_notas_a_full() -> None:
    # Con amplitud alta por nota, la suma de tres no debería envolver
    # (wraparound) al límite de int16 -- tiene que clipear, no desbordar.
    chord = _chord([261.63, 329.63, 392.0], 0.1, amplitude=0.9)

    assert chord.max() <= np.iinfo(np.int16).max
    assert chord.min() >= np.iinfo(np.int16).min


def test_fade_edges_sostiene_el_medio_a_volumen_pleno() -> None:
    samples = np.full((_SAMPLE_RATE, 2), 1000, dtype=np.int16)  # 1s a volumen constante

    faded = _fade_edges(samples, 0.1)

    mitad = len(faded) // 2
    assert faded[mitad, 0] == 1000
    assert faded[0, 0] == 0
    assert faded[-1, 0] == 0


def test_fade_edges_no_pierde_frames_si_el_borde_pedido_es_mas_largo_que_la_senal() -> None:
    samples = np.full((100, 2), 1000, dtype=np.int16)

    faded = _fade_edges(samples, 10.0)  # borde absurdamente largo

    assert len(faded) == 100


def test_generate_bed_dura_lo_pedido() -> None:
    bed = generate_bed(2.0)

    assert len(bed) == int(_SAMPLE_RATE * 2.0)


def test_generate_stinger_no_esta_vacio() -> None:
    stinger = generate_stinger()

    assert len(stinger) > 0
    assert stinger.shape[1] == 2

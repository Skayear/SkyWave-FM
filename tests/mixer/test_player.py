from skywave.mixer.player import (
    _crossfade,
    _duck_envelope,
    _duck_mix,
    _take,
    crossfade_window_bytes,
)


def test_crossfade_window_bytes_ida_y_vuelta() -> None:
    # 1s a 44100Hz, estéreo, s16le: 44100 frames * 2 canales * 2 bytes.
    assert crossfade_window_bytes(1.0) == 44100 * 4


def test_take_junta_exactamente_lo_pedido_y_deja_el_resto_en_el_iterador() -> None:
    chunks = iter([b"AAAA", b"BBBB", b"CCCC"])

    collected, rest = _take(chunks, 6)

    assert collected == b"AAAABB"
    assert list(rest) == [b"BB", b"CCCC"]


def test_take_con_stream_mas_corto_que_lo_pedido_devuelve_todo() -> None:
    chunks = iter([b"AAAA", b"BB"])

    collected, rest = _take(chunks, 100)

    assert collected == b"AAAABB"
    assert list(rest) == []


def test_crossfade_de_silencio_con_senal_dan_la_mitad_del_fade_in() -> None:
    # PCM: 2 frames estéreo, s16le. Tail en silencio, head a volumen constante.
    tail = (0).to_bytes(2, "little", signed=True) * 4  # 2 frames, ambos canales en 0
    head_sample = (1000).to_bytes(2, "little", signed=True)
    head = head_sample * 4  # 2 frames, ambos canales en 1000

    result = _crossfade(tail, head)

    assert len(result) == len(head)
    # El fade-in arranca en 0 (primer frame) y sube hacia el final.
    first_frame = int.from_bytes(result[0:2], "little", signed=True)
    last_frame = int.from_bytes(result[-4:-2], "little", signed=True)
    assert first_frame == 0
    assert last_frame > first_frame


def test_crossfade_usa_el_largo_menor_cuando_difieren() -> None:
    sample = (100).to_bytes(2, "little", signed=True) * 2  # 1 frame estéreo
    tail = sample * 3  # 3 frames
    head = sample * 1  # 1 frame

    result = _crossfade(tail, head)

    assert len(result) == len(head)


def test_duck_envelope_baja_sostiene_y_sube() -> None:
    envelope = _duck_envelope(10, duck_gain=0.25, ramp_frames=2)

    assert len(envelope) == 10
    assert envelope[0] == 1.0  # arranca a volumen pleno
    assert list(envelope[2:8]) == [0.25] * 6  # sostiene atenuado en el medio
    assert envelope[-1] == 1.0  # termina a volumen pleno


def test_duck_envelope_recorta_las_rampas_si_el_segmento_es_corto() -> None:
    # Con ramp_frames=100 pero solo 4 frames, no puede haber "sostenido":
    # la mitad baja, la mitad sube, sin que se pisen.
    envelope = _duck_envelope(4, duck_gain=0.25, ramp_frames=100)

    assert len(envelope) == 4


def test_duck_mix_atenua_la_musica_bajo_la_voz() -> None:
    frame = (1000).to_bytes(2, "little", signed=True) * 2  # 1 frame estéreo
    speech = frame * 4
    music = frame * 4

    result = _duck_mix(speech, music, duck_gain=0.25, ramp_seconds=0.0)

    assert len(result) == len(speech)
    # Sin rampa (ramp_seconds=0), el colchón entero está atenuado a 0.25:
    # voz (1000) + música*0.25 (250) = 1250 en cada muestra.
    first_sample = int.from_bytes(result[0:2], "little", signed=True)
    assert first_sample == 1250


def test_duck_mix_usa_el_largo_menor_cuando_difieren() -> None:
    frame = (1000).to_bytes(2, "little", signed=True) * 2
    speech = frame * 5
    music = frame * 2

    result = _duck_mix(speech, music, duck_gain=0.25, ramp_seconds=0.0)

    assert len(result) == len(music)

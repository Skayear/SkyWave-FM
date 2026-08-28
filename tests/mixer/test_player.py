import numpy as np

from skywave.mixer.player import (
    _crossfade,
    _duck_chunks,
    _duck_envelope,
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


def test_duck_envelope_silencio_fade_in_sostenido_y_release() -> None:
    # 10 frames de habla: 30% de silencio total (el locutor arranca hablando
    # solo), sube como colchón, sostiene, y el release ocurre en un tramo
    # aparte, recién después de que el habla terminó.
    envelope = _duck_envelope(10, duck_gain=0.4, solo_ratio=0.3, fade_in_frames=4, release_frames=2)

    assert len(envelope) == 12
    assert list(envelope[:3]) == [0.0, 0.0, 0.0]  # arranca en silencio total, sin música
    assert envelope[3] == 0.0  # el colchón empieza a subir desde cero
    assert list(envelope[7:10]) == [0.4, 0.4, 0.4]  # sostiene atenuado el resto del habla
    assert envelope[10] == 0.4  # el release recién arranca cuando el habla ya terminó
    assert envelope[-1] == 1.0  # termina a volumen pleno


def test_duck_envelope_recorta_el_fade_in_si_el_habla_es_corta() -> None:
    # Con fade_in_frames=100 pero solo 3 frames de habla (sin silencio),
    # no puede haber "sostenido": el fade-in se recorta a la duración del
    # habla.
    envelope = _duck_envelope(
        3, duck_gain=0.25, solo_ratio=0.0, fade_in_frames=100, release_frames=3
    )

    assert len(envelope) == 6


def test_duck_chunks_mezcla_con_la_envolvente_dada() -> None:
    frame = (1000).to_bytes(2, "little", signed=True) * 2  # 1 frame estéreo
    padded_speech = frame * 4
    envelope = np.array([0.0, 0.0, 0.25, 0.25])
    music_chunks = iter([frame * 4])  # un solo chunk con toda la música

    result = b"".join(_duck_chunks(music_chunks, padded_speech, envelope))

    assert len(result) == len(padded_speech)
    first_sample = int.from_bytes(result[0:2], "little", signed=True)
    assert first_sample == 1000  # envolvente en 0.0: solo voz, nada de música
    last_sample = int.from_bytes(result[-4:-2], "little", signed=True)
    assert last_sample == 1250  # voz (1000) + música*0.25 (250)


def test_duck_chunks_mezcla_a_traves_de_varios_chunks() -> None:
    # ffmpeg entrega la música en chunks de tamaño fijo que no
    # necesariamente coinciden con los tramos de la envolvente -- tiene
    # que funcionar igual mezclando parcialmente adentro de un chunk.
    frame = (1000).to_bytes(2, "little", signed=True) * 2
    padded_speech = frame * 4
    envelope = np.array([0.0, 0.0, 0.25, 0.25])
    music_chunks = iter([frame * 2, frame * 2])  # el corte cae justo a la mitad

    result = b"".join(_duck_chunks(music_chunks, padded_speech, envelope))

    assert len(result) == len(padded_speech)
    first_sample = int.from_bytes(result[0:2], "little", signed=True)
    assert first_sample == 1000
    last_sample = int.from_bytes(result[-4:-2], "little", signed=True)
    assert last_sample == 1250


def test_duck_chunks_deja_pasar_sin_mezclar_lo_que_sobra_de_la_envolvente() -> None:
    # Un chunk que cruza el final de la envolvente: la parte de adentro se
    # mezcla, la de afuera pasa intacta (la pista sola, sin voz de fondo).
    frame = (1000).to_bytes(2, "little", signed=True) * 2
    padded_speech = frame * 2
    envelope = np.array([0.0, 0.25])
    music_chunks = iter([frame * 4])  # 4 frames, la envolvente solo cubre 2

    result = b"".join(_duck_chunks(music_chunks, padded_speech, envelope))

    assert len(result) == len(frame) * 4
    third_sample = int.from_bytes(result[2 * 4 : 2 * 4 + 2], "little", signed=True)
    assert third_sample == 1000  # ya pasó la envolvente: música sola, sin mezclar


def test_duck_chunks_deja_pasar_chunks_enteros_una_vez_cubierta_la_envolvente() -> None:
    frame = (1000).to_bytes(2, "little", signed=True) * 2
    padded_speech = frame * 2
    envelope = np.array([0.0, 0.25])
    music_chunks = iter([frame * 2, frame * 3])  # el segundo chunk entero ya es "resto"

    result = b"".join(_duck_chunks(music_chunks, padded_speech, envelope))

    assert len(result) == len(frame) * 5

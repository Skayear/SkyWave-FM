import random
from pathlib import Path

import pytest

from skywave.scheduler.ads import pick_next_ad, should_play_ad

MATE = Path("/assets/ads/mate-turbo.wav")
SEGURO = Path("/assets/ads/seguro-el-zorro.wav")
COLCHON = Path("/assets/ads/colchones-nube-9.wav")
ADS = [MATE, SEGURO, COLCHON]


def test_should_play_ad_antes_del_umbral_es_false() -> None:
    assert should_play_ad(5, every=8) is False


def test_should_play_ad_en_el_umbral_es_true() -> None:
    assert should_play_ad(8, every=8) is True


def test_should_play_ad_pasado_el_umbral_tambien_es_true() -> None:
    # Por si el llamador se saltea un chequeo, no debería quedar trabado
    # esperando el número exacto.
    assert should_play_ad(9, every=8) is True


def test_pick_next_ad_respeta_la_ventana_de_no_repeticion() -> None:
    history = [MATE, SEGURO]

    ad = pick_next_ad(ADS, history, no_repeat=2, rng=random.Random(1))

    assert ad == COLCHON


def test_pick_next_ad_relaja_la_ventana_si_no_hay_candidatos() -> None:
    history = [MATE, SEGURO, COLCHON]

    ad = pick_next_ad(ADS, history, no_repeat=3, rng=random.Random(1))

    assert ad in ADS


def test_pick_next_ad_relajacion_final_evita_repetir_la_misma() -> None:
    ads = [MATE, SEGURO]
    history = [SEGURO]

    for seed in range(20):
        ad = pick_next_ad(ads, history, no_repeat=5, rng=random.Random(seed))
        assert ad == MATE


def test_pick_next_ad_una_sola_publicidad_igual_suena() -> None:
    ad = pick_next_ad([MATE], [MATE], no_repeat=2, rng=random.Random(1))

    assert ad == MATE


def test_pick_next_ad_deterministico_con_seed_fija() -> None:
    history: list[Path] = []

    first = pick_next_ad(ADS, history, no_repeat=2, rng=random.Random(42))
    second = pick_next_ad(ADS, history, no_repeat=2, rng=random.Random(42))

    assert first == second


def test_pick_next_ad_catalogo_vacio_explota() -> None:
    with pytest.raises(ValueError, match="no hay publicidades"):
        pick_next_ad([], [], rng=random.Random(1))

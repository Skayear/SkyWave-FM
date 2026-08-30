from skywave.scheduler.greetings import should_read_greeting


def test_should_read_greeting_antes_del_umbral_es_false() -> None:
    assert should_read_greeting(3, every=5) is False


def test_should_read_greeting_en_el_umbral_es_true() -> None:
    assert should_read_greeting(5, every=5) is True


def test_should_read_greeting_pasado_el_umbral_tambien_es_true() -> None:
    assert should_read_greeting(6, every=5) is True

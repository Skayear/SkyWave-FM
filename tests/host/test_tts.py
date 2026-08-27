from skywave.host.tts import _normalize_text


def test_normalize_text_colapsa_saltos_de_linea_a_espacio() -> None:
    # Caso real: un guion .txt con saltos de línea "de lectura" (para que
    # no queden líneas eternas en el archivo) -- Kokoro los toma como
    # cortes de oración y sintetiza cada línea por separado sin pausa
    # entre medio si no se normaliza antes.
    texto = "Probá Mate Turbo,\nla bombilla con calefacción\nincorporada."

    assert _normalize_text(texto) == "Probá Mate Turbo, la bombilla con calefacción incorporada."


def test_normalize_text_colapsa_espacios_multiples() -> None:
    assert _normalize_text("Hola   mundo") == "Hola mundo"


def test_normalize_text_saca_espacios_en_los_bordes() -> None:
    assert _normalize_text("  Hola mundo  \n") == "Hola mundo"


def test_normalize_text_sin_espacios_de_mas_no_cambia() -> None:
    assert _normalize_text("Hola mundo.") == "Hola mundo."

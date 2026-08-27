from skywave.host.tts import _normalize_text, _split_by_terms


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


def test_split_by_terms_sin_terminos_devuelve_todo_como_espanol() -> None:
    assert _split_by_terms("Ahora suena algo.", []) == [("Ahora suena algo.", False)]


def test_split_by_terms_alterna_espanol_e_ingles() -> None:
    texto = "Ahora suena Keep On Loving You de REO Speedwagon."
    segments = _split_by_terms(texto, ["Keep On Loving You", "REO Speedwagon"])

    assert segments == [
        ("Ahora suena ", False),
        ("Keep On Loving You", True),
        (" de ", False),
        ("REO Speedwagon", True),
        (".", False),
    ]


def test_split_by_terms_no_distingue_mayusculas() -> None:
    segments = _split_by_terms("suena keep on loving you ahora", ["Keep On Loving You"])

    assert segments[1] == ("keep on loving you", True)


def test_split_by_terms_prefiere_el_termino_mas_largo() -> None:
    # Si "REO" y "REO Speedwagon" son ambos términos, no debería partir
    # "REO Speedwagon" en "REO" + " Speedwagon" (sin marcar) por el medio.
    segments = _split_by_terms("de REO Speedwagon.", ["REO", "REO Speedwagon"])

    assert ("REO Speedwagon", True) in segments
    assert ("REO", True) not in segments


def test_split_by_terms_termino_ausente_no_rompe() -> None:
    segments = _split_by_terms("Ahora suena otra cosa.", ["Keep On Loving You"])

    assert segments == [("Ahora suena otra cosa.", False)]

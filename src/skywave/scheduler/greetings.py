def should_read_greeting(tracks_since_last_greeting: int, *, every: int = 5) -> bool:
    """True cuando ya pasaron `every` temas musicales desde el último
    saludo leído -- mismo contrato que `should_play_ad`, el contador lo
    lleva el llamador (`skywave play`).

    A diferencia de las publicidades no hace falta elegir *cuál* saludo
    leer: son FIFO puro (`web.greetings.unread_greetings`), así que no
    hay una función `pick_next_greeting` -- el orden ya lo da la cola."""
    return tracks_since_last_greeting >= every

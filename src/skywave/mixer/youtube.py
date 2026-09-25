"""Resuelve una URL de YouTube (video o directo) a una URL de media
directa que ffmpeg puede leer (issue #43).

YouTube no sirve el audio en una URL fija: hace falta yt-dlp para
resolverla del lado del cliente. Es un extra opcional
(`pyproject.toml`, `uv sync --extra relay`) -- no toda instalación de
skywave necesita el modo relay, así que el import va acá adentro en vez
de arriba del módulo, mismo criterio que `ClaudeGenerator` en
`host/scripts.py` con el SDK de Anthropic."""


def resolve_audio_url(youtube_url: str) -> str:
    try:
        import yt_dlp
    except ImportError as error:
        raise ImportError(
            "Falta el extra 'relay': instalá con `uv sync --extra relay` "
            "(o `pip install skywave[relay]`)."
        ) from error

    with yt_dlp.YoutubeDL({"format": "bestaudio/best", "quiet": True, "no_warnings": True}) as ydl:
        info = ydl.extract_info(youtube_url, download=False)

    url = info.get("url") if info else None
    if not url:
        raise ValueError(f"No se pudo resolver una URL de audio para {youtube_url!r}")
    return url

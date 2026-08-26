from pathlib import Path
from typing import Any

import mutagen


def read_tags(path: Path) -> dict[str, Any]:
    audio = mutagen.File(path, easy=True)
    if audio is None:
        raise ValueError(f"mutagen no reconoce el archivo como audio: {path}")

    def first(key: str) -> str | None:
        if audio.tags is None:
            return None
        values = audio.tags.get(key)
        return values[0] if values else None

    return {
        "artist": first("artist"),
        "title": first("title"),
        "album": first("album"),
        "date": first("date"),
        "duration_seconds": audio.info.length,
    }

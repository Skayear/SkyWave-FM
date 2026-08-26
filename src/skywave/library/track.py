from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# Número de pista al inicio del nombre de archivo, con disco opcional
# ("5-11 Título", rip de un box set) y seguido de un separador explícito
# ("01 - Título", "01.Título") o simplemente un espacio ("01 Título", como
# nombra REO Speedwagon The Hits en la práctica).
_TRACK_NUMBER_PREFIX = re.compile(r"^(?:\d+-)?\d+(?:\s*[-._]\s*|\s+)")
_YEAR = re.compile(r"\d{4}")


def _parse_folder_name(name: str) -> tuple[str, str | None]:
    """ "Artista - Álbum" -> (artista, álbum). Sin separador, todo es artista."""
    parts = re.split(r"\s+-\s+", name, maxsplit=1)
    if len(parts) == 2:
        return parts[0].strip(), parts[1].strip()
    return name.strip(), None


def _title_from_filename(path: Path) -> str:
    """ "01 - Prologue.wav" -> "Prologue": saca el número de pista inicial."""
    return _TRACK_NUMBER_PREFIX.sub("", path.stem).strip()


def _parse_year(date: str | None) -> int | None:
    if date is None:
        return None
    match = _YEAR.search(date)
    return int(match.group()) if match else None


@dataclass(frozen=True, slots=True)
class Track:
    """Una pista de la biblioteca. Inmutable: representa un hecho fijado en
    el momento del escaneo, no algo que se edite en memoria."""

    path: Path
    artist: str
    title: str
    album: str | None
    year: int | None
    duration_seconds: float

    @classmethod
    def from_tags(cls, path: Path, tags: dict[str, Any]) -> Track:
        """Arma un Track a partir del dict crudo de read_tags(). Si faltan
        artist/title/album, cae a la carpeta y el nombre de archivo — mejor
        un dato aproximado (parseado de "Artista - Álbum/NN - Título.ext")
        que un track sin nombre en la biblioteca."""
        folder_artist, folder_album = _parse_folder_name(path.parent.name)

        return cls(
            path=path,
            artist=tags["artist"] or folder_artist,
            title=tags["title"] or _title_from_filename(path),
            album=tags["album"] or folder_album,
            year=_parse_year(tags["date"]),
            duration_seconds=tags["duration_seconds"],
        )

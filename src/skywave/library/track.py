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


def _folder_artist_album(path: Path, root: Path | None) -> tuple[str, str | None]:
    """Determina (artista, álbum) de la carpeta cuando faltan tags.

    Caso simple: una sola carpeta "Artista - Álbum" (Electric Light
    Orchestra - Time/track.wav). Caso anidado: "Artista/Álbum/track.wav"
    sin separador en la carpeta inmediata (Megadeth/Rust In Peace/track.wav)
    — ahí la carpeta padre es el álbum y la de arriba el artista, siempre
    que esa carpeta de arriba no sea la raíz del escaneo (si no hay `root`,
    o la carpeta inmediata ya está pegada a la raíz, no hay forma de saber
    si subir un nivel más tiene sentido, y mejor no inventar).
    """
    folder = path.parent
    artist, album = _parse_folder_name(folder.name)
    if album is not None:
        return artist, album
    parent_folder = folder.parent
    # folder != root: si la carpeta inmediata ya es la raíz, no hay
    # "carpeta de arriba" dentro de lo escaneado a la que subir.
    # parent_folder != root: si la de arriba YA es la raíz, esto es el
    # caso plano (root/Carpeta/track, sin separador — ver REO Speedwagon
    # en los tests) y la carpeta entera se queda como artista, como antes.
    if root is not None and folder != root and parent_folder != root:
        # La carpeta de arriba puede a su vez ser "Artista - Álbum..."
        # (Queen - Sheer Heart Attack 2011- Remastered/Sheer Heart Attack/),
        # así que se parsea con la misma regla en vez de tomarla entera.
        grandparent_artist, _ = _parse_folder_name(parent_folder.name)
        return grandparent_artist, folder.name
    return artist, album


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
    def from_tags(cls, path: Path, tags: dict[str, Any], *, root: Path | None = None) -> Track:
        """Arma un Track a partir del dict crudo de read_tags(). Si faltan
        artist/title/album, cae a la carpeta y el nombre de archivo — mejor
        un dato aproximado (parseado de "Artista - Álbum/NN - Título.ext",
        o de "Artista/Álbum/NN - Título.ext" si se pasa `root`) que un
        track sin nombre en la biblioteca."""
        folder_artist, folder_album = _folder_artist_album(path, root)

        return cls(
            path=path,
            artist=tags["artist"] or folder_artist,
            title=tags["title"] or _title_from_filename(path),
            album=tags["album"] or folder_album,
            year=_parse_year(tags["date"]),
            duration_seconds=tags["duration_seconds"],
        )

from collections.abc import Iterator
from pathlib import Path

AUDIO_EXTENSIONS = {".mp3", ".flac", ".ogg", ".m4a", ".wav"}

# Synology NAS crea estas carpetas de miniaturas en cada directorio; no son
# ocultas (no empiezan con ".") pero tampoco queremos bajar ahí.
_IGNORED_DIR_NAMES = {"@eaDir"}


def _is_ignored_dir(name: str) -> bool:
    return name.startswith(".") or name in _IGNORED_DIR_NAMES


def find_audio_files(root: Path) -> Iterator[Path]:
    for dirpath, dirnames, filenames in root.walk():
        dirnames[:] = [d for d in dirnames if not _is_ignored_dir(d)]
        for name in filenames:
            if name.startswith("."):
                continue
            path = dirpath / name
            if path.suffix.lower() in AUDIO_EXTENSIONS:
                yield path

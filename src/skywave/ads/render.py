from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

_SCRIPT_EXTENSION = ".txt"


def render_ads(
    scripts_dir: Path,
    out_dir: Path,
    synthesize: Callable[[str, Path], Path],
) -> list[Path]:
    """Sintetiza cada guion curado a mano en `scripts_dir` (un .txt por
    publicidad) a un WAV en `out_dir`, con el mismo nombre de archivo.

    Es un paso manual/offline: se corre cuando se agrega o edita una
    publicidad, no forma parte del loop de la radio en vivo — las
    publicidades nunca se generan en vivo (issue #25 de Fase 6).
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    rendered = []
    for script_path in sorted(scripts_dir.glob(f"*{_SCRIPT_EXTENSION}")):
        text = script_path.read_text(encoding="utf-8").strip()
        wav_path = out_dir / f"{script_path.stem}.wav"
        rendered.append(synthesize(text, wav_path))
    return rendered

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

_SCRIPT_EXTENSION = ".txt"


def render_ads(
    scripts_dir: Path,
    out_dir: Path,
    synthesize: Callable[[str, Path], Path],
    *,
    produce: Callable[[Path], None] | None = None,
) -> list[Path]:
    """Sintetiza cada guion curado a mano en `scripts_dir` (un .txt por
    publicidad) a un WAV en `out_dir`, con el mismo nombre de archivo.

    Si se pasa `produce` (issue #26: jingle.produce_ad), se lo llama con
    el WAV recién sintetizado para sumarle colchón musical y SFX in situ
    antes de darlo por terminado — sin `produce`, el WAV queda con la voz
    sola (comportamiento de la issue #25).

    Es un paso manual/offline: se corre cuando se agrega o edita una
    publicidad, no forma parte del loop de la radio en vivo — las
    publicidades nunca se generan en vivo (issue #25 de Fase 6).
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    rendered = []
    for script_path in sorted(scripts_dir.glob(f"*{_SCRIPT_EXTENSION}")):
        text = script_path.read_text(encoding="utf-8").strip()
        wav_path = out_dir / f"{script_path.stem}.wav"
        synthesize(text, wav_path)
        if produce is not None:
            produce(wav_path)
        rendered.append(wav_path)
    return rendered


def list_ads(ads_dir: Path) -> list[Path]:
    """Publicidades ya renderizadas en `ads_dir`, para que el scheduler
    (issue #27) elija entre ellas. Solo `.wav` — no incluye `scripts/`
    (los guiones curados) ni nada que no sea un WAV ya producido."""
    if not ads_dir.exists():
        return []
    return sorted(ads_dir.glob("*.wav"))

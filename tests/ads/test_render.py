from pathlib import Path

from skywave.ads.render import render_ads


class FakeSynth:
    """Doble de prueba: escribe un archivo trucho en vez de llamar a Piper,
    y guarda qué le pidieron sintetizar."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, Path]] = []

    def __call__(self, text: str, wav_path: Path) -> Path:
        self.calls.append((text, wav_path))
        wav_path.parent.mkdir(parents=True, exist_ok=True)
        wav_path.write_bytes(f"WAV de: {text}".encode())
        return wav_path


def test_render_ads_sintetiza_cada_guion_txt(tmp_path: Path) -> None:
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    (scripts_dir / "mate-turbo.txt").write_text("Probá Mate Turbo.")
    (scripts_dir / "seguro-el-zorro.txt").write_text("Seguros El Zorro.")
    out_dir = tmp_path / "out"
    synth = FakeSynth()

    rendered = render_ads(scripts_dir, out_dir, synth)

    assert len(rendered) == 2
    assert {p.name for p in rendered} == {"mate-turbo.wav", "seguro-el-zorro.wav"}
    assert len(synth.calls) == 2


def test_render_ads_usa_el_texto_del_archivo_sin_espacios_de_mas(tmp_path: Path) -> None:
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    (scripts_dir / "uno.txt").write_text("  Texto con espacios raros.  \n")
    synth = FakeSynth()

    render_ads(scripts_dir, tmp_path / "out", synth)

    text, _ = synth.calls[0]
    assert text == "Texto con espacios raros."


def test_render_ads_ignora_archivos_que_no_son_txt(tmp_path: Path) -> None:
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    (scripts_dir / "uno.txt").write_text("Un guion.")
    (scripts_dir / "notas.md").write_text("no es un guion")
    synth = FakeSynth()

    rendered = render_ads(scripts_dir, tmp_path / "out", synth)

    assert len(rendered) == 1


def test_render_ads_sin_guiones_no_llama_a_sintetizar(tmp_path: Path) -> None:
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    synth = FakeSynth()

    rendered = render_ads(scripts_dir, tmp_path / "out", synth)

    assert rendered == []
    assert synth.calls == []


def test_render_ads_crea_out_dir_si_no_existe(tmp_path: Path) -> None:
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    (scripts_dir / "uno.txt").write_text("Un guion.")
    out_dir = tmp_path / "no-existe-todavia"

    render_ads(scripts_dir, out_dir, FakeSynth())

    assert out_dir.is_dir()

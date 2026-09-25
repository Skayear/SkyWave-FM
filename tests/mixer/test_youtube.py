import sys
import types

import pytest

from skywave.mixer.youtube import resolve_audio_url


class _YoutubeDLFalso:
    def __init__(self, info: dict | None, *, error: Exception | None = None) -> None:
        self._info = info
        self._error = error

    def __call__(self, opts: dict) -> "_YoutubeDLFalso":
        return self

    def __enter__(self) -> "_YoutubeDLFalso":
        return self

    def __exit__(self, *exc_info: object) -> None:
        pass

    def extract_info(self, url: str, download: bool) -> dict | None:
        if self._error is not None:
            raise self._error
        return self._info


def _fake_yt_dlp_module(youtube_dl: _YoutubeDLFalso) -> types.ModuleType:
    module = types.ModuleType("yt_dlp")
    module.YoutubeDL = youtube_dl  # type: ignore[attr-defined]
    return module


def test_resolve_audio_url_devuelve_la_url_de_media(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(
        sys.modules,
        "yt_dlp",
        _fake_yt_dlp_module(_YoutubeDLFalso({"url": "https://media.example/stream.m3u8"})),
    )

    assert (
        resolve_audio_url("https://youtube.com/watch?v=abc") == "https://media.example/stream.m3u8"
    )


def test_resolve_audio_url_sin_url_en_la_respuesta_explota(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "yt_dlp", _fake_yt_dlp_module(_YoutubeDLFalso({})))

    with pytest.raises(ValueError):
        resolve_audio_url("https://youtube.com/watch?v=abc")


def test_resolve_audio_url_propaga_errores_de_extraccion(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(
        sys.modules,
        "yt_dlp",
        _fake_yt_dlp_module(_YoutubeDLFalso(None, error=RuntimeError("video no disponible"))),
    )

    with pytest.raises(RuntimeError):
        resolve_audio_url("https://youtube.com/watch?v=abc")


def test_resolve_audio_url_sin_el_extra_instalado_da_un_mensaje_claro(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(sys.modules, "yt_dlp", None)  # como si el import fallara

    with pytest.raises(ImportError, match="extra 'relay'"):
        resolve_audio_url("https://youtube.com/watch?v=abc")

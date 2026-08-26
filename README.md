# SkyWave-FM

Radio online personal con locutor IA (en construcción). Escanea tu música,
arma la programación con rotación de artistas y sale al aire por
[Icecast2](https://icecast.org/) — escuchable desde un navegador o desde
Euro Truck Simulator 2.

Proyecto personal de aprendizaje de Python: el roadmap por fases y las
convenciones están en [CLAUDE.MD](CLAUDE.MD), y cada fase deja su bitácora
de decisiones en [docs/](docs/).

## Estado

- ✅ Fase 0 — Icecast2 en Docker
- ✅ Fase 1 — Librería musical (scanner, tags, SQLite, CLI)
- ✅ Fase 2 — Salir al aire (mixer ffmpeg → Icecast)
- ✅ Fase 3 — Programación (rotación, no-repetición, "sonando ahora")
- ✅ Fase 4 — El locutor (Piper TTS + guiones LLM con fallback)
- ⏳ Fase 5 — Mezcla de verdad (crossfade, ducking) — próxima

## Requisitos

- Python 3.12+ y [`uv`](https://docs.astral.sh/uv/)
- Docker (para Icecast2)
- `ffmpeg` en el host (`sudo apt install ffmpeg`)
- Para el locutor (opcional): la voz de Piper
  (`uv run python -m piper.download_voices --download-dir voices es_AR-daniela-high`)
  y [Ollama](https://ollama.com) con `ollama pull llama3.2:3b` para guiones
  con LLM — sin Ollama, el locutor usa plantillas; sin la voz, la radio
  sale sin locutor.

## Puesta en marcha

```bash
# 1. Configurar secretos (una sola vez)
cp .env.example .env        # completar con passwords reales

# 2. Levantar Icecast
docker compose up -d

# 3. Escanear tu música
uv run skywave scan ~/Music

# 4. Salir al aire (Ctrl+C para cortar)
uv run skywave play
```

Con la radio sonando, escuchala en `http://localhost:8010/sky.mp3`
(navegador, VLC, o ETS2 como emisora de streaming).

## Comandos

| Comando | Qué hace |
|---------|----------|
| `skywave scan <carpeta>` | Escanea recursivamente y guarda los tracks en SQLite |
| `skywave list` | Lista la biblioteca en una tabla |
| `skywave play` | Radio continua: rotación, locutor entre temas, hasta Ctrl+C |

Opciones útiles: `--db <archivo>` en todos (default `./skywave.db`);
`--mount <nombre>`, `--no-repeat-artist <N>` y `--sin-locutor` en `play`.

## Desarrollo

```bash
uv run pytest           # tests (lógica pura; el audio se prueba a mano)
uv run ruff check .     # lint
uv run ruff format .    # formato
```

El estado del trabajo se trackea en los
[issues y milestones](https://github.com/Skayear/SkyWave-FM/milestones) del
repo, un milestone por fase.

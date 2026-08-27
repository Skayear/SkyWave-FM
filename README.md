# SkyWave-FM

Radio online personal con locutor IA (en construcción). Escanea tu música,
arma la programación con rotación de artistas, presenta los temas con voz
sintetizada y sale al aire por [Icecast2](https://icecast.org/) —
escuchable desde un navegador, VLC o Euro Truck Simulator 2.

Proyecto personal de aprendizaje de Python: el roadmap por fases y las
convenciones están en [CLAUDE.MD](CLAUDE.MD), y cada fase deja su bitácora
de decisiones en [docs/](docs/).

## Estado

- ✅ Fase 0 — Icecast2 en Docker
- ✅ Fase 1 — Librería musical (scanner, tags, SQLite, CLI)
- ✅ Fase 2 — Salir al aire (mixer ffmpeg → Icecast)
- ✅ Fase 3 — Programación (rotación, no-repetición, "sonando ahora")
- ✅ Fase 4 — El locutor (Piper TTS + guiones LLM con fallback)
- ✅ Fase 5 — Mezcla de verdad (crossfade, ducking, pre-generación del guion)
- ✅ Fase 6 — Publicidades falsas (guiones curados + jingle + SFX, rotación)
- ⏳ Fase 7 — Web — próxima

## Cómo funciona

```
~/Music ──scan──▶ SQLite (tracks)
                     │
                     ▼
              scheduler (pick_next)          host (locutor)
              rotación + no-repetición       guion: Ollama ─fallback▶ plantillas
              bloques horarios                  │
                     │                          ▼
                     │                       voz: Piper ──▶ cache/ (WAV por hash)
                     ▼                          │
              mixer ◀───────────────────────────┘
              Decoder (ffmpeg -re, por pista) ──PCM──▶ Encoder (ffmpeg persistente)
                                                          │
                                                          ▼
                                                  Icecast2 (Docker) :8010/sky.mp3
                                                          │
                                              navegador / VLC / ETS2
```

El loop de `skywave play`, tema a tema:

1. **El scheduler elige** la próxima pista al azar entre las que su artista
   no sonó en los últimos N temas (regla que se relaja sola si la
   biblioteca es chica — la radio nunca se queda muda). De madrugada
   prefiere temas cortos. Esta elección pasa en **un hilo de fondo**
   mientras suena el tema actual, junto con el guion y la voz del punto
   siguiente — para cuando el tema termina, la próxima intervención ya
   está lista (nada de aire muerto generando en vivo).
2. Se actualiza la tabla **`now_playing`** en SQLite (la futura web lo lee
   de ahí).
3. **El locutor** escribe un guion corto (Ollama local; si falla o no
   está, plantillas fijas), lo convierte a voz con **Piper** (es_AR) y lo
   cachea en `cache/` por hash del texto — el mismo guion nunca se
   sintetiza dos veces.
4. **El mixer** decodifica voz y música a PCM crudo (un proceso
   `ffmpeg -re` por pista, a ritmo real). La voz del locutor suena sobre
   el arranque del tema entrante como colchón atenuado (**ducking**, con
   rampas suaves), y la cola de un tema se funde con el arranque del
   siguiente cuando no hay locutor de por medio (**crossfade**) — ambos
   con `numpy` sobre el PCM crudo. Todo se escribe al stdin de un
   `ffmpeg` **persistente** que re-codifica a mp3 128k contra Icecast. Ese
   proceso vive toda la sesión: la conexión no se corta entre temas.

Todo el audio interno es PCM s16le 44100Hz estéreo. Ctrl+C corta limpio:
limpia `now_playing` y no deja procesos huérfanos.

## Requisitos

| Qué | Para qué | Instalación |
|-----|----------|-------------|
| Python 3.12+ y [`uv`](https://docs.astral.sh/uv/) | todo | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| Docker | Icecast2 | — |
| `ffmpeg` | mixer (decodificar/codificar) | `sudo apt install ffmpeg` |
| Voz de Piper (~114MB) | locutor *(opcional)* | `uv run python -m piper.download_voices --download-dir voices es_AR-daniela-high` |
| [Ollama](https://ollama.com) + modelo (~2GB) | guiones con LLM *(opcional)* | `curl -fsSL https://ollama.com/install.sh \| sh && ollama pull llama3.2:3b` |

Los opcionales degradan con gracia: sin Ollama el locutor usa plantillas
fijas; sin la voz de Piper la radio sale sin locutor (avisando).

Las dependencias de Python (`mutagen`, `typer`, `piper-tts`, etc.) las
instala `uv` solo la primera vez que corras `uv run`.

## Puesta en marcha

```bash
# 1. Configurar secretos (una sola vez)
cp .env.example .env             # completar con passwords reales
./scripts/render-icecast-config.sh   # genera config/icecast.xml desde .env

# 2. Levantar Icecast
docker compose up -d

# 3. Escanear tu música
uv run skywave scan ~/Music

# 4. Salir al aire (Ctrl+C para cortar)
uv run skywave play
```

Con la radio sonando, escuchala en `http://localhost:8010/sky.mp3`
(navegador, VLC, o ETS2 como emisora de streaming). Desde otra PC de la
red: `http://<ip-de-esta-máquina>:8010/sky.mp3`.

### Variables de entorno (`.env`)

| Variable | Qué es |
|----------|--------|
| `ICECAST_SOURCE_PASSWORD` | Password con la que el mixer se conecta como fuente |
| `ICECAST_ADMIN_USER` / `ICECAST_ADMIN_PASSWORD` | Admin web de Icecast |
| `ICECAST_SERVER_HOST` | Host de Icecast (default `localhost`) |
| `ICECAST_SOURCE_PORT` | Puerto en el host (default `8010` — el 8000 estaba ocupado) |

Si cambiás `.env`, correr de nuevo `./scripts/render-icecast-config.sh` y
`docker compose up -d` (Icecast no relee su config solo).

## Comandos

| Comando | Qué hace |
|---------|----------|
| `skywave scan <carpeta>` | Escanea recursivamente (mp3/flac/ogg/m4a/wav), lee tags con mutagen y guarda en SQLite. Re-escanear actualiza, no duplica. |
| `skywave list` | Lista la biblioteca en una tabla (artista, título, año, álbum) |
| `skywave play` | Radio continua: rotación, locutor entre temas, publicidades, hasta Ctrl+C |
| `skywave render-ads` | Sintetiza a WAV las publicidades curadas a mano en `assets/ads/scripts/*.txt` (voz + colchón + stinger), a `assets/ads/*.wav` |

| Opción | Comandos | Qué hace |
|--------|----------|----------|
| `--db <archivo>` | todos | Archivo SQLite de la biblioteca (default `./skywave.db`) |
| `--mount <nombre>` | `play` | Punto de montaje en Icecast (default `sky.mp3`) |
| `--no-repeat-artist <N>` | `play` | Ventana de temas sin repetir artista (default 3) |
| `--sin-locutor` | `play` | Solo música, sin presentaciones |
| `--sin-publicidades` | `play` | Sin publicidades intercaladas |
| `--ads-every <N>` | `play` | Cada cuántos temas suena una publicidad (default 8) |
| `--scripts-dir <carpeta>` | `render-ads` | Carpeta con los guiones `.txt` curados (default `assets/ads/scripts`) |
| `--out-dir <carpeta>` | `render-ads` | Carpeta donde se escriben los WAV (default `assets/ads`) |

Si un track no tiene tags (pasa con los `.wav`), el título y el artista se
deducen de la carpeta (`Artista - Álbum/NN - Título.wav`).

## Desarrollo

```bash
uv run pytest           # tests (lógica pura; el audio se prueba a mano)
uv run ruff check .     # lint
uv run ruff format .    # formato
```

Estructura: `src/skywave/` con un subpaquete por componente — `library/`
(scanner, tags, SQLite), `scheduler/` (qué suena, rotación de temas y
publicidades), `host/` (el locutor), `mixer/` (audio a Icecast), `ads/`
(curar y producir publicidades), `web/` (Fase 7, vacío aún).

El estado del trabajo se trackea en los
[issues y milestones](https://github.com/Skayear/SkyWave-FM/milestones) del
repo, un milestone por fase. Las decisiones de diseño de cada fase están
en su bitácora dentro de [docs/](docs/).

## Documentación de las tecnologías

**Python**
- [Python (stdlib)](https://docs.python.org/3/) — `pathlib`, `sqlite3`,
  `subprocess`, `dataclasses`, `threading`, todo lo que no es una dependencia
- [uv](https://docs.astral.sh/uv/) — gestor de paquetes y proyecto
- [ruff](https://docs.astral.sh/ruff/) — lint + formato
- [pytest](https://docs.pytest.org/)

**CLI y librería musical**
- [typer](https://typer.tiangolo.com/) — la CLI (`skywave scan/list/play`)
- [rich](https://rich.readthedocs.io/) — tablas y salida de consola
- [mutagen](https://mutagen.readthedocs.io/) — lectura de tags de audio
- [python-dotenv](https://github.com/theskumar/python-dotenv) — carga de `.env`

**Streaming y audio**
- [Icecast2](https://icecast.org/docs/) — servidor de streaming
- [ffmpeg](https://ffmpeg.org/documentation.html) — decodificar/codificar
  audio (`mixer/encoder.py`, `mixer/decoder.py`)
- [Docker Compose](https://docs.docker.com/compose/) — levanta Icecast
- [NumPy](https://numpy.org/doc/) — arrays de PCM (Fase 5: crossfade, ducking)

**El locutor**
- [Piper](https://github.com/rhasspy/piper) — TTS local
- [Ollama](https://github.com/ollama/ollama/blob/main/docs/api.md) — API
  local de LLM para los guiones

**Más adelante en el roadmap**
- [FastAPI](https://fastapi.tiangolo.com/) — la web (Fase 7)
- [Tailscale](https://tailscale.com/kb) — acceso remoto sin exponer a
  internet (Fase 8)
- [Prometheus](https://prometheus.io/docs/) /
  [Grafana](https://grafana.com/docs/) — métricas y dashboard (Fase 8)

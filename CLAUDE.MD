# SkyWave FM

Radio online personal con locutor IA. Proyecto de aprendizaje: el objetivo
**doble** es (a) tener una radio funcional y (b) que yo aprenda Python de verdad.

## Cómo quiero que trabajes conmigo

- **Estoy aprendiendo Python.** Vengo de SRE/DevOps: sé mucho de infra (AWS,
  Kubernetes, Terraform, Docker, observabilidad) y nada de Python idiomático.
  No hace falta que me expliques qué es un contenedor. Sí explicame decisiones
  de Python: por qué un dataclass y no un dict, cuándo asyncio y cuándo threads,
  qué es un context manager, etc.
- **No escribas features enteras de una.** Preferí pasos chicos que yo pueda
  leer, entender y correr. Si un cambio toca más de 2-3 archivos, proponé el
  plan primero.
- **Explicá el "por qué", no solo el "qué".** Un comentario de una línea sobre
  la decisión de diseño vale más que diez comentarios describiendo el código.
- Hablame en **español**.
- Preferí soluciones concretas y ejecutables sobre abstracciones prematuras.

## Stack

- Python 3.12+, gestionado con `uv`
- **Icecast2** como servidor de streaming (en Docker)
- **ffmpeg** para decodificar/codificar audio (via `subprocess`)
- **mutagen** para leer tags ID3/FLAC
- **numpy** para mezcla de audio (crossfade, ducking)
- **SQLite** para la biblioteca musical y la cola de saludos
- **Piper** para TTS local (voz en español, `es_AR-daniela` o similar)
- **FastAPI** para la web (reproductor + "sonando ahora" + text box de saludos)
- **typer** para la CLI
- **ruff** (lint + format) y **pytest**
- LLM para los guiones del locutor: interfaz común con dos implementaciones
  intercambiables (Ollama local / API de Claude)

## Arquitectura

Cinco componentes, cada uno un subpaquete de `skywave/`:

1. **`library/`** — escanea la carpeta de música, lee tags con mutagen, guarda
   en SQLite. Opcionalmente enriquece con MusicBrainz (año, sello, país).
2. **`scheduler/`** — decide qué suena: rotación, no repetir artista en X temas,
   bloques por hora, cuándo entra un aviso o un saludo.
3. **`host/`** (el locutor) — recibe metadata del tema que termina y del que
   arranca, genera un guion corto con el LLM, lo convierte a voz con Piper,
   cachea el WAV por hash del texto. **Siempre** con fallback a plantillas
   si el LLM falla: la radio nunca se queda muda.
4. **`mixer/`** — el corazón. Mantiene un proceso ffmpeg abierto empujando a
   Icecast y le escribe PCM crudo a ritmo real:

   ```
   ffmpeg -f s16le -ar 44100 -ac 2 -i pipe:0 \
     -c:a libmp3lame -b:a 128k -content_type audio/mpeg \
     -f mp3 icecast://source:PASS@localhost:8000/sky.mp3
   ```

   Como controlamos los bytes, la mezcla (crossfade, ducking de la música bajo
   la voz) es suma de arrays de numpy.
5. **`web/`** — FastAPI: `/now-playing`, página con reproductor `<audio>`,
   text box de saludos que encola en SQLite, WebSocket para actualizar en vivo.

## Decisiones ya tomadas (no re-discutir salvo que yo lo pida)

- **Streaming:** Icecast2, no HLS. Tiene que consumirlo Euro Truck Simulator 2
  además del navegador.
- **Acceso restringido vía Tailscale.** Icecast escucha solo en la tailnet.
  Uso estrictamente personal, música digitalizada de mis propios discos.
  Nada de exposición pública, nada de listado público de mounts.
  Evitar HTTP Basic Auth: ETS2 no lo maneja bien.
- **TTS local con Piper**, no servicios pagos.
- **Publicidades falsas estilo GTA:** se generan y curan una sola vez a mano,
  se renderizan a WAV en `assets/ads/` y el scheduler las rota. **No** se
  generan en vivo.
- Todo el audio se maneja como PCM s16le 44100Hz estéreo internamente.

## Roadmap

Trabajamos fase por fase. No adelantes fases sin que yo lo pida.

- [x] **Fase 0 — Base:** repo, `uv`, estructura de paquete, ruff + pytest,
      Docker Compose con Icecast2 andando y probado con un MP3 cualquiera.
- [x] **Fase 1 — Librería musical:** scanner recursivo, lectura de tags,
      modelo `Track`, persistencia SQLite, CLI (`skywave scan`, `skywave list`).
      *Aprendo: pathlib, dataclasses, sqlite3, typer.*
- [x] **Fase 2 — Salir al aire:** mixer que abre ffmpeg contra Icecast,
      decodifica una pista a PCM y la escribe a ritmo real; encadenar pistas
      sin silencio. **Hito: que suene en ETS2 y en el navegador.**
      *Aprendo: subprocess, bytes/buffers, threading.*
      (Navegador confirmado; ETS2 todavía sin probar — ver docs/fase-2-salir-al-aire.md.)
- [ ] **Fase 3 — Programación:** cola con rotación, regla de no-repetición,
      bloques horarios, estado "sonando ahora".
- [ ] **Fase 4 — El locutor:** wrapper de Piper, cache en disco por hash,
      generador de guiones con LLM (metadata + hora + qué viene después),
      plantillas de fallback. *Aprendo: APIs, cache, manejo de errores.*
- [ ] **Fase 5 — Mezcla de verdad:** crossfade, ducking, colchón musical bajo
      la voz. *Aprendo: numpy, audio básico.*
- [ ] **Fase 6 — Publicidades falsas:** guiones curados + jingle + SFX,
      insertadas en la rotación.
- [ ] **Fase 7 — Web:** FastAPI, reproductor, text box de saludos, moderación
      básica + rate limit, WebSocket. *Aprendo: async, pydantic, FastAPI.*
- [ ] **Fase 8 — Producción:** Dockerizar, desplegar en el homelab k3s,
      métricas Prometheus (oyentes, pistas/hora, latencia TTS, errores LLM),
      dashboard en Grafana. *Acá estoy en mi terreno.*

## Convenciones

- Type hints en todo. `ruff check` y `ruff format` antes de cerrar cualquier cambio.
- Tests con pytest para la lógica pura (scheduler, parseo de metadata).
  El audio y el streaming se prueban a mano.
- Config en `config.toml` + variables de entorno para secretos.
  **Nunca** commitear la password de Icecast ni API keys.
- Nada de música ni WAVs generados en el repo: `.gitignore` para
  `library/`, `cache/`, `assets/ads/*.wav`.
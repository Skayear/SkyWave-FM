# Fase 3 — Programación

Objetivo de la fase: que la radio decida qué suena — rotación con
no-repetición de artista, bloques horarios, estado "sonando ahora" — en vez
de recorrer la biblioteca en orden una sola vez. **Cerrada** — los 4 issues
del milestone [Fase 3 —
Programación](https://github.com/Skayear/SkyWave-FM/milestone/4) están
resueltos y el milestone está cerrado.

## Qué se hizo

### 1. Selector con rotación (issue [#11](https://github.com/Skayear/SkyWave-FM/issues/11))

`src/skywave/scheduler/selector.py` — `pick_next(catalog, history, ...)`:
elige al azar entre los tracks cuyo artista no sonó en los últimos N temas.

Decisiones detrás:

- **Lógica pura, sin I/O.** Recibe `list[Track]` y devuelve `Track`; nada
  de ffmpeg ni SQLite adentro. Es exactamente la parte que las convenciones
  del proyecto piden testear con pytest — y se puede, sin sonido.
- **El azar se inyecta** (`rng: random.Random` como parámetro) en vez de
  usar el módulo `random` global: los tests pasan `random.Random(seed)` y
  son determinísticos; producción omite el parámetro y usa azar real. Es el
  mismo patrón que se repite después con el reloj.
- **La regla se relaja sola.** Si ningún track califica (biblioteca chica,
  ventana grande), la ventana se achica de a uno en vez de fallar; en la
  última relajación al menos evita repetir el mismo tema exacto. Principio
  rector: la radio nunca se queda muda por una regla.
- **Gotcha de Python documentado en el código:** `history[-0:]` no es la
  lista vacía sino la lista entera (el slice `-0` equivale a `0`), así que
  el caso ventana=0 se maneja aparte.

Validado también contra el catálogo real: 20 pasadas simuladas, cero
violaciones de la ventana.

### 2. Estado "sonando ahora" (issue [#12](https://github.com/Skayear/SkyWave-FM/issues/12))

Tabla `now_playing` en el mismo SQLite, con la restricción de "una sola
fila" forzada a nivel de esquema (`id INTEGER PRIMARY KEY CHECK (id = 1)`)
— no depende de que el código se porte bien. Guarda solo `path` (la
identidad del track) + `started_at`; el resto sale con un JOIN contra
`tracks`, sin duplicar datos que podrían quedar desactualizados.

`started_at` se guarda como texto ISO-8601 en UTC — SQLite no tiene tipo de
fecha nativo, y el formato ISO ordena bien lexicográficamente y se parsea
con `datetime.fromisoformat()`. El timestamp es inyectable para tests.

En Fase 7, la web va a leer este estado para el "sonando ahora" de la
página.

### 3. Radio continua (issue [#13](https://github.com/Skayear/SkyWave-FM/issues/13))

`skywave play` ahora es un loop infinito: pide pista al selector, actualiza
`now_playing`, la reproduce con el mismo `Encoder` de punta a punta, y
repite hasta Ctrl+C. El corte es limpio: se limpia `now_playing` en un
`finally` (mejor ninguna fila que una vieja mintiendo) y no queda ningún
proceso ffmpeg huérfano.

Detalle de señales que apareció en la prueba: con Ctrl+C, el ffmpeg hijo
recibe el mismo SIGINT que el proceso Python (comparten el process group de
la terminal) y puede morir *antes* — cerrar su stdin entonces tira
`BrokenPipeError`, que `Encoder.close()` ahora ignora porque el objetivo
(que ffmpeg termine) ya se cumplió.

### 4. Bloques horarios, versión mínima (issue [#14](https://github.com/Skayear/SkyWave-FM/issues/14))

`pick_next()` acepta `now: datetime` inyectable (mismo patrón que el rng) y
filtra el catálogo por franja antes de la ventana de artista. Única regla
concreta por ahora: de madrugada (0-5h) se prefieren temas de hasta 4
minutos; si no hay ninguno, la regla se ignora.

Deliberadamente mínimo: la interfaz queda preparada, pero configurar
bloques por género/franja necesita metadata que la biblioteca todavía no
tiene. Se profundiza cuando crezca.

## Ajustes no anticipados

- **El fallback de Fase 1 confunde álbum con artista en carpetas
  anidadas.** La simulación con el catálogo real mostró a "Rust In Peace"
  (un álbum de Megadeth) como *artista*: esos archivos están en
  `Megadeth/Rust In Peace/` sin tags, y el fallback solo mira la carpeta
  inmediata. Anotado como mejora futura del fallback (reconocer estructura
  `Artista/Álbum/`), no bloqueaba esta fase. **Arreglado el 2026-08-27**
  — el bug salió a la luz al aire, en un guion del locutor que decía "de
  Rust In Peace" — ver `Track.from_tags(..., root=...)` en
  `library/track.py`.

## Para estudiar antes de Fase 4

Fase 4 (el locutor) introduce:

- **Piper TTS** por línea de comandos y cómo envolverlo desde Python.
- **Cache en disco por hash**: `hashlib` para derivar la clave del texto
  del guion, y el patrón "si el WAV ya existe, no regenerar".
- **APIs de LLM con fallback**: interfaz común con dos implementaciones
  (Ollama local / API de Claude) y plantillas fijas si el LLM falla — la
  radio nunca se queda muda, otra vez.

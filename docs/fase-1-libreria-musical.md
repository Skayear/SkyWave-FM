# Fase 1 — Librería musical

Objetivo de la fase: escanear la carpeta de música, leer tags con `mutagen`,
guardar todo en SQLite (modelo `Track`) y exponerlo por CLI (`skywave scan`,
`skywave list`). **Cerrada** — los 5 issues del milestone [Fase 1 — Librería
musical](https://github.com/Skayear/SkyWave-FM/milestone/2) están resueltos y
el milestone está cerrado.

## Qué se hizo

### 1. Scanner recursivo (issue [#2](https://github.com/Skayear/SkyWave-FM/issues/2))

`src/skywave/library/scanner.py` — `find_audio_files(root: Path) -> Iterator[Path]`.

Dos decisiones de Python detrás de esta función:

- **Generador (`yield`) en vez de `list[Path]`.** Una carpeta de música puede
  tener miles de archivos. Con un generador el caller puede empezar a
  procesar el primer resultado sin esperar a que termine de recorrer todo el
  disco, y nunca tenemos la lista completa en memoria a la vez.

- **`Path.walk()` en vez de `Path.rglob("*")`.** `rglob` es más directo pero
  no se puede podar: baja a *todas* las subcarpetas sí o sí. `Path.walk()`
  (nuevo en 3.12, mismo patrón que el clásico `os.walk` pero con objetos
  `Path`) devuelve `(dirpath, dirnames, filenames)` en cada paso, y como
  `dirnames` es una lista mutable, sacarle entradas antes de que el walk siga
  evita bajar a esas carpetas. Lo usamos para ignorar carpetas ocultas
  (`.algo`) y `@eaDir` — la carpeta de miniaturas que un NAS Synology crea en
  cada directorio (no empieza con punto, así que hay que filtrarla por
  nombre explícito).

Extensiones reconocidas (case-insensitive vía `.suffix.lower()`):
`.mp3`, `.flac`, `.ogg`, `.m4a`, `.wav`.

Tests en `tests/library/test_scanner.py`, usando el fixture `tmp_path` de
pytest para armar árboles de carpetas descartables en vez de commitear
archivos de audio de prueba al repo.

### 2. Lectura de tags con mutagen (issue [#3](https://github.com/Skayear/SkyWave-FM/issues/3))

`src/skywave/library/tags.py` — `read_tags(path: Path) -> dict[str, Any]`.

Usa `mutagen.File(path, easy=True)` en vez de las clases específicas por
formato (`EasyID3`, Vorbis comments de FLAC, etc.). El modo "easy" normaliza
tags de formatos distintos bajo las mismas claves (`artist`, `title`,
`album`, `date`) — sin esto habría que manejar ID3 de mp3 y Vorbis comments
de FLAC por separado, con claves internas distintas. La duración
(`audio.info.length`) sale igual sin importar el modo easy.

Tags ausentes o parciales quedan en `None`, no revientan — probado con
fixtures sintéticas de 1 segundo de silencio generadas con un contenedor
`ffmpeg` descartable (mismo patrón que la prueba end-to-end de Icecast en
Fase 0; seguimos sin `ffmpeg` en el host).

### 3. Modelo Track (issue [#4](https://github.com/Skayear/SkyWave-FM/issues/4))

`src/skywave/library/track.py` — `Track` (`@dataclass(frozen=True, slots=True)`)
con `Track.from_tags(path, tags)` como constructor.

- **`frozen=True`:** un `Track` representa un hecho fijado en el momento del
  escaneo (no algo que se edite en memoria), y de paso lo hace hashable
  gratis — útil el día que el scheduler necesite un `set[Track]` para la
  regla de no-repetición (Fase 3).
- **`slots=True`:** menos memoria por instancia y evita agregar atributos
  sueltos por accidente. No es parte de lo que pide el issue, pero es
  prácticamente gratis en un dataclass que no necesita herencia.

Si `mutagen` no trae `artist`/`title`/`album`, `from_tags` cae a parsear la
carpeta (`"Artista - Álbum"`) y el nombre de archivo (`"NN - Título"`). No
hay fallback razonable para `year`: si no hay tag `date`, queda `None`.

### 4. Persistencia en SQLite (issue [#5](https://github.com/Skayear/SkyWave-FM/issues/5))

`src/skywave/library/db.py` — `connect()`, `upsert_track()`, `list_tracks()`,
con `sqlite3` de la librería estándar, sin ORM.

- **Upsert con `INSERT ... ON CONFLICT(path) DO UPDATE`** en vez de
  `INSERT OR REPLACE`: actualiza la fila existente en lugar de borrarla y
  recrearla — importa el día que algo más referencie esa fila por `rowid`.
  `path` es la clave natural (es la identidad del archivo en disco).
- **`upsert_track()` no hace `commit()`.** Decisión deliberada: quien
  orquesta el escaneo controla el alcance de la transacción. Envolver un
  escaneo completo en un solo `with conn:` significa un commit atómico al
  final, no uno por archivo.

### 5. CLI con typer (issue [#6](https://github.com/Skayear/SkyWave-FM/issues/6))

`src/skywave/cli.py` — `skywave scan <carpeta>` y `skywave list`, colgado del
entry point `skywave` ya configurado en `pyproject.toml`
(`src/skywave/__init__.py:main()` ahora llama a la app de typer).

`skywave list` usa `rich.table.Table` para la salida — `rich` llega como
dependencia transitiva de `typer`, pero se declaró explícita en
`pyproject.toml` porque el código la importa directo (no conviene depender
de una transitiva que el propio `typer` podría dejar de traer). Sin
`config.toml` todavía, `--db` es una opción explícita por comando
(default `./skywave.db` en el directorio actual).

## Ajustes no anticipados

- **Bug de `.gitignore` que se comía `src/skywave/library/`.** La regla
  `library/` (pensada para ignorar la carpeta de música real en la raíz del
  repo, nunca subida) no tenía barra inicial, así que en git eso significa
  "ignorá cualquier carpeta llamada `library` en cualquier nivel del árbol"
  — incluyendo el subpaquete de Python `src/skywave/library/`. El síntoma
  fue que `git status` decía "nothing to commit" con `scanner.py` recién
  creado. Se corrigió anclando la regla a la raíz (`/library/`, `/cache/`).
  Efecto colateral: `src/skywave/library/__init__.py` tampoco se había
  commiteado nunca, ni en el commit inicial del repo — quedó trackeado recién
  en Fase 1.

- **El fallback de título en `Track` no contemplaba todos los formatos de
  nombre de archivo reales.** Probar contra los 111 archivos de `~/Music`
  (no solo fixtures sintéticas) encontró dos patrones que el regex original
  no cubría: `"14 Título.wav"` sin guion (REO Speedwagon The Hits) y
  `"5-11 Título.wav"` con prefijo disco-pista (un rip tipo box set de
  Electric Light Orchestra). Los dos quedaron cubiertos con tests de
  regresión antes de cerrar el issue #4.

## Para estudiar antes de Fase 2

Fase 2 (salir al aire) va a introducir:

- **`subprocess`**: el mixer va a abrir un proceso `ffmpeg` de larga
  duración y escribirle PCM crudo por stdin en tiempo real — distinto a
  correr un comando y esperar a que termine.
- **bytes/buffers**: trabajar con audio como bytes crudos (PCM s16le),
  no como abstracciones de alto nivel.
- **threading**: mientras un hilo empuja audio al proceso ffmpeg, otra
  parte de la app tiene que poder seguir respondiendo (web, scheduler).

También hace falta instalar `ffmpeg` en el host antes de Fase 2 — hasta
ahora todo se probó con un contenedor descartable.

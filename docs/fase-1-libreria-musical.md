# Fase 1 — Librería musical

Objetivo de la fase: escanear la carpeta de música, leer tags con `mutagen`,
guardar todo en SQLite (modelo `Track`) y exponerlo por CLI (`skywave scan`,
`skywave list`).

A diferencia de `fase-0-base.md` (que se escribió cuando la fase ya estaba
cerrada), este archivo se va completando a medida que avanza la fase. El
estado tarea por tarea (qué falta, quién la agarra) vive en los issues del
milestone [Fase 1 — Librería
musical](https://github.com/Skayear/SkyWave-FM/milestone/2) en GitHub — acá
solo quedan las decisiones y el "por qué" de lo que ya está hecho.

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
  ahora.

## Para estudiar antes de la próxima tarea

La próxima tarea (issue [#3](https://github.com/Skayear/SkyWave-FM/issues/3),
lectura de tags con `mutagen`) va a mostrar cómo `mutagen` normaliza (o no)
metadata entre formatos distintos — ID3 de mp3 vs Vorbis comments de FLAC no
usan las mismas claves internamente.

# Fase 0 — Base

Objetivo de la fase: dejar el repo con estructura de paquete, herramientas de
calidad (`ruff`, `pytest`) y Icecast2 corriendo y probado con un MP3 cualquiera.

## Qué se hizo

### 1. `uv` como gestor de proyecto

Se instaló con el instalador oficial (`curl -LsSf https://astral.sh/uv/install.sh | sh`),
que lo deja en `~/.local/bin`.

`uv` reemplaza tres herramientas que en Python solías usar por separado:
`pip` (instalar paquetes), `venv` (crear el entorno virtual) y algo como
`poetry` (manejar `pyproject.toml` y el lockfile). Es un solo binario en Rust,
mucho más rápido, y **crea el venv solo** la primera vez que corrés `uv run`
o `uv add` — no hay que acordarse de activar nada a mano.

Comandos que vas a usar seguido:

```bash
uv add <paquete>          # agrega una dependencia y actualiza uv.lock
uv add --dev <paquete>    # dependencia solo de desarrollo (ruff, pytest)
uv run <comando>          # corre algo dentro del venv del proyecto
uv run python             # un intérprete con el proyecto instalado
```

### 2. `pyproject.toml`

Se generó con `uv init --app --package --name skywave --python 3.12`. Vale la
pena entender cada sección porque es el archivo de configuración central de
cualquier proyecto Python moderno (reemplaza al viejo `setup.py`):

- **`[project]`**: metadata (nombre, versión, `requires-python`) y
  `dependencies` (las de producción — todavía vacía).
- **`[project.scripts]`**: define el comando `skywave` que se va a instalar
  cuando el paquete se instale (`skywave = "skywave:main"` → ejecuta la
  función `main()` de `src/skywave/__init__.py`). Esto es lo que en Fase 1
  va a hacer que `skywave scan` y `skywave list` funcionen como comandos de
  terminal en vez de `python -m algo`.
- **`[build-system]`**: qué herramienta sabe empaquetar este proyecto
  (`uv_build`, el build backend propio de `uv`).
- **`[dependency-groups]` → `dev`**: dependencias que *no* van a producción
  (`ruff`, `pytest`). Es el reemplazo moderno y estandarizado (PEP 735) de lo
  que otras herramientas llamaban `dev-dependencies` o `extras`.
- **`[tool.ruff]`** y **`[tool.pytest.ini_options]`**: cada herramienta que
  soporta `pyproject.toml` guarda su config bajo `[tool.<nombre>]`, para no
  necesitar un archivo de config aparte por herramienta.

### 3. Layout `src/`

`uv init --package` creó `src/skywave/` en vez de un `skywave/` suelto en la
raíz. Esto se llama **src-layout** y es la convención recomendada para
cualquier paquete que se vaya a instalar (a diferencia de un script suelto):
obliga a que los tests corran contra el paquete *instalado* en el venv, no
contra los archivos del repo por accidente de que estén en el mismo
directorio. Evita una clase entera de bugs de "me funciona en local pero no
instalado".

Dentro, los 5 subpaquetes de la arquitectura, cada uno con su `__init__.py`
vacío por ahora:

```
src/skywave/
├── __init__.py      # define main(), el entry point de la CLI
├── library/
├── scheduler/
├── host/
├── mixer/
└── web/
```

Un paquete en Python es, ni más ni menos, una carpeta con `__init__.py`
adentro (aunque esté vacío) — eso es lo que le dice a Python "esto se puede
importar como `skywave.library`".

### 4. `ruff` y `pytest`

`ruff` hace dos cosas que en otros lenguajes son herramientas separadas:
linter (encuentra errores/malas prácticas) y formatter (como `gofmt` o
`prettier`). Reglas elegidas en `[tool.ruff.lint].select`:

| Código | Qué chequea |
|--------|-------------|
| `E`, `F` | Errores de estilo (pep8) y errores reales (pyflakes) — imports sin usar, variables no definidas |
| `I`      | Orden de imports |
| `UP`     | Sugiere sintaxis moderna de Python (`pyupgrade`) |
| `B`      | Bugs comunes y "gotchas" (`flake8-bugbear`) |

```bash
uv run ruff check .     # lint
uv run ruff format .    # formatea
uv run pytest           # corre tests (testpaths = ["tests"], que todavía no existe)
```

### 5. Icecast2 en Docker Compose

`docker-compose.yml` usa la imagen `deepcomp/icecast2`, que permite
configurar usuario/passwords por variables de entorno en vez de tener que
montar un `icecast.xml` a mano. Las passwords están en `.env` (gitignoreado)
y `.env.example` queda como plantilla commiteada — así el repo nunca tiene un
secreto real, pero cualquiera sabe qué variables necesita definir.

Puerto: el default de Icecast es 8000, pero en esta máquina ya lo usa un
contenedor de `portainer` que estaba corriendo. Se mapeó **8010→8000** en
`docker-compose.yml` (el contenedor sigue escuchando en su 8000 interno, solo
cambia cómo se accede desde el host).

### 6. Prueba end-to-end

Como `ffmpeg` todavía no está instalado en el host (lo vas a necesitar recién
en Fase 2, para el mixer), la prueba se hizo con un contenedor `ffmpeg`
descartable:

1. Generar un tono de prueba: `ffmpeg -f lavfi -i "sine=frequency=440:duration=15" ...`
2. Empujarlo a Icecast como si fuera una fuente en vivo, con el protocolo
   `icecast://usuario:password@host:puerto/punto-de-montaje`:
   ```
   ffmpeg -re -i test.mp3 -c:a libmp3lame -b:a 128k \
     -content_type audio/mpeg -f mp3 \
     icecast://source:PASSWORD@icecast:8000/test.mp3
   ```
3. Mientras corría, se confirmó con `curl http://127.0.0.1:8010/status-json.xsl`
   que Icecast veía la fuente activa, y se descargaron bytes del mount
   (`curl http://127.0.0.1:8010/test.mp3`) para confirmar que era un MP3
   válido y reproducible — exactamente lo que haría un navegador o ETS2.

Esto separa dos roles que vas a ver de nuevo en Fase 2: **source** (quien
empuja audio a Icecast, en el futuro el propio `mixer/` de skywave vía
`subprocess`) y **listener** (quien lo consume, un navegador/ETS2/`curl`).

## Ajustes no anticipados

- Puerto 8000 ocupado por `portainer` → Icecast quedó en 8010 en el host.
- `ffmpeg` no instalado en el host todavía → falta antes de Fase 2.

## Para estudiar antes de Fase 1

Fase 1 (librería musical) va a introducir:

- **`pathlib`**: la forma moderna de manejar rutas de archivos en Python (en
  vez de `os.path.join` con strings). Vas a recorrer la carpeta de música
  con esto.
- **`dataclasses`**: para el modelo `Track`. Vale la pena entender *por qué*
  un `dataclass` y no un dict suelto o una tupla — la diferencia es
  tipado explícito + métodos autogenerados (`__init__`, `__eq__`, `__repr__`)
  sin escribirlos a mano. Te lo voy a explicar en el momento con el código
  real delante.
- **`sqlite3`**: viene en la librería estándar de Python, no hay que instalar
  nada. Es una base de datos completa en un solo archivo.
- **`typer`**: para que `skywave scan` y `skywave list` sean subcomandos de
  una CLI real, usando los `[project.scripts]` que ya está configurado.

Si querés adelantar lectura por tu cuenta antes de que lleguemos ahí, esos
cuatro nombres son el mejor punto de partida.

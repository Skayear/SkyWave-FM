# Fase 7 — Web

Objetivo de la fase: una web mínima para escuchar la radio desde el
navegador sin tocar la URL de Icecast a mano, ver qué está sonando en
vivo, y dejar un saludo. **En progreso** — milestone [Fase 7 —
Web](https://github.com/Skayear/SkyWave-FM/milestone/8), 4 issues
(#29-#32).

## Qué se hizo

### 1. Esqueleto FastAPI + `/now-playing` (issue [#29](https://github.com/Skayear/SkyWave-FM/issues/29))

Nuevo paquete `src/skywave/web/`. `app.py` define la app FastAPI y
`GET /now-playing`, que lee directo de la tabla `now_playing` que ya
persiste Fase 3 (`db.get_now_playing()`) — no hay estado nuevo, la web es
un lector de lo que la radio ya escribe.

Dos decisiones chicas, ambas con precedente en el resto del proyecto:

- **La radio apagada no es un error.** Si `get_now_playing()` devuelve
  `None` (biblioteca vacía o `skywave play` no está corriendo), el
  endpoint devuelve `null` con 200 en vez de un 404 o un 500 — mismo
  principio de "nunca se queda muda" aplicado a un endpoint en vez de al
  audio.
- **La ruta de la base es una dependencia inyectable de FastAPI
  (`Depends(get_db_path)`), no una constante importada a mano.** Mismo
  espíritu que el `Callable` inyectado de `VoiceCache` o el `rng`/`now`
  de `pick_next` — acá aplicado con el mecanismo propio de FastAPI en vez
  de un parámetro de función común, así los tests apuntan a un
  `tmp_path` con `app.dependency_overrides` en vez de tocar
  `skywave.db` de verdad.

Todavía no hay un subcomando `skywave serve` — se levanta directo con
`uv run uvicorn skywave.web.app:app --reload` (ver README). No estaba en
el alcance del issue y no hacía falta para probarlo a mano; se puede
agregar más adelante si se vuelve incómodo.

Probado con `TestClient` (biblioteca vacía, tema sonando, biblioteca con
temas pero radio apagada) y a mano contra el `skywave.db` real con
`skywave play` corriendo al mismo tiempo.

## Ajustes no anticipados

- `ruff`'s `B008` marca `Depends(...)` como default de argumento como
  sospechoso (en general, una llamada mutable en un default es un bug) —
  pero es el idiom explícito de FastAPI para inyección de dependencias,
  no el error que la regla busca. Silenciado con un
  `per-file-ignores` en `pyproject.toml` acotado a `src/skywave/web/*.py`,
  no global.
- El `TestClient` de FastAPI tira un `StarletteDeprecationWarning`
  avisando que el uso de `httpx` para tests está deprecado a favor de un
  paquete `httpx2` — a la fecha, `httpx2` ni siquiera está publicado
  todavía. No se persigue por ahora (mismo criterio que el warning de HF
  Hub sin autenticar en Fase 4): no rompe nada, y perseguir un paquete
  que no existe públicamente sería prematuro.

## Para estudiar antes de seguir con #30

Servir HTML/templates con Jinja2 desde FastAPI, y la diferencia entre
devolver JSON (esto) y servir una página completa.

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

### 2. Página con reproductor (issue [#30](https://github.com/Skayear/SkyWave-FM/issues/30))

`GET /` sirve `templates/index.html` (Jinja2, vía `Jinja2Templates` de
FastAPI) con un `<audio>` apuntando al mount de Icecast. La URL del
stream se arma con las mismas variables de entorno que ya usa
`cli._icecast_url` (`ICECAST_SERVER_HOST`, `ICECAST_SOURCE_PORT`), pero
sin password: es la URL que escucha un navegador, no la del source que
empuja el mixer. Se expone como una dependencia (`get_stream_url`),
mismo patrón que `get_db_path`.

El "sonando ahora" **no** se rellena server-side al armar la página —
la propia página pide `/now-playing` por JS al cargar y cada 10s
después, reusando el endpoint del issue anterior en vez de duplicar la
lógica de lectura de `now_playing`. Sin frameworks de frontend: un
`fetch` + `textContent` alcanza.

Decisión chica: el JS usa `textContent`, no `innerHTML`, para pintar
título/artista. Vienen de tags de audio (mutagen) — no son HTML de
confianza, y `innerHTML` con datos externos es el patrón clásico de XSS.
Barato de hacer bien desde el arranque.

Probado con `TestClient` (que la página devuelva HTML con el `<audio>`
y una referencia a `/now-playing`) y a mano en el navegador con
`skywave play` corriendo: se escucha el stream y el tema actual se ve y
se actualiza.

## Ajustes no anticipados

- Los issues #30, #31 y #32 aparecieron cerrados en GitHub el
  2026-08-28 con comentarios que describían el trabajo como terminado
  y citaban commits (`34b46d8`, `317b938`, `9390fb5`) que **no existen**
  en ningún lado del repo (ni local, ni `origin`, ni ramas, ni objetos
  sueltos) — tampoco había código correspondiente (`templates/`,
  `greetings.py`, ruta `/ws` no existían). Todo indica que una sesión
  de IA anterior alucinó haber completado la fase y cerró los issues
  sin commitear nada. Se reabrieron los tres el 2026-08-28 antes de
  retomar #30 de verdad.

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

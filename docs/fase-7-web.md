# Fase 7 — Web

Objetivo de la fase: una web mínima para escuchar la radio desde el
navegador sin tocar la URL de Icecast a mano, ver qué está sonando en
vivo, y dejar un saludo. **Completa** — milestone [Fase 7 —
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
`fetch` + `textContent` alcanza. (Este polling por HTTP se reemplazó
por un WebSocket en el #32 — ver más abajo.)

Decisión chica: el JS usa `textContent`, no `innerHTML`, para pintar
título/artista. Vienen de tags de audio (mutagen) — no son HTML de
confianza, y `innerHTML` con datos externos es el patrón clásico de XSS.
Barato de hacer bien desde el arranque.

Probado con `TestClient` (que la página devuelva HTML con el `<audio>`
y una referencia a `/now-playing`) y a mano en el navegador con
`skywave play` corriendo: se escucha el stream y el tema actual se ve y
se actualiza.

### 3. Saludos: moderación y rate limit (issue [#31](https://github.com/Skayear/SkyWave-FM/issues/31))

Nuevo módulo `web/greetings.py`, separado a propósito de
`library/db.py`: un saludo es contenido generado por un oyente de la
web, no un dato de la biblioteca musical, aunque hoy los dos esquemas
vivan en el mismo archivo SQLite.

Dos funciones puras primero, con tests antes de tocar SQLite o
FastAPI:

- `is_appropriate(texto)` — filtro de palabras prohibidas por palabra
  completa (no substring, así "pelotudo" no marca "pelotudos"),
  case-insensitive. Lista chica a propósito, ampliable después.
- `is_within_rate_limit(envios_previos, now=..., max_messages=3,
  window=5min)` — mismo patrón de reloj inyectable que `pick_next`, no
  sabe de IPs, solo cuenta timestamps dentro de la ventana.

Recién con esas dos probadas se sumó la persistencia (`ensure_schema`,
`insert_greeting`, `recent_sends`) y `POST /greetings` en `app.py`:
valida con Pydantic (1-200 caracteres, un `field_validator` rechaza
mensajes de solo espacios que `min_length` no detecta), aplica
moderación (422) y rate limit por IP (429), guarda si pasa todo.

Bug real encontrado al conectar las piezas: `insert_greeting` guarda
`datetime.now(UTC)` (aware) pero `is_within_rate_limit` comparaba por
default contra `datetime.now()` (naive) → `TypeError` al comparar.
Se arregló pasando `now=datetime.now(UTC)` explícito desde el endpoint,
mismo valor que se usa para guardar.

El textbox (`<textarea>` + botón) se agregó a `templates/index.html`
en un paso aparte, con `fetch` a `POST /greetings` y mensajes de error
distintos para 422/429.

Probado con tests puros (moderación, rate limit, persistencia),
`TestClient` sobre el endpoint (saludo válido, vacío, palabra
prohibida, rate limit disparado con 4 pedidos seguidos) y a mano en el
navegador con `skywave play` corriendo.

### 4. WebSocket para actualizar en vivo (issue [#32](https://github.com/Skayear/SkyWave-FM/issues/32))

`GET /ws` reemplaza el polling HTTP de `/now-playing` cada 10s que
tenía la página desde el #30. SQLite no tiene pub/sub nativo, así que
el propio endpoint hace el polling: un loop `while True` que revisa
`now_playing` cada `poll_interval` (default 2s, inyectable como
dependencia -- mismo patrón que `get_db_path` -- para que los tests no
esperen segundos reales) y solo manda un mensaje cuando el resultado
cambió respecto al último enviado. Así un solo lugar lee la base por
tick, en vez de una consulta HTTP por cada pestaña abierta.

Se extrajo `_now_playing_payload(db_path)` como helper compartido
entre `GET /now-playing` y `GET /ws`, para no mantener dos copias de
la misma lógica de mapeo `db.NowPlaying` → `NowPlayingOut`.

En el frontend, `index.html` abre un `WebSocket` a `/ws` en vez de
hacer `fetch` periódico. Si la conexión se cae (proxy que corta
conexiones ociosas, reinicio del server) se reconecta sola a los 3s --
la página queda abierta horas escuchando la radio, así que no
reconectar habría sido un bug real, no una posibilidad remota.

Probado con `TestClient.websocket_connect` (primer mensaje `null` sin
nada sonando, primer mensaje con el tema actual, mensaje nuevo al
cambiar `now_playing` en la base) y a mano con dos pestañas del
navegador abiertas contra `skywave play` corriendo: las dos se
actualizan solas al cambiar de tema.

### 5. Playlist de próximos temas (issue [#38](https://github.com/Skayear/SkyWave-FM/issues/38))

Retomado después de Fase 8 arrancar en paralelo. `scheduler/selector.py`'s
`pick_next()` elige un tema a la vez, de forma reactiva — no existe el
concepto de "cola" de varios temas por venir. Para mostrar "a
continuación" en la web sin diseñar todavía una cola real (pregunta
abierta del propio issue), se resolvió como **vista previa aproximada**:

- `library/db.py` suma `play_history` — tabla que registra cada tema
  que arranca a sonar (`record_play_history()`, wireado en `cli.py`
  junto a `set_now_playing()`). Deliberadamente **no se poda**: sirve
  de log para debuguear repeticiones, además de alimentar la
  proyección. `recent_play_history()` trae los últimos 20 (misma
  ventana que ya usaba `cli.py` a mano) y `latest_play_history_id()`
  da una semilla estable.
- `GET /queue` en `app.py` proyecta los próximos 5 temas llamando a
  `pick_next()` en secuencia con ese historial y un `random.Random`
  propio (semilla = `latest_play_history_id()`) — sin tocar nada
  persistido. Estable mientras no suene un tema nuevo (misma semilla,
  misma respuesta); se recalcula entera cuando sí cambia. **No es una
  cola garantizada**: `skywave play` y el server web son procesos
  separados sin memoria compartida, así que el primer ítem no
  necesariamente coincide con lo que el scheduler real vaya a elegir
  si algo fuerza una relajación de ventana en el medio.
- `index.html` pide `/queue` al cargar y de nuevo cada vez que el
  WebSocket de #32 avisa que cambió el "sonando ahora" — mismo
  mecanismo de refresco, sin agregar un segundo push por WebSocket
  (una de las preguntas abiertas del issue original).

Probado con tests (persistencia de `play_history`, endpoint con
biblioteca vacía / con temas / estabilidad entre dos requests
seguidos) y a mano en el navegador con `skywave play` al aire: la
playlist se ve y cambia cuando cambia el tema.

(Esta simulación por `pick_next()` se reemplazó por una cola real
persistida en el #40 — ver más abajo. `recent_play_history()` y
`latest_play_history_id()` se borraron: quedaron sin uso.)

### 6. Cola garantizada, sin simular (issue [#40](https://github.com/Skayear/SkyWave-FM/issues/40))

Reemplaza la vista previa aproximada del #38 por una cola real:
`skywave play` planifica por adelantado en vez de que la web adivine.

- `library/db.py` suma `upcoming_queue` (FIFO) con `enqueue_track()`,
  `dequeue_next()`, `peek_queue()`, `clear_upcoming_queue()` — CRUD
  simple, mismo estilo que el resto del módulo.
- `scheduler/selector.py` suma `plan_queue()`: función pura que decide
  qué temas nuevos hacen falta para completar la cola hasta
  `target_depth`, dado lo que ya está encolado (cuenta para la ventana
  de no-repetición igual que `history`) — no toca la base, mismo
  patrón que `pick_next()`.
- `cli.py`: `_prepare_next()` rellena `upcoming_queue` con `plan_queue()`
  y **mira** (no saca) el primero. `GET /queue` en `app.py` se
  simplificó a leer `peek_queue()` directo — ya no simula nada, ni
  importa `pick_next`/`random`.

**Bug real encontrado a mano probando en vivo** (no lo agarró ningún
test): `_prepare_next()` corre en el hilo de fondo de `prep_pool` con
su propia conexión (necesario -- `sqlite3.Connection` no es segura
entre threads, encontrado también a mano: la primera versión compartía
el `conn` del hilo principal y explotaba con `ProgrammingError` en el
segundo tema). Con esa conexión propia resuelta, apareció un segundo
bug de diseño: `_prepare_next()` corre **un paso adelantado** al tema
que realmente suena (issue #20, para evitar aire muerto) — si sacaba
el tema de `upcoming_queue` en esa misma llamada, para cuando `GET
/queue` se consultaba, el tema *inmediato siguiente* ya estaba afuera
de la tabla (resuelto en el `Future`, sonando todavía no). El primer
ítem que mostraba la web en realidad era el que suena **después** del
próximo, no el próximo — confirmado a mano: la web mostró "The Girl Is
Mine" pero al terminar el tema sonó "Seven Seas Of Rhye". Se corrigió
separando las dos responsabilidades: `_prepare_next()` solo *mira*
(`peek_queue`) y prepara la intervención; recién se saca de la cola
(`dequeue_next`) en el loop principal, en el mismo momento en que ese
tema pasa a ser `now_playing` de verdad. Confirmado de nuevo a mano:
el primer ítem de la cola coincidió con el tema que arrancó después,
dos veces seguidas.

Probado con tests (`plan_queue()` puro, CRUD de `upcoming_queue`,
`GET /queue` leyendo lo persistido) y a mano al aire con `skywave play`
+ el server real: confirmado que el primer ítem de "a continuación"
es exactamente el próximo tema, y que la cola se corre (no se
recalcula entera) cuando cambia.

### 7. Excluir artistas desde la web (issue [#41](https://github.com/Skayear/SkyWave-FM/issues/41))

Espejo web de `skywave exclude`/`skywave include` (ver
docs/fase-3-programacion.md para el CLI). `library/db.py` suma
`list_artists()` (nombres distintos de `tracks`, ordenados). `GET
/artists` combina eso con `excluded_artists()` y devuelve cada artista
con su estado (`{name, excluded}`); `POST /exclude-artist` / `POST
/include-artist` alternan ese estado.

Primera versión tenía un textbox de nombre libre -- Pablo lo cambió por
un checkbox por artista (los 48 nombres salen de `GET /artists`, la
biblioteca real): así se ahorra la validación de que el texto escrito
coincida exactamente con un artista real, y no hace falta acordarse de
cómo está tipeado.

**Bug real encontrado a mano, no relacionado con #41 pero descubierto
mientras se probaba:** con cualquier pestaña del navegador abierta
(conexión WebSocket viva), `uvicorn --reload` quedaba colgado para
siempre en "Waiting for background tasks to complete" al guardar un
archivo. `GET /ws` (issue #32) nunca llamaba a `websocket.receive()`
-- sin eso, ni el propio handler se entera cuando el cliente
desconecta, ni Starlette tiene forma de entregarle el cierre que
dispara el servidor en un shutdown. Se corrigió corriendo dos tareas en
paralelo con `asyncio.wait(..., return_when=FIRST_COMPLETED)`: una que
empuja actualizaciones (la de siempre) y otra que solo espera
`receive()` para detectar la desconexión; la que termina primero
cancela a la otra. Confirmado a mano: con una conexión WS abierta de
verdad (cliente en Python con la librería `websockets`), un `--reload`
completó limpio en vez de colgarse, y el navegador se reconectó solo
después (el `setTimeout` de reconexión del #32 ya lo contemplaba).

Probado con tests (`GET /artists` vacío/con biblioteca/marcando
excluidos, los tests de WebSocket existentes siguen pasando con la
nueva estructura de dos tareas) y a mano: excluir/incluir por API,
y el reload sin colgarse con una conexión WS real abierta.

## Ajustes no anticipados

- Los issues #30, #31, #32, #36 y #38 aparecieron cerrados en GitHub
  el 2026-08-28 con comentarios que describían el trabajo como
  terminado y citaban commits (`34b46d8`, `317b938`, `9390fb5`,
  `7a8aa52`, `6654078`) que **no existen** en ningún lado del repo (ni
  local, ni `origin`, ni ramas, ni objetos sueltos) — tampoco había
  código correspondiente (`templates/`, `greetings.py`, ruta `/ws`,
  `play_history`, `scheduler/greetings.py` no existían). Todo indica
  que una sesión de IA anterior alucinó haber completado varias
  features y cerró los issues sin commitear nada. Se reabrieron todos
  antes de retomarlos de verdad (#30-32 el 2026-08-28, #36 y #38 el
  2026-08-30) — ver también docs/fase-4-el-locutor.md para #36.

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

## Fase 7 completa

Con #32 cerrado, los 4 issues del milestone están resueltos: la web
sirve el reproductor, el "sonando ahora" en vivo por WebSocket, y el
textbox de saludos con moderación y rate limit. Sigue faltando el
subcomando `skywave serve` (por ahora se levanta con `uvicorn` a
mano, ver README) y Fase 8 (producción: Docker, k3s, métricas).

# Fase 2 — Salir al aire

Objetivo de la fase: un mixer que abre `ffmpeg` contra Icecast, decodifica
pistas a PCM y las escribe a ritmo real, encadenándolas sin cortar la
conexión. **Cerrada** — los 4 issues del milestone [Fase 2 — Salir al
aire](https://github.com/Skayear/SkyWave-FM/milestone/3) están resueltos y
el milestone está cerrado.

Hito de la fase: **que suene en el navegador y en ETS2.** Navegador
confirmado a mano (`http://localhost:8010/sky.mp3`, con la biblioteca real
de 111 tracks escaneada en Fase 1). **ETS2 confirmado a mano** (issue
#33, ver "Seguimiento posterior a la fase" más abajo).

## Qué se hizo

### 1. Encoder persistente (issue [#7](https://github.com/Skayear/SkyWave-FM/issues/7))

`src/skywave/mixer/encoder.py` — `Encoder`, un proceso `ffmpeg` de larga
duración (vive toda la sesión de radio) que recibe PCM crudo por stdin y lo
re-codifica a mp3 contra Icecast:

```
ffmpeg -f s16le -ar 44100 -ac 2 -i pipe:0 -c:a libmp3lame -b:a 128k \
  -content_type audio/mpeg -f mp3 icecast://source:PASS@host:puerto/mount
```

Un hilo en background drena su stderr continuamente. Esto no es opcional:
el pipe de stderr tiene un buffer chico (~64KB en Linux), y si nadie lo lee
mientras el proceso vive, ffmpeg se bloquea escribiendo ahí en cuanto se
llena — un deadlock que no aparece en pruebas cortas, solo con streams
largos. Es la razón concreta por la que esta fase pide threading.

### 2. Decoder de una pista (issue [#8](https://github.com/Skayear/SkyWave-FM/issues/8))

`src/skywave/mixer/decoder.py` — `Decoder`, un proceso `ffmpeg` por pista
(vive solo mientras dura ese tema) que decodifica a PCM crudo con `-re`:

```
ffmpeg -re -i cancion.flac -vn -f s16le -ar 44100 -ac 2 pipe:1
```

`-re` hace que ffmpeg mismo pace la lectura del archivo a velocidad de
reproducción — la alternativa sería leer todo lo más rápido posible y
dormir a mano entre writes calculando bytes-por-segundo, más frágil y con
más superficie para bugs de timing.

`drain_stderr()` se extrajo a `mixer/_process.py`, compartido entre
Encoder y Decoder — recién en el segundo uso, no antes.

### 3. Encadenar pistas (issue [#9](https://github.com/Skayear/SkyWave-FM/issues/9))

`src/skywave/mixer/player.py` — `play_tracks(encoder, paths)`: recorre las
pistas en secuencia, abriendo un `Decoder` nuevo por cada una pero
reusando el mismo `Encoder` durante toda la secuencia. La conexión a
Icecast nunca se reconecta entre temas — confirmado con `stream_start` en
`/status-json.xsl`, que se mantiene idéntico durante toda la reproducción.

No es gapless a nivel milisegundo todavía (cada Decoder arranca su propio
proceso ffmpeg, que tarda un poco en levantar). Simplificación deliberada
para este primer corte, no un bug pendiente.

### 4. CLI `skywave play` (issue [#10](https://github.com/Skayear/SkyWave-FM/issues/10))

`src/skywave/cli.py` — cierra el círculo: lee la biblioteca de SQLite
(Fase 1) y la reproduce con lo de arriba. La URL de Icecast sale de
variables de entorno (`ICECAST_SOURCE_PASSWORD`, `ICECAST_SERVER_HOST`,
`ICECAST_SOURCE_PORT`) cargadas con `python-dotenv` — sin `config.toml`
todavía, no tenía sentido inventarle una ubicación fija.

`ICECAST_SOURCE_PORT` se agregó a `.env`/`.env.example`: hasta ahora el
`8010` (mapeo de host, ver Fase 0) solo estaba hardcodeado en
`docker-compose.yml`, y el mixer corriendo en el host —no en Docker— lo
necesita explícito.

## Ajustes no anticipados

- **Carátulas embebidas rompen un mux mp3 en vivo.** Durante la prueba
  local manual (antes de escribir código), empujar un `.flac` con carátula
  embebida directo a Icecast con `ffmpeg` sin `-map`/`-vn` rompió el stream
  (`Broken pipe`) casi al toque — ffmpeg intentó mapear la imagen como un
  stream de video dentro del mp3. La arquitectura de dos etapas (decodificar
  a PCM crudo, después re-codificar a mp3) esquiva esto de raíz: el PCM
  intermedio nunca lleva metadata ni imágenes, así que `Decoder` y `Encoder`
  no necesitaron ningún manejo especial para este caso — igual se dejó
  `-vn` explícito en el decoder por prolijidad, no por necesidad real.

- **Se filtró la password de Icecast en un transcript de prueba manual**
  (antes de que existiera código, un `pgrep -af` mostró la línea de
  comando completa con la URL). Se rotó en `.env` y se recreó el
  contenedor (`docker compose up -d`) para que tome la password nueva.

## Seguimiento posterior a la fase

### Confirmar reproducción en ETS2 (issue [#33](https://github.com/Skayear/SkyWave-FM/issues/33))

El hito original de esta fase era "que suene en ETS2 y en el navegador".
El navegador se había confirmado en su momento; ETS2 quedó pendiente
hasta retomarlo acá.

**El juego no tiene un campo para tipear una URL de radio a mano.**
Euro Truck Simulator 2 lee la lista de emisoras de internet de un
archivo de texto, `live_streams.sii`, ubicado en
`Documentos\Euro Truck Simulator 2\live_streams.sii` (perfil del
juego, no la carpeta de instalación de Steam). Si el archivo todavía
no existe, hay que abrir el juego una vez, entrar al menú de radio de
internet y usar "Update from Internet" para que lo genere con la
lista oficial de SCS.

**Formato de cada emisora**, una línea por estación con un índice
`stream_data[N]` secuencial y los campos separados por `|` (sin
espacios alrededor de las barras):

```
stream_data[N]: "URL|Nombre|Género|Idioma|Bitrate|Favorito"
```

Ejemplo real usado para SkyWave FM (`N` = el índice libre siguiente al
último de la lista):

```
stream_data[467]: "http://192.168.1.36:8010/sky.mp3|SkyWave FM|Various|ES|128|0"
```

Justo después de la llave de apertura del bloque, el archivo trae un
campo `stream_data: <total>` con la cantidad total de emisoras — tiene
que coincidir con la cantidad real de líneas `stream_data[...]` (índices
`0` a `total - 1`, sin huecos) o el juego puede comportarse raro. Al
insertar una emisora nueva, lo más simple es ocupar el próximo índice
libre y no tocar ese contador si ya venía bien.

**Bug real encontrado a mano: el juego pisa el archivo entero.** Si
después de agregar la emisora a mano se vuelve a tocar "Update from
Internet" (o a veces solo "Refresh") en el menú de radio, ETS2
descarga de nuevo la lista oficial de SCS y sobreescribe todo el
archivo, borrando cualquier entrada agregada a mano. No es un bug de
SkyWave-FM ni específico de esta emisora — es como el juego maneja esa
lista siempre. Mitigación: agregar la entrada a mano y **no volver a
tocar "Update from Internet"/"Refresh"** en esa pantalla. Se recomienda
guardar una copia de `live_streams.sii` aparte por si el juego la pisa
de todas formas.

**Prueba de red:** ETS2 corrió en otra máquina de la LAN, no en la
misma donde vive el repo, así que hizo falta exponer el stream más
allá de `127.0.0.1`. Se cambió `BIND_HOST` e `ICECAST_PUBLIC_HOST` en
`.env` a la IP de LAN del host (`192.168.1.36`) mientras duró la
prueba — ver Fase 8 (issue #39) para el detalle de esas variables. Con
Tailscale activo en el host real (pendiente, también Fase 8) esto no
debería hacer falta exponerlo a toda la LAN, solo a la tailnet.

Confirmado a mano: la emisora aparece en la lista de ETS2 y suena.

## Para estudiar antes de Fase 3

Fase 3 (programación: cola con rotación, no-repetición de artista, bloques
horarios, "sonando ahora") va a construir sobre lo que ya existe acá:
`db.list_tracks()` de Fase 1 y `play_tracks()` de esta fase, agregando la
lógica de qué pista elegir después en vez de simplemente recorrer toda la
biblioteca en orden.

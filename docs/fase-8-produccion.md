# Fase 8 — Producción

Objetivo de la fase: correr SkyWave-FM en el homelab de verdad, en vez
de `uv run` a mano en una terminal. Arranca con Docker; k3s y métricas
(Prometheus/Grafana) quedan para más adelante. **En progreso.**

## Qué se hizo

### 1. Dockerizar + exponer vía Tailscale (issue [#39](https://github.com/Skayear/SkyWave-FM/issues/39))

**Decisión de arranque**: esta sesión trabajó en una máquina de
desarrollo sin Tailscale instalado (ni el CLI ni una interfaz
`tailscale0`) -- confirmado con Pablo (2026-08-31) que el deploy real
va a otro host, donde Tailscale ya está configurado. El alcance acá
fue dejar el Dockerfile/compose/volúmenes listos y probados, con el
mecanismo de Tailscale preparado pero sin poder ejercitarlo de verdad
en este entorno.

**Un solo contenedor para `skywave play` + la web**, a pedido de Pablo
(el plan original separaba los dos en distintos servicios de compose).
`scripts/docker-entrypoint.sh` los corre como dos procesos dentro del
mismo contenedor, con supervisión mínima: si cualquiera de los dos
termina, se corta el otro y el contenedor entero sale, para que
`restart: unless-stopped` reinicie todo limpio en vez de dejar un
proceso zombi con el otro caído.

**Icecast interno vs. público, sin tocar `ICECAST_SERVER_HOST` para
todos.** Con dos procesos en un solo contenedor (mismo entorno
compartido), no se puede resolver esto con overrides por servicio de
compose como se pensaba al principio -- hizo falta un cambio de
código: `web/app.py`'s `get_stream_url()` ahora prueba
`ICECAST_PUBLIC_HOST`/`ICECAST_PUBLIC_PORT` primero (nuevas,
opcionales) y cae a `ICECAST_SERVER_HOST`/`ICECAST_SOURCE_PORT` si no
están seteadas -- así el uso sin Docker no cambia en nada. En
`docker-compose.yml`, el contenedor `skywave` fija
`ICECAST_SERVER_HOST=icecast`/`ICECAST_SOURCE_PORT=8000` (red interna
de compose, para el mixer) mientras `.env` trae el host/puerto público
real para lo que arma la URL que abre el navegador.

**`BIND_HOST`** en `.env` (default `127.0.0.1`) ata los puertos
publicados (Icecast 8010, web 8001) -- en el host real, la IP de la
interfaz `tailscale0`. El mapeo de Icecast volvió a `127.0.0.1` por
default (dejó de ser el `0.0.0.0` "temporal" que tenía desde antes de
esta fase).

**Volúmenes**, para que `docker compose down && up` no pierda nada:
`skywave.db` (bind mount de un solo archivo -- tiene que existir antes
del primer `up`, si no Docker crea un directorio ahí en vez de montar
el archivo), `assets/ads/` (bind mount, los `.wav` gitignoreados),
`cache/` (named volume, WAVs del locutor) y la caché de
HuggingFace/Kokoro (named volume, ~310MB, para no re-descargar en cada
restart).

**Bug real encontrado a mano, no relacionado con Tailscale:** el mount
de música apuntaba a `/music` adentro del contenedor, pero
`skywave.db` guarda paths absolutos del host (`/home/pablo/Music/...`)
-- ffmpeg no encontraba nada, fallaba al toque en cada tema, y el loop
pasaba al siguiente cada 2-5s en vez de sonar en tiempo real (parecía
"andar" por los logs, pero no sonaba nada de verdad). Se corrigió
montando `${MUSIC_DIR}:${MUSIC_DIR}:ro` -- el mismo path absoluto
adentro y afuera, sin necesidad de re-escanear.

**Segundo bug real, más grande: `Ctrl+C`/SIGINT no funcionaba, ni en
Docker ni corriendo `skywave play` a mano.** Investigado a fondo con
`/proc/PID/status` (`SigIgn`, `SigCgt`, `wchan`):

1. Un script de bash **no interactivo** (como `docker-entrypoint.sh`)
   pone SIGINT/SIGQUIT en "ignorar" para cualquier hijo lanzado con
   `&` -- comportamiento de POSIX, no un bug de Docker ni de Python.
   Sin arreglar esto, ningún `kill -INT` le llegaba a nadie. Se
   corrigió con el idiom estándar `(trap - INT; exec <comando>) &` en
   cada hijo -- resetea la señal a default antes de reemplazar la
   subshell con el proceso real.
2. Con eso arreglado, apareció un **segundo problema real**: si el
   `KeyboardInterrupt` llega justo en medio de `for chunk in
   decoder.chunks(): encoder.write(chunk)` (mixer/player.py), el
   `finally` de `Decoder.chunks()` llama a `self._process.terminate();
   self._process.wait()` -- pero el ffmpeg del decoder, al recibir la
   señal, intenta hacer un shutdown prolijo escribiendo a su stdout
   una última vez, y como nadie lo está leyendo ya (el loop de lectura
   ya cortó), se bloquea escribiendo a un pipe lleno. Deadlock: Python
   espera a que ffmpeg termine, ffmpeg espera que alguien le lea el
   pipe. **Bug real de `mixer/`, preexistente, no específico de
   Docker** -- queda pendiente arreglarlo de raíz (fuera del alcance
   de Dockerizar). Confirmado con `/proc/PID/wchan` mostrando `do_wait`
   en el proceso principal minutos después de la señal.

Mitigación para que Docker nunca dependa de que ese deadlock no pase:
`docker-entrypoint.sh` manda SIGINT, espera 8s, y si los procesos
siguen vivos escala a SIGKILL (`stop_grace_period: 20s` en compose le
da margen a esa escalada antes de que Docker mate todo por su cuenta).
Como SIGKILL no deja correr el cleanup del `finally`, `now_playing`
podía quedar mintiendo un tema viejo hasta el próximo arranque -- se
agregó `db.clear_now_playing(conn)` al **arranque** de `play()`, mismo
criterio que ya tenía `upcoming_queue` (que si no, dejaba pasar por
alto un plan de una corrida anterior). Con eso, un restart siempre
arranca en blanco sin importar cómo terminó el anterior.

Probado a mano, ciclo completo: `docker compose build` +`up` (audio
real confirmado con `ffprobe` contra `http://localhost:8010/sky.mp3`,
`/now-playing` y `/queue` reflejando la radio real), `skywave
exclude`/`include` desde el host contra el mismo `skywave.db`
compartido por volumen (confirma que los comandos de administración
no necesitan correr dentro de Docker), y `docker compose down && up`
sin perder la biblioteca (1341 tracks antes y después).

## Para retomar

- Activar Tailscale de verdad en el host real y confirmar el criterio
  de aceptación pendiente: accesible desde otro dispositivo de la
  tailnet, confirmado que NO desde internet público.
- El deadlock de `mixer/` en `Decoder.chunks()` cuando la interrupción
  llega a mitad de un chunk -- arreglar de raíz (por ejemplo, drenar
  el pipe del decoder antes de esperar a que ffmpeg termine, o usar un
  timeout en `Popen.wait()` con `kill()` de respaldo ahí mismo en vez
  de solo en el entrypoint de Docker).
- k3s y métricas (Prometheus/Grafana) -- todavía no arrancado.

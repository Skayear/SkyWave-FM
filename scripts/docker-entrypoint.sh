#!/usr/bin/env bash
set -euo pipefail

# Corre `skywave play` y el server web como dos procesos en el mismo
# contenedor (issue #39, a pedido de Pablo -- un solo servicio de
# compose en vez de separarlos). Docker solo vigila un PID 1; esto hace
# de supervisor mínimo: si cualquiera de los dos termina (crash o
# señal), se corta el otro y el contenedor entero sale, para que
# `restart: unless-stopped` reinicie todo limpio en vez de dejar un
# proceso zombi corriendo solo con el otro caído.
#
# Ojo con `trap - INT; exec ...` en cada subshell: un script de bash NO
# interactivo (como este) pone SIGINT/SIGQUIT en "ignorar" para
# cualquier hijo lanzado con `&` -- comportamiento de POSIX, no un bug
# de Docker. Sin este reset, `kill -INT` más abajo no le llega a nadie:
# encontrado a mano, `now_playing`/`upcoming_queue` nunca se limpiaban
# al cortar (ni en Docker ni corriendo `skywave play &` a mano).
#
# Los binarios del venv directo, no `uv run` -- así el `exec` reemplaza
# la subshell por el proceso Python real (mismo PID), sin una capa de
# `uv` en el medio que podría no reenviar la señal.

(trap - INT; exec /app/.venv/bin/skywave play "$@") &
PLAY_PID=$!

(trap - INT; exec /app/.venv/bin/uvicorn skywave.web.app:app --host 0.0.0.0 --port 8001) &
WEB_PID=$!

# `docker stop`/`compose down` mandan SIGTERM -- pero el `play()` de
# cli.py solo limpia `now_playing`/`upcoming_queue` en un
# `except KeyboardInterrupt` (SIGINT). Reenviamos SIGINT para que ese
# cleanup corra en vez de que el proceso muera en seco.
#
# Con timeout de respaldo: si el SIGINT llega justo en medio de leer un
# chunk de audio, `Decoder`/`Encoder` pueden entrar en deadlock entre sí
# (uno espera que el otro termine, el otro espera que alguien le lea el
# pipe) -- un bug real de mixer/, no de este script, y más grande que
# el alcance de Dockerizar (issue #39). Sin este timeout, un
# `docker compose down` se cuelga para siempre esperando un cleanup que
# nunca llega.
_shutdown() {
    kill -INT "$PLAY_PID" "$WEB_PID" 2>/dev/null || true
    # 8s de margen -- por debajo del stop_grace_period de compose (20s,
    # ver docker-compose.yml), para que esta escalada a SIGKILL corra
    # siempre antes de que Docker mate todo por su cuenta.
    for _ in $(seq 1 8); do
        kill -0 "$PLAY_PID" 2>/dev/null || kill -0 "$WEB_PID" 2>/dev/null || break
        sleep 1
    done
    kill -KILL "$PLAY_PID" "$WEB_PID" 2>/dev/null || true
    wait || true
}
trap '_shutdown; exit 0' TERM INT

wait -n
EXIT_CODE=$?
_shutdown
exit "$EXIT_CODE"

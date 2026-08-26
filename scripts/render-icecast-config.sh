#!/bin/sh
# Genera config/icecast.xml (gitignoreado, tiene las passwords en texto
# plano) a partir de config/icecast.xml.template + .env. Correr de nuevo
# cada vez que cambie .env o el template, y después `docker compose up -d`
# para que el contenedor lo recargue (icecast no relee el archivo solo).
set -eu

cd "$(dirname "$0")/.."

if [ ! -f .env ]; then
    echo "Falta .env — copiá .env.example y completá los valores reales." >&2
    exit 1
fi

set -a
. ./.env
set +a

envsubst '$ICECAST_SOURCE_PASSWORD $ICECAST_ADMIN_USER $ICECAST_ADMIN_PASSWORD $ICECAST_SERVER_HOST' \
    < config/icecast.xml.template > config/icecast.xml

echo "config/icecast.xml generado."

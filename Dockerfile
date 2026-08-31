FROM python:3.12-slim

# ffmpeg: lo usan mixer/decoder.py y mixer/encoder.py vía subprocess
# para decodificar música/voz a PCM y codificar el stream a Icecast.
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir uv

WORKDIR /app

# Dependencias primero, código después: mientras pyproject.toml/uv.lock
# no cambien, Docker cachea esta capa entera -- torch y kokoro son
# pesados y lentos de instalar, no hace falta repetirlo en cada cambio
# de código Python.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project

COPY . .
RUN uv sync --frozen

COPY scripts/docker-entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]

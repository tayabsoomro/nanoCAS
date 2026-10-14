# nanoCAS backend image: Flask + Socket.IO server with minimap2 and samtools.
FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    BACKEND_PORT=5007

RUN apt-get update \
 && apt-get install -y --no-install-recommends minimap2 samtools libnotify-bin \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 5007
# Threading async mode: gunicorn's gthread worker + simple-websocket serve
# both HTTP and WebSocket traffic. One worker only: the watchdog observers
# and run-health monitors are in-process state.
CMD ["sh", "-c", "gunicorn --worker-class gthread --threads 16 -w 1 --timeout 120 --bind 0.0.0.0:${BACKEND_PORT} nanocas:app"]

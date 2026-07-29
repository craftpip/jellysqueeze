# Dockerize Plan

## Overview

Package `media-convert-for-jellyfin` as a Docker image so users don't need to manually install Python, ffmpeg, or NVIDIA Container Toolkit on the host. The Web UI auto-runs when the container starts — just point a browser at it.

## Host Prerequisites

Three things needed on the host machine:

1. **NVIDIA GPU** — for hardware transcoding
2. **NVIDIA drivers** — whatever the distro uses (e.g. `nvidia-driver`)
3. **nvidia-container-toolkit** — bridges Docker to the GPU

Install on Debian/Ubuntu:

```bash
sudo apt install nvidia-container-toolkit
sudo systemctl restart docker
```

Without an NVIDIA card, fall back to CPU encoding — no special setup needed.

## Status

| Area | Status |
|---|---|
| Dockerfile | Done |
| docker-compose.yml | Done |
| .dockerignore | Done |
| Web UI auto-run on container start | Done |
| Multi-stage build (slimmer image) | Not started |
| CPU-only compose variant | Not started |
| Test build + run | Not started |
| Host prerequisite docs | Not started |
| CI build | Not started |

## Dockerfile

- **Base**: `python:3.11-slim-bookworm`
- **ffmpeg**: installed via apt
- **Python deps**: pip install from requirements.txt
- **Entrypoint**: `uvicorn webui.main:app --host 0.0.0.0 --port 8080`
- **Healthcheck**: pings `/api/config` every 30s
- **Exposes**: port 8080

The Web UI spawns `convert.py` as a subprocess when you click Run in the browser.

### CLI usage (override entrypoint)

```bash
docker compose run --rm --entrypoint "python convert.py" media-convert /media --use nvidia
```

## docker-compose.yml

```yaml
services:
  media-convert:
    build: .
    image: media-convert-for-jellyfin
    container_name: media-convert
    restart: unless-stopped
    ports:
      - "${WEBUI_PORT:-8080}:8080"
    runtime: nvidia
    environment:
      - NVIDIA_VISIBLE_DEVICES=all
      - NVIDIA_DRIVER_CAPABILITIES=all
    env_file:
      - .env
    volumes:
      - "${PWD}/config.yml:/app/config.yml:ro"
      - "${PWD}/done.txt:/app/done.txt"
      - "${PWD}/probe-cache.json:/app/probe-cache.json"
      - "${PWD}/size-report.csv:/app/size-report.csv"
      - "${PWD}/logs:/app/logs"
      - "${MEDIA_PATH}:/media:ro"
```

All paths use absolute-resolution variables (`${PWD}`, `${MEDIA_PATH}`) — no relative paths.

### Port

Web UI defaults to **8080**, configurable via `WEBUI_PORT` in `.env`.

### Volumes

| Host path | Container path | Purpose |
|---|---|---|
| `${PWD}/config.yml` | `/app/config.yml:ro` | Library + profile config |
| `.env` | (via env_file) | API key, bitrate, paths |
| `${PWD}/done.txt` | `/app/done.txt` | Track completed conversions |
| `${PWD}/probe-cache.json` | `/app/probe-cache.json` | Probe cache persistence |
| `${PWD}/size-report.csv` | `/app/size-report.csv` | Size report output |
| `${PWD}/logs` | `/app/logs` | Conversion logs |
| `${MEDIA_PATH}` | `/media:ro` | Media files (read-only) |

Set `MEDIA_PATH` in `.env`:

```env
MEDIA_PATH=/mnt/media/tvshows
WEBUI_PORT=8080
```

## .dockerignore

Excludes: `.venv/`, `__pycache__/`, `.git/`, plans, tests, logs, local state files (`.env`, `done.txt`, `probe-cache.json`, etc.), and markdown files.

Keeps the image lean by not copying development/state artifacts.

## Web UI Auto-run Flow

```
Container starts
  └── uvicorn starts webui.main:app on 0.0.0.0:8080
        ├── Serves HTML/JS frontend at GET /
        ├── REST API at /api/*
        │     ├── POST /api/run  → spawns convert.py as subprocess
        │     ├── POST /api/stop → SIGTERM → SIGKILL
        │     └── GET /api/status → poll exit code
        └── WebSocket at /api/ws/{run_id} → live terminal output
```

User opens `http://localhost:8080` in a browser, picks a mode and flags, clicks Run. The web UI streams terminal output live.

## Run commands

```bash
# Build
docker compose build

# Start Web UI (auto-run on port 8080)
docker compose up -d

# View logs
docker compose logs -f

# CLI mode (one-off conversion)
docker compose run --rm --entrypoint "python convert.py" \
  media-convert /media --use nvidia

# CPU fallback (remove runtime + NVIDIA_* from compose)
docker compose run --rm --entrypoint "python convert.py" \
  media-convert /media --use cpu
```

## TODO

- [ ] Multi-stage build — build ffmpeg with full codec support or use a prebuilt ffmpeg image
- [ ] Split compose into `docker-compose.yml` (GPU) + `docker-compose.cpu.yml` override
- [ ] Test build + run on real media
- [ ] Document host prerequisites in readme
- [ ] Push to registry option

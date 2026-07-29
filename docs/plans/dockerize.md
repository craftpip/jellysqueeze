# Dockerize Plan

## Overview

Package `media-convert-for-jellyfin` as a Docker image so users don't need to manually install Python, ffmpeg, or GPU drivers on the host. The Web UI auto-runs when the container starts — just point a browser at it.

One Dockerfile per GPU variant (each uses a different `jrottenberg/ffmpeg` ffmpeg source), four compose files:

| File | GPU | ffmpeg source | Host needs | Device / Runtime |
|---|---|---|---|---|
| `docker-compose.yml` | CPU (default) | `jrottenberg/ffmpeg:8.1-ubuntu2404` | None | None |
| `docker-compose.nvidia.yml` | NVIDIA | `jrottenberg/ffmpeg:8.1-nvidia2404` | NVIDIA driver + `nvidia-container-toolkit` | `runtime: nvidia` |
| `docker-compose.intel.yml` | Intel QSV | `jrottenberg/ffmpeg:8.1-vaapi2404` | `intel-media-va-driver-non-free` | `/dev/dri:/dev/dri`, render GID |
| `docker-compose.amd.yml` | AMD AMF | `jrottenberg/ffmpeg:8.1-amf2404` | ROCm/AMF runtime + AMD driver | `/dev/dri:/dev/dri`, `/dev/kfd:/dev/kfd` |

The `jrottenberg/ffmpeg` project has pre-built variants for each GPU vendor — each compiled from source with the right `--enable` flags (NVENC, VAAPI, AMF). We copy the ffmpeg binary into a Python runtime image via multi-stage build.

Usage:

```bash
# Build (pick your variant)
docker compose -f docker-compose.nvidia.yml build

# CPU
docker compose up -d

# NVIDIA
docker compose -f docker-compose.nvidia.yml up -d

# Intel QSV
docker compose -f docker-compose.intel.yml up -d

# AMD AMF
docker compose -f docker-compose.amd.yml up -d
```

Each compose file is standalone (not an override) since they need different build args and device configs.

## Key differences from host-based usage

### GPU detection in Docker

Currently the code detects GPUs by running `ffmpeg -encoders` and checking for encoder names. In Docker this is **not reliable** — an encoder may be compiled into ffmpeg but fail at runtime because:

- The GPU device isn't passed through (`/dev/dri`, `/dev/kfd` not mounted)
- The NVIDIA container toolkit isn't configured
- The render group GID doesn't match the host

Docker detection should check device availability **before** checking encoder names:

| GPU | Check device | Then check encoder |
|---|---|---|
| NVIDIA | `nvidia-smi` exits 0 | `ffmpeg -encoders` has `h264_nvenc` |
| Intel QSV | `/dev/dri/renderD128` exists | `ffmpeg -encoders` has `h264_qsv` |
| AMD AMF | `/dev/dri` + `/dev/kfd` exist | `ffmpeg -encoders` has `h264_amf` |
| CPU | Always works | `libx264` is always compiled in |

### AMF on Linux (AMD)

AMD's AMF (Advanced Media Framework) now works on Linux via the ROCm stack. It's AMD's equivalent of NVENC — much more featured than VAAPI for encoding (more presets, better quality control). The `jrottenberg/ffmpeg:amf2404` image builds ffmpeg with `--enable-amf`.

At runtime, the container needs the AMD ROCm/AMF user-space libraries. The exact packages need research (likely `amf-amdgpu-pro` or ROCm runtime libs from the AMD repos).

### Intel QSV path

On Linux, Intel QSV is accessed through the `iHD` VAAPI driver (`intel-media-va-driver`). The `jrottenberg/ffmpeg:vaapi2404` variant has VAAPI compiled in. The encoder is `h264_qsv` / `hevc_qsv` with `-hwaccel qsv` (native QSV path) or `-hwaccel vaapi` (VAAPI path).

The `intel` profile should use `h264_qsv` encoder with `-hwaccel qsv` for the native path.

## Encoder mapping changes needed

Current → Fixed for Docker:

| Profile | Current encoder | Docker encoder | Reason |
|---|---|---|---|
| `intel` | `h264_vaapi` | `h264_qsv` | Native QSV path via iHD driver, not VAAPI abstraction |
| `amdgpu` | `h264_amf` | keep `h264_amf` | AMF now works on Linux via ROCm — no change needed |
| `nvidia` | `h264_nvenc` | keep as-is | Correct already |
| `cpu` | `libx264` | keep as-is | Correct already |

For Intel, `-hwaccel` should change from `vaapi` to `qsv`. For AMD AMF on Linux, `-hwaccel` for AMF needs investigation (AMF may not need `-hwaccel` since it handles decode internally).

## Status

| Area | Status |
|---|---|
| CPU Dockerfile + docker-compose.yml | Not started |
| NVIDIA Dockerfile + docker-compose.nvidia.yml | Not started |
| Intel QSV Dockerfile + docker-compose.intel.yml | Not started |
| AMD AMF Dockerfile + docker-compose.amd.yml | Not started |
| Research AMD ROCm/AMF runtime requirements | Not started |
| Fix GPU detection for Docker (device checks before encoder checks) | Not started |
| Fix Intel encoder mapping (vaapi → qsv) | Not started |
| .dockerignore | Done |
| Web UI auto-run on container start | Done |
| Test build + run (all 4 variants) | Not started |
| Host prerequisite docs in README | Not started |
| CI build | Not started |

## Dockerfile (pattern — one per variant)

Each variant follows the same multi-stage pattern but uses a different jrottenberg ffmpeg image:

```dockerfile
# Stage 1: ffmpeg with vendor-specific codecs
FROM jrottenberg/ffmpeg:8.1-{VARIANT} AS ffmpeg

# Stage 2: Python runtime
FROM python:3.11-slim-bookworm

# Vendor-specific runtime libraries go here
# (varies per GPU — see each variant below)

# Copy ffmpeg/ffprobe
COPY --from=ffmpeg /usr/local/bin/ffmpeg /usr/local/bin/ffmpeg
COPY --from=ffmpeg /usr/local/bin/ffprobe /usr/local/bin/ffprobe

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app/src
ENV WEBUI_HOST=0.0.0.0
ENV WEBUI_PORT=8080

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:$WEBUI_PORT/api/config')" \
  || exit 1

ENTRYPOINT ["python", "-m", "uvicorn", "webui.main:app", "--host", "0.0.0.0", "--port", "8080"]
```

### Variant specifics

| Variant | `{VARIANT}` | Runtime packages to install | Notes |
|---|---|---|---|
| CPU | `ubuntu2404` | None | ffmpeg from apt standard build |
| NVIDIA | `nvidia2404` | None needed | CUDA/NVENC libs come from `runtime: nvidia` at container start |
| Intel QSV | `vaapi2404` | `libva2 libva-drm2 intel-media-va-driver-non-free` | iHD driver provides QSV via VAAPI |
| AMD AMF | `amf2404` | **TBD** — needs ROCm/AMF runtime libs | Research: `amf-amdgpu-pro` or rocm-dev runtime packages |

## docker-compose.yml (CPU — default)

```yaml
services:
  media-convert:
    build:
      context: .
      dockerfile: Dockerfile.cpu
    image: media-convert-for-jellyfin:cpu
    container_name: media-convert
    restart: unless-stopped
    ports:
      - "${WEBUI_PORT:-8080}:8080"
    env_file:
      - .env
    volumes:
      - "${PWD}/config.yml:/app/config.yml:ro"
      - "${PWD}/.env:/app/.env"
      - "${PWD}/var:/app/var"
      - /mnt/media1t/downloads:/mnt/media1t/downloads
      - /mnt/media2t/downloads:/mnt/media2t/downloads
      - /mnt/media3t/downloads:/mnt/media3t/downloads
```

No GPU config needed. Works anywhere.

## docker-compose.nvidia.yml (standalone)

```yaml
services:
  media-convert:
    build:
      context: .
      dockerfile: Dockerfile.nvidia
    image: media-convert-for-jellyfin:nvidia
    container_name: media-convert-nvidia
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
      - "${PWD}/.env:/app/.env"
      - "${PWD}/var:/app/var"
      - /mnt/media1t/downloads:/mnt/media1t/downloads
      - /mnt/media2t/downloads:/mnt/media2t/downloads
      - /mnt/media3t/downloads:/mnt/media3t/downloads
```

Host needs: NVIDIA driver + `nvidia-container-toolkit`.

## docker-compose.intel.yml (standalone)

```yaml
services:
  media-convert:
    build:
      context: .
      dockerfile: Dockerfile.intel
    image: media-convert-for-jellyfin:intel
    container_name: media-convert-intel
    restart: unless-stopped
    ports:
      - "${WEBUI_PORT:-8080}:8080"
    devices:
      - /dev/dri:/dev/dri
    group_add:
      - "109"
    environment:
      - LIBVA_DRIVER_NAME=iHD
    env_file:
      - .env
    volumes:
      - "${PWD}/config.yml:/app/config.yml:ro"
      - "${PWD}/.env:/app/.env"
      - "${PWD}/var:/app/var"
      - /mnt/media1t/downloads:/mnt/media1t/downloads
      - /mnt/media2t/downloads:/mnt/media2t/downloads
      - /mnt/media3t/downloads:/mnt/media3t/downloads
```

Host needs: `intel-media-va-driver-non-free` on host kernel. The `render` GID (`109`) may differ — users should check `getent group render` on their host.

## docker-compose.amd.yml (standalone)

```yaml
services:
  media-convert:
    build:
      context: .
      dockerfile: Dockerfile.amd
    image: media-convert-for-jellyfin:amd
    container_name: media-convert-amd
    restart: unless-stopped
    ports:
      - "${WEBUI_PORT:-8080}:8080"
    devices:
      - /dev/dri:/dev/dri
      - /dev/kfd:/dev/kfd
    group_add:
      - "44"     # video group (ROCm requirement)
    env_file:
      - .env
    volumes:
      - "${PWD}/config.yml:/app/config.yml:ro"
      - "${PWD}/.env:/app/.env"
      - "${PWD}/var:/app/var"
      - /mnt/media1t/downloads:/mnt/media1t/downloads
      - /mnt/media2t/downloads:/mnt/media2t/downloads
      - /mnt/media3t/downloads:/mnt/media3t/downloads
```

Host needs: AMD ROCm drivers installed. The `video` GID (`44`) differs from the `render` GID — ROCm requires the `video` group for `/dev/kfd` access.

## Volumes

All variants share the same volume layout:

| Host path | Container path | Purpose |
|---|---|---|
| `${PWD}/config.yml` | `/app/config.yml:ro` | Library + profile config |
| `.env` | (via env_file) | API key, bitrate, paths |
| `${PWD}/var` | `/app/var` | Progress, logs, probe cache, size reports |
| `${MEDIA_PATH}` | (as configured) | Media files |

Set `MEDIA_PATH` in `.env` matching your config.yml library paths.

## .dockerignore

Excludes: `.venv/`, `__pycache__/`, `.git/`, plans, tests, logs, local state files (`.env`, `done.txt`, `probe-cache.json`, etc.), and markdown files.

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

User opens `http://localhost:8080` in a browser, picks a mode and flags, clicks Run.

## TODO

- [ ] Research AMD ROCm/AMF runtime requirements for the container
- [ ] Create Dockerfile.cpu + docker-compose.yml
- [ ] Create Dockerfile.nvidia + docker-compose.nvidia.yml
- [ ] Create Dockerfile.intel + docker-compose.intel.yml
- [ ] Create Dockerfile.amd + docker-compose.amd.yml
- [ ] Fix GPU detection for Docker — check device files before encoder names
- [ ] Fix Intel encoder mapping: `h264_vaapi` → `h264_qsv`, `-hwaccel vaapi` → `-hwaccel qsv`
- [ ] Test build + run on real media (all 4 variants)
- [ ] Document host prerequisites in README
- [ ] CI build
- [ ] Docker Hub / registry push option

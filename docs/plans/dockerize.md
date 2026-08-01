# Dockerize Plan

## Overview

Package `jellysqueeze` as a Docker image so users don't need to manually install Python, ffmpeg, or GPU drivers on the host. The Web UI auto-runs when the container starts — just point a browser at it.

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
| CPU Dockerfile + docker-compose.yml | Done |
| NVIDIA Dockerfile + docker-compose.nvidia.yml | Done |
| Intel QSV Dockerfile + docker-compose.intel.yml | Done |
| AMD AMF Dockerfile + docker-compose.amd.yml | Done (WIP/untested) |
| Research AMD ROCm/AMF runtime requirements | Cancelled — `h264_amf` is Windows-only, not in jrottenberg. AMD uses VA-API via `radeonsi` instead |
| Fix GPU detection for Docker (device checks before encoder checks) | Done — `device_available()` in convert.py checks `nvidia-smi` or `/dev/dri/renderD128` before trusting encoder names |
| Fix Intel encoder mapping (vaapi → qsv) | Done — `h264_vaapi` → `h264_qsv`, `-hwaccel vaapi` → `-hwaccel qsv`, removed VAAPI device args |
| .dockerignore | Done |
| Web UI auto-run on container start | Done |
| Test build + run (CPU, NVIDIA) | Done — smoke-tested both, confirmed working. Intel untested (no iGPU). AMD WIP |
| Host prerequisite docs in README | Not started |
| CI build | Not started |

## Dockerfile (pattern — one per variant)

Each variant uses jrottenberg/ffmpeg as the base image and installs Python on top (single-stage). Multi-stage would cause libc conflicts — jrottenberg uses Ubuntu, slim uses Debian.

```dockerfile
FROM jrottenberg/ffmpeg:8.1-{VARIANT}

RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 \
    python3-pip \
    python3-venv \
    && rm -rf /var/lib/apt/lists/*

RUN python3 -m venv /venv
ENV PATH="/venv/bin:$PATH"

WORKDIR /app
COPY requirements.txt .
RUN /venv/bin/pip install --no-cache-dir -r requirements.txt
COPY . .

ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app/src
ENV WEBUI_HOST=0.0.0.0
ENV WEBUI_PORT=8080
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s \
  CMD /venv/bin/python -c "import urllib.request; urllib.request.urlopen('http://localhost:$WEBUI_PORT/api/config')" \
  || exit 1

ENTRYPOINT ["/venv/bin/python", "-m", "uvicorn", "webui.main:app", "--host", "0.0.0.0", "--port", "8080"]
```

### Variant specifics

| Variant | Jrottenberg image | Extra packages | Notes |
|---|---|---|---|---|
| CPU | `jrottenberg/ffmpeg:8.1-ubuntu2404` | Python from apt | Ubuntu 24.04 (Python 3.12) |
| NVIDIA | `jrottenberg/ffmpeg:8.1-nvidia2404` | Python from apt | Needs `runtime: nvidia` at container start |
| Intel QSV | `jrottenberg/ffmpeg:8.1-vaapi2404` | Python + intel-media-va-driver-non-free, libva2 | iHD driver for QSV, needs `/dev/dri` |
| AMD (WIP) | `jrottenberg/ffmpeg:8.1-vaapi2404` | Python + mesa-va-drivers, libva2 | Uses VAAPI via radeonsi. `h264_amf` is Windows-only, not in jrottenberg |

## docker-compose.yml (CPU — default)

```yaml
services:
  jellysqueeze:
    build:
      context: .
      dockerfile: Dockerfile.cpu
    image: jellysqueeze:cpu
    container_name: jellysqueeze
    restart: unless-stopped
    ports:
      - "${WEBUI_PORT:-8080}:8080"
    env_file:
      - .env
    volumes:
      - "${PWD}/config.yml:/app/config.yml:ro"
      - "${PWD}/.env:/app/.env"
      - "${PWD}/var:/app/var"
```

No GPU config needed. Works anywhere.

## docker-compose.nvidia.yml (standalone)

```yaml
services:
  jellysqueeze-nvidia:
    build:
      context: .
      dockerfile: Dockerfile.nvidia
    image: jellysqueeze:nvidia
    container_name: jellysqueeze-nvidia
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
```

Host needs: NVIDIA driver + `nvidia-container-toolkit`.

## docker-compose.intel.yml (standalone)

```yaml
services:
  jellysqueeze-intel:
    build:
      context: .
      dockerfile: Dockerfile.intel
    image: jellysqueeze:intel
    container_name: jellysqueeze-intel
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
```

Host needs: `intel-media-va-driver-non-free` on host kernel. The `render` GID (`109`) may differ — users should check `getent group render` on their host.

## docker-compose.amd.yml (standalone)

```yaml
services:
  jellysqueeze-amd:
    build:
      context: .
      dockerfile: Dockerfile.amd
    image: jellysqueeze:amd
    container_name: jellysqueeze-amd
    restart: unless-stopped
    ports:
      - "${WEBUI_PORT:-8080}:8080"
    devices:
      - /dev/dri:/dev/dri
    group_add:
      - "109"
    environment:
      - LIBVA_DRIVER_NAME=radeonsi
    env_file:
      - .env
    volumes:
      - "${PWD}/config.yml:/app/config.yml:ro"
      - "${PWD}/.env:/app/.env"
      - "${PWD}/var:/app/var"
```

Host needs: AMD Mesa VA-API drivers (`mesa-va-drivers`). Uses the `vaapi` profile with `radeonsi` VA-API driver (same device mount as Intel, different `LIBVA_DRIVER_NAME`). WIP — AMF (`h264_amf`) is Windows-only and not available in jrottenberg images.

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

- [x] Create Dockerfile.cpu + docker-compose.yml
- [x] Create Dockerfile.nvidia + docker-compose.nvidia.yml
- [x] Create Dockerfile.intel + docker-compose.intel.yml
- [x] Create Dockerfile.amd + docker-compose.amd.yml
- [x] Fix GPU detection for Docker — check device files before encoder names
- [x] Fix Intel encoder mapping: `h264_vaapi` → `h264_qsv`, `-hwaccel vaapi` → `-hwaccel qsv`
- [ ] Test build + run on real media (all 4 variants) — CPU and NVIDIA smoke-tested
- [ ] Document host prerequisites in README
- [ ] CI build
- [ ] Docker Hub / registry push option

# Linux Transcoding Guide (AMDGPU + Intel QSV)

## Fastest AMDGPU Path on Linux (Transcoding)

If your goal is maximum transcoding speed on Linux with AMDGPU, use VA-API end-to-end:

1. Hardware decode with VA-API
2. Hardware scale with `scale_vaapi`
3. Hardware encode with VA-API

For raw throughput/FPS, H.264 output is usually the fastest:

- `h264_vaapi` (generally fastest/most compatible)
- `hevc_vaapi` (often slower than H.264, but more efficient compression)
- `av1_vaapi` (newer hardware support; usually not the fastest)

### Typical FFmpeg pattern (AMD + VA-API)

```bash
ffmpeg \
  -hwaccel vaapi \
  -hwaccel_output_format vaapi \
  -vaapi_device /dev/dri/renderD128 \
  -i input.mp4 \
  -vf 'scale_vaapi=w=1280:h=720' \
  -c:v h264_vaapi \
  -b:v 4M \
  -c:a copy \
  output.mp4
```

## Intel QSV on Linux (Install + Verify)

QSV on Linux depends on Intel media drivers and the VA stack.

## 1) Install packages

### Ubuntu / Debian

```bash
sudo apt update
sudo apt install ffmpeg intel-media-va-driver-non-free libmfx-gen1.2 libvpl2 vainfo intel-gpu-tools
```

### Fedora

```bash
sudo dnf install ffmpeg intel-media-driver libvpl libva-utils intel-gpu-tools
```

### Arch Linux

```bash
sudo pacman -S ffmpeg intel-media-driver libvpl libva-utils intel-gpu-tools
```

## 2) Confirm iGPU device exists

Make sure Intel iGPU is enabled in BIOS/UEFI, then check:

```bash
ls -l /dev/dri/renderD128
```

## 3) Verify VA/QSV availability

```bash
vainfo
ffmpeg -hide_banner -encoders | grep qsv
ffmpeg -hide_banner -hwaccels | grep qsv
```

## 4) Quick QSV transcode test

```bash
ffmpeg -hwaccel qsv -c:v h264_qsv -i input.mp4 -c:v h264_qsv -preset veryfast output.mp4
```

## Troubleshooting Notes

- If any stage falls back to CPU (decode, scaling, tonemapping, subtitle burn-in), performance drops sharply.
- On Linux + AMD, prefer VA-API rather than AMF for practical support.
- If QSV does not appear in FFmpeg, validate:
  - Installed Intel media driver
  - `vainfo` output is healthy
  - FFmpeg build includes QSV encoders/decoders

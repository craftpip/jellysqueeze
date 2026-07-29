# media-convert-for-jellyfin

Shrink your video library for Jellyfin (or any self-hosted media server) without the bloat. 🎬

Recursively scan a media directory, re-encode oversized videos to a target bitrate, and strip audio/subtitle tracks you don't need — all while keeping your existing H.264/HEVC files untouched.

## 🤔 Why

Self-hosted video libraries accumulate huge files. This tool:

- Finds videos above your target bitrate and re-encodes them smaller with **GPU-accelerated** or CPU encoding.
- Removes **unwanted audio languages** so you don't keep 5+ audio tracks you can't understand.
- Removes **unwanted subtitle streams** to save more space.
- Converts multichannel audio (e.g. 7.1) down to stereo if you don't have a surround setup.
- Tracks what's already been converted so you can stop/resume safely.

## 🚀 Quick start

```bash
# Convert with GPU (NVIDIA)
python convert.py /path/to/media --use nvidia

# Convert with CPU and a specific quality
python convert.py /path/to/media --use cpu --crf 23

# Convert with a target bitrate and keep a log
python convert.py /path/to/media --bitrate 2800 --log-file convert.log

# Run two conversions at once
python convert.py /path/to/media --use nvidia --workers 2
```

## ✨ Features

- Recursive directory scan — point it at your library root
- GPU acceleration: `nvidia`, `amdgpu`, `intel`, `vaapi`, or `cpu`
- Optional parallel workers for converting multiple files at once
- Set target video bitrate or use CRF quality mode
- Strip audio languages you don't speak
- Strip subtitle streams you don't read
- Downmix multichannel audio to stereo
- Resume-safe — tracks completed conversions in `var/_progress.txt`
- Size report in `var/size-report.csv`
- Temp file safety with automatic cleanup

## 🎮 CLI Options

| Option | Description | Default | Required |
|---|---|---|---|
| **Target & Scan** | | | |
| `dir` | Directory to scan recursively | `.` | ❌ |
| `--bitrate` | Target video bitrate in kbps (max = bitrate + 1000) | `TARGET_BR` env | ❌ |
| `--crf` | CRF quality mode (lower = better, e.g. 23) | `DEFAULT_CRF` env | ❌ |
| `--exclude` | Comma-separated directory names to skip (always excludes `.trickplay`) | `""` | ❌ |
| **Encoder** | | | |
| `--use` | Transcode profile: `nvidia`, `amdgpu`, `intel`, `vaapi`, `cpu`, or a raw ffmpeg encoder name | `nvidia` | ❌ |
| `-j`, `--workers` | Number of local files to process concurrently. `1` keeps the original sequential behavior. Remote mode remains sequential. | `1` | ❌ |
| `--verbose` | Verbose logging (debug output) | off | ❌ |
| **Logging** | | | |
| `--log-file` | Path to write a log file | none | ❌ |
| **Remote** | | | |
| `--remote` | Remote target (`user@host:/path`) | `""` | ❌ |
| `--local-tmp` | Local temp directory for remote mode | `/tmp/convert-remote` | ❌ |
| **Cleanup** | | | |
| `--cleanup-tmp` | Full recursive temp-file cleanup before scan | off | ❌ |

### Worker guidance

Start small. More workers is not always faster because encoders, disks, and GPUs have limits.

| Encoder | Suggested workers |
|---|---|
| NVIDIA NVENC | `2` |
| AMD AMF / VAAPI | `2` |
| Intel QSV | `2` to `4` |
| CPU / libx264 | `2` to `4`, depending on CPU cores |

If conversions start failing with encoder errors, lower `--workers`.

## 📋 Requirements

- Python 3.10+
- `ffmpeg` and `ffprobe` in `PATH`
- GPU encoder drivers if using hardware profiles

```bash
ffmpeg -version
ffprobe -version
```

## ⚙️ Configuration

Create a `.env` file in the project root:

```dotenv
TARGET_BR=3000
MAX_BR=3300
BUFSIZE=6000
DEFAULT_CRF=23
```

Optional binary overrides:

```dotenv
FFMPEG_BIN=/usr/bin/ffmpeg
FFPROBE_BIN=/usr/bin/ffprobe
```

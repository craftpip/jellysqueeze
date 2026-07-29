# Root Folder Organisation

## Goal

Root stays clean — only build files, config, and docs. All source code in `src/`. All runtime data in `var/`.

## Proposed layout

```
Root:
  setup.py
  requirements.txt
  Dockerfile
  docker-compose.yml
  .dockerignore
  readme.md
  AGENTS.md

src/                        # all source code
  convert.py                # main entry point
  jellyfin_client.py        # jellyfin API client
  _detect_encoder.py        # encoder detection helper

scripts/
  convert.sh

config/
  config.yml
  config.yml.example
  .env

var/                        # all runtime data
  _progress.txt             # (renamed from done.txt)
  size-report.csv
  probe-cache.json
  logs/
    YYYY-MM-DD/
      HH-MM-SS_mode.log
      HH-MM-SS_mode.size.csv

plans/
test_files/
webui/
```

## Changes

- `convert.py`, `jellyfin_client.py`, `_detect_encoder.py` move to `src/`
- `convert.py` becomes `src/convert.py` (update all internal imports + paths)
- `setup.py` entry point updated to `src/convert.py`
- Everything runtime goes to `var/`

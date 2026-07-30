"""Helper script for detecting an available GPU encoder."""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from convert import device_available, get_available_encoders, resolve_transcoder

get_available_encoders()

profiles = ["nvidia", "intel", "vaapi", "amdgpu", "cpu"]
for p in profiles:
    if not device_available(p):
        continue
    ok, _ = resolve_transcoder(p)
    if ok:
        print(p)
        break
else:
    print("cpu")

"""Helper script run by setup.py to detect available GPU encoder."""

import sys
sys.path.insert(0, ".")

from convert import get_available_encoders, resolve_transcoder

get_available_encoders()

profiles = ["nvidia", "intel", "amdgpu", "vaapi", "cpu"]
for p in profiles:
    ok, _ = resolve_transcoder(p)
    if ok:
        print(p)
        break
else:
    print("cpu")

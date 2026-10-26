#!/usr/bin/env bash
set -euo pipefail

mkdir -p /logs/verifier
printf '0\n' >/logs/verifier/reward.txt
cd /app

test -s /logs/artifacts/model.patch
git apply --check /logs/artifacts/model.patch
git apply /logs/artifacts/model.patch

python3 -m unittest -v test_canary_greeting.py
python3 - <<'PY'
from canary_greeting import greet

assert greet("Ada") == "Hello, Ada!"
assert greet("  Ada Lovelace  ") == "Hello, Ada Lovelace!"
try:
    greet(" \t ")
except ValueError:
    pass
else:
    raise AssertionError("blank names must raise ValueError")
print("independent greeting contract checks passed")
PY

printf '1\n' >/logs/verifier/reward.txt

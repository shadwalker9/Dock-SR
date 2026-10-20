#!/usr/bin/env bash
set -euo pipefail
repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
gate0_venv="${1:-$repo_root/.venv-gate0}"
gate0_python="${DOCKSR_GATE0_PYTHON:-python3}"
"$gate0_python" -c 'import sys; assert (3, 10) <= sys.version_info[:2] <= (3, 12), "Gate-0 lock supports CPython 3.10-3.12; CPython 3.12/Linux x86_64 is tested"'
"$gate0_python" -m venv "$gate0_venv"
"$gate0_venv/bin/python" -m pip install --require-hashes --only-binary=:all: -r "$repo_root/requirements-gate0.lock"
"$gate0_venv/bin/python" -c 'import onnx, onnxruntime, numpy; print("Host SDK:", onnx.__version__, onnxruntime.__version__, numpy.__version__); print("Gate-0 tools select CPU only; this setup installs no AMD runtime or drivers.")'

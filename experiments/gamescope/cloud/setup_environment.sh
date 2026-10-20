#!/usr/bin/env bash
# Debian 13 x86_64 isolated laboratory prerequisites, never a handheld installer.
set -euo pipefail
cloud_source_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
lab_root=${1:-/workspace/DockSR-gamescope-lab}
repo_root=$(cd -- "$cloud_source_dir/../../.." && pwd)
python3 "$repo_root/scripts/bootstrap_cloud.py"
python3 "$repo_root/scripts/bootstrap_preview.py" --with-test-tools
python3 "$cloud_source_dir/prepare_deps.py" --root "$lab_root" \
  --restore-lock "$cloud_source_dir/dependencies.lock.json" \
  --restore-lock "$cloud_source_dir/sid-dependencies.lock.json"
python3 -m venv "$lab_root/venv"
"$lab_root/venv/bin/python" -m pip install --disable-pip-version-check --require-hashes \
  -r "$cloud_source_dir/meson-requirements.txt"
python3 - "$lab_root" <<'PY'
import pathlib, shlex, sys
root = pathlib.Path(sys.argv[1]).resolve()
text = '''#!/bin/sh
# Workspace-only dependencies; intentionally software Vulkan for this cloud.
. /workspace/.cache/docksr-cloud/env.sh
. /workspace/.cache/docksr-cloud/preview-env.sh
export DOCKSR_GAMESCOPE_LAB='''+shlex.quote(str(root))+'''
export PATH="$DOCKSR_GAMESCOPE_LAB/venv/bin:$DOCKSR_GAMESCOPE_LAB/prefix/usr/bin:$PATH"
export LD_LIBRARY_PATH="$DOCKSR_GAMESCOPE_LAB/prefix/usr/lib/x86_64-linux-gnu:$LD_LIBRARY_PATH"
export PKG_CONFIG_PATH="$DOCKSR_GAMESCOPE_LAB/prefix/usr/lib/x86_64-linux-gnu/pkgconfig:$DOCKSR_GAMESCOPE_LAB/prefix/usr/share/pkgconfig:$DOCKSR_VULKAN_ROOT/lib/x86_64-linux-gnu/pkgconfig:${PKG_CONFIG_PATH:-}"
export CMAKE_PREFIX_PATH="$DOCKSR_GAMESCOPE_LAB/prefix/usr:$DOCKSR_VULKAN_ROOT:${CMAKE_PREFIX_PATH:-}"
'''
path = root/'env.sh'
path.write_text(text)
path.chmod(0o700)
PY
"$lab_root/venv/bin/meson" --version
printf '%s\n' "Dependency setup complete. Source $lab_root/env.sh in the build shell."

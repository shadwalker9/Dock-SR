#!/usr/bin/env bash
set -euo pipefail
cd /workspace/Dock-SR
python3 scripts/bootstrap_cloud.py
python3 scripts/bootstrap_preview.py --with-test-tools
source /workspace/.cache/docksr-cloud/env.sh
source /workspace/.cache/docksr-cloud/preview-env.sh
cmake -S . -B build-preview -G Ninja -DCMAKE_BUILD_TYPE=Release \
  -DBUILD_PREVIEW=ON \
  -DDOCKSR_REQUIRE_VULKAN=ON \
  -DPython3_EXECUTABLE=/workspace/.venvs/docksr-host/bin/python \
  -DVulkan_INCLUDE_DIR="$DOCKSR_VULKAN_ROOT/include" \
  -DVulkan_LIBRARY="$DOCKSR_VULKAN_ROOT/lib/x86_64-linux-gnu/libvulkan.so.1" \
  -DVulkan_GLSLANG_VALIDATOR_EXECUTABLE="$DOCKSR_VULKAN_ROOT/bin/glslangValidator" \
  -DX11_X11_INCLUDE_PATH="$DOCKSR_PREVIEW_ROOT/include" \
  -DX11_X11_LIB="$DOCKSR_PREVIEW_ROOT/lib/x86_64-linux-gnu/libX11.so"
cmake --build build-preview --parallel 2
ctest --test-dir build-preview --output-on-failure

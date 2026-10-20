# AMD interoperability gate

The source audit establishes real import plumbing, not a passing Linux graphics/inference roundtrip. No XDNA execution or target performance result is available in this environment.

## Memory and graph binding

For the smallest experiment, allocate persistent linear input/output `VkBuffer` objects rather than importing optimal-tiled swapchain images. Query the exact storage/transfer usages with `vkGetPhysicalDeviceExternalBufferProperties` and the DMA_BUF handle type. Chain `VkExternalMemoryBufferCreateInfo`, allocate with `VkExportMemoryAllocateInfo` and required dedicated information, bind, then export with `vkGetMemoryFdKHR`.

The reviewed native XRT path imports via `xrt::bo(device, export_handle)` / `xrtBOImport`. The XDNA shim issues `DRM_IOCTL_PRIME_FD_TO_HANDLE`; the driver attaches/maps the dma-buf. Reviewed paired XRT argument handling preserves imported backing rather than remapping to another memory bank. Exporter mmap/addressability and graph ABI can still fail, and native BO support does not prove ONNX-provider external device-buffer binding.

Reviewed upstream Linux 6.14 and 6.15 lack the PRIME import implementation present by 6.16. A version number alone does not guarantee a working current runtime: verify the actual distro's backports, ioctls, firmware and userspace pairing. Containers cannot supply missing host kernel/firmware support.

## Ordering and ownership

The NPU is a foreign device/driver. Use the appropriate `VK_QUEUE_FAMILY_FOREIGN_EXT` ownership and availability/visibility protocol, not an assumption that a shared FD synchronizes devices. A first host-mediated experiment can wait for GPU completion, run/wait the NPU, and submit a Vulkan acquire/consumer, without copying full image tensors on the host.

The reviewed XRT fence export uses `DRM_IOCTL_SYNCOBJ_HANDLE_TO_FD` with flags zero: an opaque DRM syncobj FD, not a `sync_file`. It must not be passed directly as Vulkan `SYNC_FD`. Any direct fence bridge needs valid point handling, compatible import/export and actual execution-fence evidence. Cache maintenance alone is also not an execution dependency.

## Required proof

Use an output-changing tiny transform and changing inputs so a compiled-away identity cannot pass. Show actual NPU dispatch and completion, GPU-produced data and GPU-consumed output. Keep allocations/imports persistent. Check all results, slot generations, consumer retirement, resource counts and error paths. Audit hidden copies and corroborate with traces; syscall absence alone cannot exclude an in-process copy.

Only then collect warm/cold timing separately, handoff and inference p50/p95/p99, actual overlap under GPU load, frame age and package/system power. A small-vector pass is not useful SR, and a software-Vulkan result does not satisfy the AMD hardware gate.

## Audited primary-source revisions

- [AMD xdna-driver](https://github.com/amd/xdna-driver/tree/0140477afa9d6bc41e53afc19810d1e0d71336d0): shim/device/buffer/platform and driver GEM paths.
- [Paired XRT](https://github.com/Xilinx/XRT/tree/1ea5176dbcdd31bb1cbe035661f1127e2be22574): BO import and kernel argument validation.
- [Vulkan specification](https://github.com/KhronosGroup/Vulkan-Docs/tree/193ebe195f47ffc5004683d1659e71c725658c4d): external memory, FOREIGN ownership and synchronization contracts.
- [Linux v6.16 GEM source](https://github.com/torvalds/linux/blob/038d61fd642278bab63ee8ef722c50d10ab01e8f/drivers/accel/amdxdna/amdxdna_gem.c): import plumbing, compared with preceding release sources.

These are source-audit pins, not a recommended arbitrarily mixed runtime installation. Current Microsoft Auto SR preview details, release-specific AMD Linux support and some vendor/model-card timing claims remain unverified because primary documentation requests were proxy-blocked during onboarding. The independently verified source primitives justify an experiment, not a shipping or zero-copy claim.

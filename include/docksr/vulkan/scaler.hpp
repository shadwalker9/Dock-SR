#pragma once

#include <docksr/image/image.hpp>

#include <cstdint>
#include <memory>
#include <optional>
#include <stdexcept>
#include <string>

namespace docksr::vulkan {
enum class DeviceEvidence { PhysicalGPU, Software, Unknown };

class Unavailable : public std::runtime_error {
public:
    using std::runtime_error::runtime_error;
};

struct ScaleResult {
    image::Image image;
    DeviceEvidence evidence{DeviceEvidence::Unknown};
    std::string device_name;
    std::optional<double> gpu_ms;
    // Entire synchronous scale call: RGB packing, dispatch, RGB readback and any
    // size-change resource configuration. This is not GPU time or game latency.
    double host_ms{};
};

// Single-owner synchronous scaler. Input RGB bytes are never modified.
// Existing Vulkan storage-buffer shader/pipeline implementation is shared with
// docksr-bench. Same-size calls reuse GPU resources; size changes reconfigure.
class Scaler {
public:
    Scaler();
    ~Scaler();
    Scaler(const Scaler&) = delete;
    Scaler& operator=(const Scaler&) = delete;
    ScaleResult scale(const image::Image& input, std::uint32_t width,
                      std::uint32_t height, image::Filter filter);

private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
};
} // namespace docksr::vulkan

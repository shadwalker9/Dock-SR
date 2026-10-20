#include <docksr/vulkan/scaler.hpp>

#include "engine.hpp"

#include <chrono>
#include <utility>
#include <vector>

namespace docksr::vulkan {
namespace {
constexpr std::uint64_t preview_fence_timeout_ns = 5'000'000'000ULL;

DeviceEvidence classify(VkPhysicalDeviceType type) {
    switch (type) {
    case VK_PHYSICAL_DEVICE_TYPE_DISCRETE_GPU:
    case VK_PHYSICAL_DEVICE_TYPE_INTEGRATED_GPU: return DeviceEvidence::PhysicalGPU;
    case VK_PHYSICAL_DEVICE_TYPE_CPU: return DeviceEvidence::Software;
    default: return DeviceEvidence::Unknown;
    }
}

bool same_shape(const ScaleConfiguration& left, const ScaleConfiguration& right) {
    return left.input_width == right.input_width && left.input_height == right.input_height &&
           left.output_width == right.output_width && left.output_height == right.output_height;
}
} // namespace

struct Scaler::Impl {
    detail::Context context;
    std::vector<std::uint32_t> shader = detail::load_shader();
    std::vector<std::uint32_t> packed_input;
    std::optional<ScaleConfiguration> configured;

    Impl() { context.initialize_device(); }
};

Scaler::Scaler() : impl_(std::make_unique<Impl>()) {}
Scaler::~Scaler() = default;

ScaleResult Scaler::scale(const image::Image& input, std::uint32_t width,
                         std::uint32_t height, image::Filter filter) {
    image::validate(input);
    const auto output_bytes = image::checked_rgb_bytes(width, height);
    if (filter != image::Filter::Nearest && filter != image::Filter::Bilinear) {
        throw std::invalid_argument("Unknown Vulkan image filter");
    }
    auto& state = *impl_;
    if (state.context.in_flight) {
        throw std::runtime_error("Vulkan scaler is unavailable after an incomplete dispatch; use a CPU fallback");
    }
    const auto started = std::chrono::steady_clock::now();
    const ScaleConfiguration configuration{input.width, input.height, width, height,
                                           filter == image::Filter::Nearest ? 0U : 1U};
    if (!state.configured || !same_shape(*state.configured, configuration)) {
        state.configured.reset();
        state.context.release_scaler();
        state.context.initialize_scaler(configuration, state.shader);
        state.configured = configuration;
    }
    const auto input_pixels = std::size_t(input.width) * input.height;
    state.packed_input.resize(input_pixels);
    for (std::size_t pixel = 0; pixel < input_pixels; ++pixel) {
        const auto offset = pixel * 3U;
        state.packed_input[pixel] = std::uint32_t(input.rgb[offset]) |
                                   (std::uint32_t(input.rgb[offset + 1]) << 8U) |
                                   (std::uint32_t(input.rgb[offset + 2]) << 16U) | 0xff000000U;
    }
    const auto sample = detail::dispatch(state.context, configuration, state.packed_input, 0, 0,
                                         preview_fence_timeout_ns);
    image::Image output{width, height, std::vector<std::uint8_t>(output_bytes)};
    const auto* rgba = static_cast<const std::uint32_t*>(state.context.output.mapped);
    for (std::size_t pixel = 0; pixel < std::size_t(width) * height; ++pixel) {
        const auto value = rgba[pixel];
        output.rgb[pixel * 3U] = static_cast<std::uint8_t>(value & 255U);
        output.rgb[pixel * 3U + 1] = static_cast<std::uint8_t>((value >> 8U) & 255U);
        output.rgb[pixel * 3U + 2] = static_cast<std::uint8_t>((value >> 16U) & 255U);
    }
    const double host_ms = std::chrono::duration<double, std::milli>(
        std::chrono::steady_clock::now() - started).count();
    return {std::move(output), classify(state.context.properties.deviceType),
            state.context.properties.deviceName, sample.gpu_ms, host_ms};
}
} // namespace docksr::vulkan

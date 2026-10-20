#pragma once

#include <cstdint>

namespace docksr::vulkan {
// Keep this in the same order as the push-constant block in shaders/scale.comp.
struct ScaleConfiguration {
    std::uint32_t input_width;
    std::uint32_t input_height;
    std::uint32_t output_width;
    std::uint32_t output_height;
    std::uint32_t filter_kind;
};
static_assert(sizeof(ScaleConfiguration) == 20);
} // namespace docksr::vulkan

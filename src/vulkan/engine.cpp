#include "engine.hpp"

#include <fstream>

namespace docksr::vulkan::detail {
std::vector<std::uint32_t> load_shader() {
    std::ifstream stream(DOCKSR_SHADER_PATH, std::ios::binary | std::ios::ate);
    if (!stream) throw std::runtime_error("Cannot open compiled shader: " DOCKSR_SHADER_PATH);
    const auto bytes = stream.tellg();
    if (bytes <= 0 || bytes > 16 * 1024 * 1024 || bytes % 4 != 0) {
        throw std::runtime_error("Invalid SPIR-V shader size");
    }
    std::vector<std::uint32_t> shader(static_cast<std::size_t>(bytes) / 4U);
    stream.seekg(0);
    stream.read(reinterpret_cast<char*>(shader.data()), bytes);
    if (!stream || shader.front() != 0x07230203U) throw std::runtime_error("Invalid or truncated SPIR-V shader");
    return shader;
}

} // namespace docksr::vulkan::detail

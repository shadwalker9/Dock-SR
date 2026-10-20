#include "engine.hpp"

#include <filesystem>
#include <fstream>

namespace docksr::vulkan::detail {
namespace {
std::filesystem::path shader_path() {
    std::error_code error;
    const auto executable = std::filesystem::read_symlink("/proc/self/exe", error);
    if (error || !executable.is_absolute()) {
        throw std::runtime_error("Cannot locate executable for packaged shader lookup");
    }
    const auto bundled = (executable.parent_path() / "../share/docksr/scale.comp.spv").lexically_normal();
    if (std::filesystem::exists(bundled, error)) return bundled;
    if (error) throw std::runtime_error("Cannot inspect packaged shader: " + bundled.string());

    // CMake places executable targets in <build>/bin and the generated shader
    // in <build>/src/vulkan. Only that original build tree may use its absolute
    // path. A relocated bundle must never borrow a missing asset from a build.
    const auto build_shader = std::filesystem::weakly_canonical(DOCKSR_SHADER_PATH, error);
    if (!error) {
        const auto build_bin = build_shader.parent_path().parent_path().parent_path() / "bin";
        const auto executable_directory = std::filesystem::weakly_canonical(executable.parent_path(), error);
        if (!error && executable_directory == build_bin) return build_shader;
    }
    throw std::runtime_error("Cannot open packaged shader: " + bundled.string());
}
} // namespace

std::vector<std::uint32_t> load_shader() {
    const auto path = shader_path();
    std::ifstream stream(path, std::ios::binary | std::ios::ate);
    if (!stream) throw std::runtime_error("Cannot open compiled shader: " + path.string());
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

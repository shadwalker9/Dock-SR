#pragma once

#include <cstddef>
#include <cstdint>
#include <filesystem>
#include <string_view>
#include <vector>

namespace docksr::image {
inline constexpr std::uint32_t maximum_dimension = 8192;
inline constexpr std::uint64_t maximum_pixels = 16'777'216;

struct Image {
    std::uint32_t width{};
    std::uint32_t height{};
    std::vector<std::uint8_t> rgb;
};

enum class Filter { Nearest, Bilinear };
Filter parse_filter(std::string_view name);
std::string_view filter_name(Filter filter);
// Throws on invalid dimensions or inconsistent image storage; multiplication is checked.
std::size_t checked_rgb_bytes(std::uint32_t width, std::uint32_t height);
void validate(const Image& image);

// Binary P6 only: maxval=255, bounded comments/header, exact raster length.
// One raster separator is consumed (CRLF is accepted as one line ending).
Image read_ppm(const std::filesystem::path& path);
// Publishes a completed 0600 file without replacing an existing destination.
// An output is considered complete only when this function returns successfully.
void write_ppm_exclusive(const std::filesystem::path& path, const Image& image);

// Pixel-center sampling, clamped borders, RGB byte-domain interpolation.
// Bilinear rounds half up using exact integer weights; no color-space conversion.
Image resize(const Image& input, std::uint32_t width, std::uint32_t height, Filter filter);
Image generate_pattern(std::uint32_t width = 1280, std::uint32_t height = 720);
} // namespace docksr::image

#include <docksr/image/image.hpp>

#include <algorithm>
#include <cerrno>
#include <charconv>
#include <cstring>
#include <fstream>
#include <limits>
#include <stdexcept>
#include <string>
#include <system_error>
#include <vector>

#include <fcntl.h>
#include <sys/stat.h>
#include <unistd.h>

namespace docksr::image {
namespace {
constexpr std::size_t maximum_header_bytes = 65'536;

bool whitespace(unsigned char value) {
    return value == ' ' || value == '\t' || value == '\r' || value == '\n' || value == '\v' || value == '\f';
}

class HeaderParser {
public:
    explicit HeaderParser(const std::vector<std::uint8_t>& bytes) : bytes_(bytes) {}

    std::string_view token() {
        skip_header_whitespace();
        const auto start = position_;
        while (position_ < bytes_.size() && !whitespace(bytes_[position_]) && bytes_[position_] != '#') {
            ++position_;
            check_limit();
        }
        if (start == position_) throw std::runtime_error("PPM header is missing a token");
        return {reinterpret_cast<const char*>(bytes_.data() + start), position_ - start};
    }

    std::size_t raster_position(std::size_t expected_raster_bytes) {
        if (position_ >= bytes_.size() || !whitespace(bytes_[position_])) {
            throw std::runtime_error("PPM maxval must be followed by a raster separator");
        }
        // Exact length disambiguates a CRLF header from a single CR separator
        // followed by a legitimate LF-valued first raster byte.
        if (bytes_[position_] == '\r' && position_ + 1 < bytes_.size() && bytes_[position_ + 1] == '\n' &&
            bytes_.size() - position_ - 2U == expected_raster_bytes) {
            position_ += 2;
        } else {
            ++position_;
        }
        check_limit();
        return position_;
    }

private:
    void check_limit() const {
        if (position_ > maximum_header_bytes) throw std::runtime_error("PPM header exceeds 65536 bytes");
    }

    void skip_header_whitespace() {
        while (position_ < bytes_.size()) {
            if (whitespace(bytes_[position_])) {
                ++position_;
            } else if (bytes_[position_] == '#') {
                while (position_ < bytes_.size() && bytes_[position_] != '\n' && bytes_[position_] != '\r') {
                    ++position_;
                    check_limit();
                }
            } else {
                return;
            }
            check_limit();
        }
    }

    const std::vector<std::uint8_t>& bytes_;
    std::size_t position_{};
};

std::uint32_t header_number(std::string_view token, std::string_view name) {
    std::uint32_t value = 0;
    const auto [end, error] = std::from_chars(token.data(), token.data() + token.size(), value);
    if (token.empty() || error != std::errc{} || end != token.data() + token.size()) {
        throw std::runtime_error("PPM " + std::string(name) + " must be a nonnegative decimal integer");
    }
    return value;
}

struct AxisSample {
    std::uint32_t lower;
    std::uint32_t upper;
    std::uint64_t weight;
};

std::vector<AxisSample> bilinear_axis(std::uint32_t input_size, std::uint32_t output_size) {
    std::vector<AxisSample> samples(output_size);
    const auto denominator = std::int64_t(2) * output_size;
    for (std::uint32_t position = 0; position < output_size; ++position) {
        const auto numerator = (std::int64_t(2) * position + 1) * input_size - output_size;
        auto lower = numerator / denominator;
        if (numerator % denominator < 0) --lower; // Mathematical floor, not truncation toward zero.
        const auto weight = static_cast<std::uint64_t>(numerator - lower * denominator);
        const auto clamp = [&](std::int64_t coordinate) {
            return static_cast<std::uint32_t>(std::clamp<std::int64_t>(coordinate, 0, input_size - 1));
        };
        samples[position] = {clamp(lower), clamp(lower + 1), weight};
    }
    return samples;
}

void write_all(int descriptor, const void* data, std::size_t bytes) {
    const auto* cursor = static_cast<const std::uint8_t*>(data);
    while (bytes > 0) {
        const auto written = ::write(descriptor, cursor, bytes);
        if (written < 0 && errno == EINTR) continue;
        if (written <= 0) throw std::system_error(errno ? errno : EIO, std::generic_category(), "Write PPM output");
        cursor += written;
        bytes -= static_cast<std::size_t>(written);
    }
}
} // namespace

Filter parse_filter(std::string_view name) {
    if (name == "nearest") return Filter::Nearest;
    if (name == "bilinear") return Filter::Bilinear;
    throw std::invalid_argument("Filter must be nearest or bilinear");
}

std::string_view filter_name(Filter filter) {
    switch (filter) {
    case Filter::Nearest: return "nearest";
    case Filter::Bilinear: return "bilinear";
    }
    throw std::invalid_argument("Unknown image filter");
}

std::size_t checked_rgb_bytes(std::uint32_t width, std::uint32_t height) {
    if (width == 0 || height == 0 || width > maximum_dimension || height > maximum_dimension) {
        throw std::invalid_argument("Image dimensions must be in [1, 8192]");
    }
    const auto pixels = std::uint64_t(width) * height;
    if (pixels > maximum_pixels || pixels > std::numeric_limits<std::size_t>::max() / 3U) {
        throw std::invalid_argument("Image exceeds the 16777216-pixel allocation limit");
    }
    return static_cast<std::size_t>(pixels * 3U);
}

void validate(const Image& image) {
    if (image.rgb.size() != checked_rgb_bytes(image.width, image.height)) {
        throw std::invalid_argument("Image RGB storage does not match its dimensions");
    }
}

Image read_ppm(const std::filesystem::path& path) {
    if (!std::filesystem::is_regular_file(path)) throw std::runtime_error("PPM input must be a regular file");
    std::ifstream stream(path, std::ios::binary | std::ios::ate);
    if (!stream) throw std::runtime_error("Cannot open PPM input: " + path.string());
    const auto byte_count = stream.tellg();
    constexpr auto maximum_file_bytes = maximum_pixels * 3U + maximum_header_bytes;
    if (byte_count <= 0 || static_cast<std::uint64_t>(byte_count) > maximum_file_bytes) {
        throw std::runtime_error("PPM file is empty or exceeds the bounded input size");
    }
    std::vector<std::uint8_t> bytes(static_cast<std::size_t>(byte_count));
    stream.seekg(0);
    stream.read(reinterpret_cast<char*>(bytes.data()), static_cast<std::streamsize>(bytes.size()));
    if (!stream) throw std::runtime_error("PPM input changed size or was truncated while reading");
    HeaderParser parser(bytes);
    if (parser.token() != "P6") throw std::runtime_error("Only binary P6 PPM input is supported");
    const auto width = header_number(parser.token(), "width");
    const auto height = header_number(parser.token(), "height");
    const auto expected = checked_rgb_bytes(width, height);
    if (header_number(parser.token(), "maxval") != 255) throw std::runtime_error("PPM maxval must equal 255");
    const auto raster = parser.raster_position(expected);
    if (bytes.size() - raster != expected) throw std::runtime_error("PPM raster is truncated or has trailing bytes");
    return {width, height, {bytes.begin() + static_cast<std::ptrdiff_t>(raster), bytes.end()}};
}

void write_ppm_exclusive(const std::filesystem::path& path, const Image& image) {
    validate(image);
    if (path.empty() || path.filename().empty()) throw std::invalid_argument("PPM output filename is required");
    const auto parent = path.has_parent_path() ? path.parent_path() : std::filesystem::path(".");
    auto temporary_name = (parent / ".docksr-image-XXXXXX").string();
    std::vector<char> temporary(temporary_name.begin(), temporary_name.end());
    temporary.push_back('\0');
    int descriptor = ::mkstemp(temporary.data());
    if (descriptor < 0) throw std::system_error(errno, std::generic_category(), "Create private PPM temporary file");
    try {
        const std::string header = "P6\n" + std::to_string(image.width) + " " + std::to_string(image.height) + "\n255\n";
        write_all(descriptor, header.data(), header.size());
        write_all(descriptor, image.rgb.data(), image.rgb.size());
        if (::fsync(descriptor) != 0) throw std::system_error(errno, std::generic_category(), "Flush completed PPM output");
        const int closing = descriptor;
        descriptor = -1; // A failed close must not be retried: the descriptor can already be released.
        if (::close(closing) != 0) throw std::system_error(errno, std::generic_category(), "Close completed PPM output");
        // Hard-link publication is atomic and cannot replace an existing destination.
        if (::link(temporary.data(), path.c_str()) != 0) {
            throw std::system_error(errno, std::generic_category(), "Publish new PPM output without overwrite");
        }
        (void)::unlink(temporary.data());
    } catch (...) {
        if (descriptor >= 0) (void)::close(descriptor);
        (void)::unlink(temporary.data());
        throw;
    }
}

Image resize(const Image& input, std::uint32_t width, std::uint32_t height, Filter filter) {
    validate(input);
    Image output{width, height, std::vector<std::uint8_t>(checked_rgb_bytes(width, height))};
    if (filter == Filter::Nearest) {
        for (std::uint32_t y = 0; y < height; ++y) {
            const auto source_y = static_cast<std::uint32_t>((std::uint64_t(2) * y + 1) * input.height / (std::uint64_t(2) * height));
            for (std::uint32_t x = 0; x < width; ++x) {
                const auto source_x = static_cast<std::uint32_t>((std::uint64_t(2) * x + 1) * input.width / (std::uint64_t(2) * width));
                const auto source = (std::size_t(source_y) * input.width + source_x) * 3U;
                const auto target = (std::size_t(y) * width + x) * 3U;
                std::copy_n(input.rgb.begin() + static_cast<std::ptrdiff_t>(source), 3,
                            output.rgb.begin() + static_cast<std::ptrdiff_t>(target));
            }
        }
        return output;
    }
    if (filter != Filter::Bilinear) throw std::invalid_argument("Unknown image filter");
    const auto horizontal = bilinear_axis(input.width, width);
    const auto vertical = bilinear_axis(input.height, height);
    const auto denominator_x = std::uint64_t(2) * width;
    const auto denominator_y = std::uint64_t(2) * height;
    const auto denominator = denominator_x * denominator_y;
    for (std::uint32_t y = 0; y < height; ++y) {
        const auto& row = vertical[y];
        for (std::uint32_t x = 0; x < width; ++x) {
            const auto& column = horizontal[x];
            const auto top_left = (std::size_t(row.lower) * input.width + column.lower) * 3U;
            const auto top_right = (std::size_t(row.lower) * input.width + column.upper) * 3U;
            const auto bottom_left = (std::size_t(row.upper) * input.width + column.lower) * 3U;
            const auto bottom_right = (std::size_t(row.upper) * input.width + column.upper) * 3U;
            const auto target = (std::size_t(y) * width + x) * 3U;
            for (std::size_t channel = 0; channel < 3; ++channel) {
                const auto upper = std::uint64_t(input.rgb[top_left + channel]) * (denominator_x - column.weight) +
                                   std::uint64_t(input.rgb[top_right + channel]) * column.weight;
                const auto lower = std::uint64_t(input.rgb[bottom_left + channel]) * (denominator_x - column.weight) +
                                   std::uint64_t(input.rgb[bottom_right + channel]) * column.weight;
                const auto numerator = upper * (denominator_y - row.weight) + lower * row.weight;
                output.rgb[target + channel] = static_cast<std::uint8_t>((2U * numerator + denominator) / (2U * denominator));
            }
        }
    }
    return output;
}

Image generate_pattern(std::uint32_t width, std::uint32_t height) {
    Image image{width, height, std::vector<std::uint8_t>(checked_rgb_bytes(width, height))};
    for (std::uint32_t y = 0; y < height; ++y) {
        for (std::uint32_t x = 0; x < width; ++x) {
            const auto offset = (std::size_t(y) * width + x) * 3U;
            auto red = width > 1 ? x * 255U / (width - 1U) : 37U;
            auto green = height > 1 ? y * 255U / (height - 1U) : 109U;
            auto blue = ((x / 8U + y / 8U) & 1U) ? 32U : 211U;
            if (x < width / 3U && y < height / 3U) {
                const bool light = ((x / 3U) ^ (y / 3U)) & 1U;
                red = light ? 255U : 0U;
                green = light ? 184U : 12U;
                blue = light ? 32U : 232U;
            }
            if (x == width / 2U) red = green = blue = 255U;
            if (x >= width * 3U / 5U && y >= height / 5U && y <= height * 2U / 5U &&
                (y == height / 5U || y == height * 2U / 5U || x % 7U == 0)) {
                red = 17; green = 255; blue = 221;
            }
            image.rgb[offset] = static_cast<std::uint8_t>(red);
            image.rgb[offset + 1] = static_cast<std::uint8_t>(green);
            image.rgb[offset + 2] = static_cast<std::uint8_t>(blue);
        }
    }
    return image;
}
} // namespace docksr::image

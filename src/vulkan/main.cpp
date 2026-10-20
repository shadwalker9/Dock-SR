#include "engine.hpp"
#include <docksr/vulkan/benchmark.hpp>
#include <vulkan/vulkan.h>

#include <algorithm>
#include <array>
#include <charconv>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <limits>
#include <optional>
#include <sstream>
#include <stdexcept>
#include <string>
#include <string_view>
#include <vector>

namespace {
using docksr::vulkan::ScaleConfiguration;
using docksr::vulkan::Unavailable;
using docksr::vulkan::detail::Context;
using docksr::vulkan::detail::Sample;
using docksr::vulkan::detail::dispatch;
using docksr::vulkan::detail::load_shader;
constexpr std::uint64_t max_pixels = 16'777'216;
constexpr std::uint32_t max_dimension = 8192;

std::string json_string(std::string_view value) {
    std::ostringstream out;
    out << '"';
    for (const unsigned char character : value) {
        switch (character) {
        case '"': out << "\\\""; break;
        case '\\': out << "\\\\"; break;
        case '\n': out << "\\n"; break;
        case '\r': out << "\\r"; break;
        case '\t': out << "\\t"; break;
        default:
            if (character < 0x20) {
                out << "\\u" << std::hex << std::setw(4) << std::setfill('0')
                    << static_cast<unsigned>(character) << std::dec;
            } else {
                out << character;
            }
        }
    }
    out << '"';
    return out.str();
}

std::uint32_t parse_number(std::string_view value, std::string_view label,
                           std::uint32_t minimum, std::uint32_t maximum) {
    std::uint32_t parsed = 0;
    const auto [end, error] = std::from_chars(value.data(), value.data() + value.size(), parsed);
    if (value.empty() || error != std::errc{} || end != value.data() + value.size() ||
        parsed < minimum || parsed > maximum) {
        throw std::invalid_argument(std::string(label) + " must be an integer in [" +
                                    std::to_string(minimum) + ", " + std::to_string(maximum) + "]");
    }
    return parsed;
}

std::pair<std::uint32_t, std::uint32_t> parse_size(std::string_view text) {
    const auto separator = text.find('x');
    if (separator == std::string_view::npos) {
        throw std::invalid_argument("Resolution must be WIDTHxHEIGHT");
    }
    const auto width = parse_number(text.substr(0, separator), "width", 1, max_dimension);
    const auto height = parse_number(text.substr(separator + 1), "height", 1, max_dimension);
    if (std::uint64_t(width) * height > max_pixels) {
        throw std::invalid_argument("Each image is limited to 16,777,216 pixels");
    }
    return {width, height};
}

struct Options {
    ScaleConfiguration scaling{1280, 720, 1920, 1080, 1};
    std::string filter = "bilinear";
    std::uint32_t warmup = 3;
    std::uint32_t iterations = 10;
    std::filesystem::path artifact_dir = "docksr-artifacts";
    bool changing_frames = false;
    bool probe = false;
    bool help = false;
};

Options parse_options(int argc, char** argv) {
    Options options;
    for (int index = 1; index < argc; ++index) {
        const std::string_view flag(argv[index]);
        auto next = [&]() -> std::string_view {
            if (++index >= argc) {
                throw std::invalid_argument("Missing value for " + std::string(flag));
            }
            return argv[index];
        };
        if (flag == "--help" || flag == "-h") {
            options.help = true;
        } else if (flag == "--input" || flag == "--output") {
            const auto [width, height] = parse_size(next());
            if (flag == "--input") {
                options.scaling.input_width = width;
                options.scaling.input_height = height;
            } else {
                options.scaling.output_width = width;
                options.scaling.output_height = height;
            }
        } else if (flag == "--filter") {
            options.filter = next();
            if (options.filter != "nearest" && options.filter != "bilinear") {
                throw std::invalid_argument("Filter must be nearest or bilinear");
            }
            options.scaling.filter_kind = options.filter == "nearest" ? 0 : 1;
        } else if (flag == "--warmup") {
            options.warmup = parse_number(next(), "warmup", 0, 1000);
        } else if (flag == "--iterations") {
            options.iterations = parse_number(next(), "iterations", 1, 10'000);
        } else if (flag == "--artifact-dir") {
            options.artifact_dir = next();
            if (options.artifact_dir.empty()) {
                throw std::invalid_argument("Artifact directory cannot be empty");
            }
        } else if (flag == "--changing-frames") {
            options.changing_frames = true;
        } else if (flag == "--probe") {
            options.probe = true;
        } else {
            throw std::invalid_argument("Unknown option: " + std::string(flag));
        }
    }
    return options;
}

void print_help() {
    std::cout << "Dock SR headless Vulkan scaling control (not a game or NPU benchmark).\n"
                 "Usage: docksr-bench [options]\n"
                 "  --input WIDTHxHEIGHT     default 1280x720\n"
                 "  --output WIDTHxHEIGHT    default 1920x1080\n"
                 "  --filter nearest|bilinear  default bilinear\n"
                 "  --warmup N               0..1000, default 3\n"
                 "  --iterations N           1..10000, default 10\n"
                 "  --artifact-dir PATH      default docksr-artifacts; existing artifacts protected\n"
                 "  --changing-frames        move deterministic source pattern per dispatch\n"
                 "  --probe                  print device/external-buffer capabilities as JSON\n"
                 "Dimensions are 1..8192 with at most 16,777,216 pixels per image.\n"
                 "Nearest is center-sampled; bilinear uses pixel centers and clamped borders.\n"
                 "Output: result.json, samples.csv, input.ppm and output.ppm.\n";
}

std::string version_text(std::uint32_t version) {
    return std::to_string(VK_VERSION_MAJOR(version)) + "." +
           std::to_string(VK_VERSION_MINOR(version)) + "." +
           std::to_string(VK_VERSION_PATCH(version));
}

std::string device_type(VkPhysicalDeviceType type) {
    switch (type) {
    case VK_PHYSICAL_DEVICE_TYPE_CPU: return "cpu";
    case VK_PHYSICAL_DEVICE_TYPE_INTEGRATED_GPU: return "integrated_gpu";
    case VK_PHYSICAL_DEVICE_TYPE_DISCRETE_GPU: return "discrete_gpu";
    case VK_PHYSICAL_DEVICE_TYPE_VIRTUAL_GPU: return "virtual_gpu";
    default: return "other";
    }
}

std::string evidence_class(VkPhysicalDeviceType type) {
    switch (type) {
    case VK_PHYSICAL_DEVICE_TYPE_CPU: return "vulkan_software";
    case VK_PHYSICAL_DEVICE_TYPE_INTEGRATED_GPU:
    case VK_PHYSICAL_DEVICE_TYPE_DISCRETE_GPU: return "vulkan_hardware";
    default: return "vulkan_unknown";
    }
}

std::vector<std::uint32_t> make_pattern(std::uint32_t width, std::uint32_t height, std::uint32_t frame) {
    std::vector<std::uint32_t> pixels(std::size_t(width) * height);
    const auto motion = frame % std::max(1U, width);
    for (std::uint32_t y = 0; y < height; ++y) {
        for (std::uint32_t x = 0; x < width; ++x) {
            const auto moved_x = (x + motion) % width;
            std::uint32_t red = width > 1 ? moved_x * 255U / (width - 1U) : 37U;
            std::uint32_t green = height > 1 ? y * 255U / (height - 1U) : 109U;
            std::uint32_t blue = ((moved_x / 8U + y / 8U) & 1U) != 0 ? 28U : 211U;
            // Crisp edge and pixel-art region, with deterministic motion when requested.
            if (moved_x < width / 3U && y < height / 3U) {
                const bool tile = ((moved_x / 3U) ^ (y / 3U)) & 1U;
                red = tile ? 255U : 0U;
                green = tile ? 184U : 12U;
                blue = tile ? 32U : 232U;
            }
            if (moved_x == width / 2U) { red = 255; green = 255; blue = 255; }
            // UI-like outline, short text strokes and progress bar.
            const auto ui_left = width * 3U / 5U;
            const auto ui_top = height / 5U;
            const auto ui_bottom = height * 2U / 5U;
            if (x >= ui_left && y >= ui_top && y <= ui_bottom &&
                (y == ui_top || y == ui_bottom || x == ui_left ||
                 ((x - ui_left) % 7U == 0 && y <= ui_top + (ui_bottom - ui_top) / 2U))) {
                red = 17; green = 255; blue = 221;
            }
            const auto alpha = 32U + ((x + y + frame) % 224U);
            pixels[std::size_t(y) * width + x] = red | (green << 8U) | (blue << 16U) | (alpha << 24U);
        }
    }
    return pixels;
}

unsigned channel(std::uint32_t pixel, unsigned component) { return (pixel >> (component * 8U)) & 255U; }

unsigned reference_channel(const std::vector<std::uint32_t>& input, const ScaleConfiguration& configuration,
                           std::uint32_t x, std::uint32_t y, unsigned component) {
    const auto width = configuration.input_width;
    const auto height = configuration.input_height;
    if (configuration.filter_kind == 0) {
        const auto source_x = std::min<std::uint64_t>((std::uint64_t(2) * x + 1) * width /
                                                     (std::uint64_t(2) * configuration.output_width), width - 1);
        const auto source_y = std::min<std::uint64_t>((std::uint64_t(2) * y + 1) * height /
                                                     (std::uint64_t(2) * configuration.output_height), height - 1);
        return channel(input[std::size_t(source_y) * width + source_x], component);
    }
    const double source_x = (double(x) + 0.5) * width / configuration.output_width - 0.5;
    const double source_y = (double(y) + 0.5) * height / configuration.output_height - 0.5;
    const auto left = static_cast<std::int32_t>(std::floor(source_x));
    const auto top = static_cast<std::int32_t>(std::floor(source_y));
    const double weight_x = source_x - left;
    const double weight_y = source_y - top;
    auto sample = [&](std::int32_t sample_x, std::int32_t sample_y) {
        sample_x = std::clamp(sample_x, 0, static_cast<std::int32_t>(width) - 1);
        sample_y = std::clamp(sample_y, 0, static_cast<std::int32_t>(height) - 1);
        return double(channel(input[std::size_t(sample_y) * width + sample_x], component));
    };
    const double value = sample(left, top) * (1.0 - weight_x) * (1.0 - weight_y) +
                         sample(left + 1, top) * weight_x * (1.0 - weight_y) +
                         sample(left, top + 1) * (1.0 - weight_x) * weight_y +
                         sample(left + 1, top + 1) * weight_x * weight_y;
    return static_cast<unsigned>(std::floor(std::clamp(value, 0.0, 255.0) + 0.5));
}

unsigned check_output(const std::vector<std::uint32_t>& input, const std::uint32_t* output,
                      const ScaleConfiguration& configuration) {
    unsigned maximum_error = 0;
    for (std::uint32_t y = 0; y < configuration.output_height; ++y) {
        for (std::uint32_t x = 0; x < configuration.output_width; ++x) {
            for (unsigned component = 0; component < 4; ++component) {
                const auto expected = reference_channel(input, configuration, x, y, component);
                const auto actual = channel(output[std::size_t(y) * configuration.output_width + x], component);
                const auto error = actual > expected ? actual - expected : expected - actual;
                maximum_error = std::max(maximum_error, error);
            }
        }
    }
    return maximum_error;
}

std::string fnv1a64(const void* data, std::size_t size) {
    std::uint64_t digest = 14695981039346656037ULL;
    const auto* bytes = static_cast<const unsigned char*>(data);
    for (std::size_t index = 0; index < size; ++index) {
        digest ^= bytes[index];
        digest *= 1099511628211ULL;
    }
    std::ostringstream output;
    output << std::hex << std::setfill('0') << std::setw(16) << digest;
    return output.str();
}

std::string save_ppm(const std::filesystem::path& path, std::uint32_t width, std::uint32_t height,
                     const std::uint32_t* pixels) {
    std::string bytes = "P6\n" + std::to_string(width) + " " + std::to_string(height) + "\n255\n";
    bytes.reserve(bytes.size() + std::size_t(width) * height * 3U);
    for (std::size_t index = 0; index < std::size_t(width) * height; ++index) {
        for (unsigned component = 0; component < 3; ++component) {
            bytes.push_back(static_cast<char>(channel(pixels[index], component)));
        }
    }
    std::ofstream stream(path, std::ios::binary);
    stream.write(bytes.data(), static_cast<std::streamsize>(bytes.size()));
    stream.close();
    if (!stream) throw std::runtime_error("Cannot write capture: " + path.string());
    return fnv1a64(bytes.data(), bytes.size());
}

std::string summary_json(std::vector<double> values) {
    if (values.empty()) return "null";
    std::sort(values.begin(), values.end());
    auto quantile = [&](double fraction) {
        const auto rank = static_cast<std::size_t>(std::ceil(fraction * double(values.size())));
        return values[std::max<std::size_t>(1, rank) - 1];
    };
    std::ostringstream out;
    out << std::setprecision(12) << "{\"min\":" << values.front() << ",\"p50\":" << quantile(0.5)
        << ",\"p95\":" << quantile(0.95) << ",\"p99\":" << quantile(0.99) << ",\"max\":" << values.back() << '}';
    return out.str();
}

std::string device_json(const Context& context) {
    std::ostringstream out;
    out << "{\"name\":" << json_string(context.properties.deviceName)
        << ",\"type\":" << json_string(device_type(context.properties.deviceType))
        << ",\"vendor_id\":" << context.properties.vendorID << ",\"device_id\":" << context.properties.deviceID
        << ",\"api_version\":" << json_string(version_text(context.properties.apiVersion))
        << ",\"driver_version\":" << context.properties.driverVersion
        << ",\"driver_name\":" << json_string(context.driver_name)
        << ",\"driver_info\":" << json_string(context.driver_info)
        << ",\"queue_family\":" << context.family
        << ",\"timestamp_valid_bits\":" << context.family_properties.timestampValidBits
        << ",\"timestamp_period_ns\":" << context.properties.limits.timestampPeriod
        << ",\"timestamps_enabled\":" << (context.timestamps ? "true" : "false") << '}';
    return out.str();
}

void save_results(const Options& options, const Context& context, const std::vector<Sample>& samples,
                  const std::vector<std::uint32_t>& input, const std::vector<std::uint32_t>& shader,
                  unsigned maximum_error) {
    const auto input_hash = save_ppm(options.artifact_dir / "input.ppm", options.scaling.input_width,
                                     options.scaling.input_height, input.data());
    const auto output_hash = save_ppm(options.artifact_dir / "output.ppm", options.scaling.output_width,
                                      options.scaling.output_height, static_cast<const std::uint32_t*>(context.output.mapped));
    std::ofstream csv(options.artifact_dir / "samples.csv");
    csv << "sample_index,host_dispatch_to_completion_ms,gpu_dispatch_ms,input_frame_index\n" << std::setprecision(12);
    std::vector<double> host_times;
    std::vector<double> gpu_times;
    for (const auto& sample : samples) {
        csv << sample.index << ',' << sample.host_ms << ',';
        if (sample.gpu_ms) { csv << *sample.gpu_ms; gpu_times.push_back(*sample.gpu_ms); }
        csv << ',' << sample.frame << '\n';
        host_times.push_back(sample.host_ms);
    }
    csv.close();
    if (!csv) throw std::runtime_error("Cannot write samples.csv");
    const auto& scale = options.scaling;
    const unsigned allowed_error = scale.filter_kind == 0 ? 0U : 1U;
    std::ofstream out(options.artifact_dir / "result.json");
    out << std::setprecision(12)
        << "{\n  \"schema_version\":\"1.0.0\",\n  \"benchmark\":\"docksr-vulkan-scaler\",\n"
        << "  \"evidence_class\":" << json_string(evidence_class(context.properties.deviceType)) << ",\n"
        << "  \"device\":" << device_json(context) << ",\n"
        << "  \"configuration\":{\"input_width\":" << scale.input_width << ",\"input_height\":" << scale.input_height
        << ",\"output_width\":" << scale.output_width << ",\"output_height\":" << scale.output_height
        << ",\"filter\":" << json_string(options.filter) << ",\"warmup_iterations\":" << options.warmup
        << ",\"measured_iterations\":" << options.iterations << ",\"changing_frames\":" << (options.changing_frames ? "true" : "false")
        << ",\"pattern\":\"gradient-edge-ui-pixel-art-v1\",\"final_input_frame_index\":" << samples.back().frame << "},\n"
        << "  \"timings\":{\"host_dispatch_to_completion_ms\":" << summary_json(host_times)
        << ",\"gpu_dispatch_ms\":" << summary_json(gpu_times)
        << ",\"timestamp_status\":" << json_string(context.timestamp_status)
        << ",\"quantile_method\":\"nearest-rank; measured iterations only\""
        << ",\"host_scope\":\"Mapped input upload and cache flush, command recording/submission, fence wait and output cache invalidation; excludes source generation, CPU reference checking, capture writes and final CPU copy.\""
        << ",\"gpu_scope\":\"Device timestamp bracket around vkCmdDispatch (TOP_OF_PIPE to BOTTOM_OF_PIPE); may include dependency stalls. No host timings substituted.\"},\n"
        << "  \"correctness\":{\"passed\":" << (maximum_error <= allowed_error ? "true" : "false")
        << ",\"max_absolute_error\":" << maximum_error << ",\"allowed_absolute_error\":" << allowed_error
        << ",\"channels_compared\":" << std::uint64_t(scale.output_width) * scale.output_height * 4
        << ",\"scope\":\"Full RGBA comparison of final measured dispatch against independent CPU pixel formulas.\"},\n"
        << "  \"metrics\":{\"power_w\":null,\"game_internal_render_ms\":null,\"npu_ms\":null,\"game_fps\":null},\n"
        << "  \"limitations\":[\"This is a standalone scaling control, not game, temporal reconstruction or NPU evidence.\","
        << "\"No physical GPU is established when evidence_class is vulkan_software or vulkan_unknown.\","
        << "\"Power, game FPS, game internal render time and NPU time were not measured.\","
        << "\"Persistent host-visible storage buffers are used; this does not test graphics-image capture, presentation, DMA-BUF or zero-copy inference.\","
        << "\"Manual storage-buffer interpolation is a reference control, not an optimized texture-sampling or Gamescope performance baseline.\","
        << "\"PPM captures contain RGB only; the internal correctness check also covers alpha. Sampling is byte-domain, without color transfer or premultiplication.\"],\n"
        << "  \"artifacts\":{\"input\":{\"path\":\"input.ppm\",\"hash\":{\"algorithm\":\"fnv1a64\",\"value\":" << json_string(input_hash)
        << "}},\"output\":{\"path\":\"output.ppm\",\"hash\":{\"algorithm\":\"fnv1a64\",\"value\":" << json_string(output_hash)
        << "}},\"samples\":{\"path\":\"samples.csv\",\"format\":\"csv\",\"columns\":[\"sample_index\",\"host_dispatch_to_completion_ms\",\"gpu_dispatch_ms\",\"input_frame_index\"]},"
        << "\"shader\":{\"hash\":{\"algorithm\":\"fnv1a64\",\"value\":"
        << json_string(fnv1a64(shader.data(), shader.size() * sizeof(std::uint32_t))) << "}}}\n}\n";
    out.close();
    if (!out) throw std::runtime_error("Cannot write result.json");
}

void print_probe(const Context& context) {
    const bool dma_buf_extension = context.has_extension(VK_EXT_EXTERNAL_MEMORY_DMA_BUF_EXTENSION_NAME);
    VkPhysicalDeviceExternalBufferInfo buffer_info{};
    buffer_info.sType = VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_EXTERNAL_BUFFER_INFO;
    buffer_info.flags = 0;
    buffer_info.usage = VK_BUFFER_USAGE_STORAGE_BUFFER_BIT | VK_BUFFER_USAGE_TRANSFER_SRC_BIT | VK_BUFFER_USAGE_TRANSFER_DST_BIT;
    buffer_info.handleType = VK_EXTERNAL_MEMORY_HANDLE_TYPE_DMA_BUF_BIT_EXT;
    VkExternalBufferProperties buffer_properties{};
    buffer_properties.sType = VK_STRUCTURE_TYPE_EXTERNAL_BUFFER_PROPERTIES;
    if (dma_buf_extension) vkGetPhysicalDeviceExternalBufferProperties(context.physical, &buffer_info, &buffer_properties);
    const auto features = buffer_properties.externalMemoryProperties.externalMemoryFeatures;
    const bool semaphore_extension = context.has_extension(VK_KHR_EXTERNAL_SEMAPHORE_FD_EXTENSION_NAME);
    VkPhysicalDeviceExternalSemaphoreInfo semaphore_info{};
    semaphore_info.sType = VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_EXTERNAL_SEMAPHORE_INFO;
    semaphore_info.handleType = VK_EXTERNAL_SEMAPHORE_HANDLE_TYPE_SYNC_FD_BIT;
    VkExternalSemaphoreProperties semaphore_properties{};
    semaphore_properties.sType = VK_STRUCTURE_TYPE_EXTERNAL_SEMAPHORE_PROPERTIES;
    if (semaphore_extension) vkGetPhysicalDeviceExternalSemaphoreProperties(context.physical, &semaphore_info, &semaphore_properties);
    const auto semaphore_features = semaphore_properties.externalSemaphoreFeatures;
    const bool fence_extension = context.has_extension(VK_KHR_EXTERNAL_FENCE_FD_EXTENSION_NAME);
    VkPhysicalDeviceExternalFenceInfo fence_info{};
    fence_info.sType = VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_EXTERNAL_FENCE_INFO;
    fence_info.handleType = VK_EXTERNAL_FENCE_HANDLE_TYPE_SYNC_FD_BIT;
    VkExternalFenceProperties fence_properties{};
    fence_properties.sType = VK_STRUCTURE_TYPE_EXTERNAL_FENCE_PROPERTIES;
    if (fence_extension) vkGetPhysicalDeviceExternalFenceProperties(context.physical, &fence_info, &fence_properties);
    const auto fence_features = fence_properties.externalFenceFeatures;
    auto boolean = [](bool value) { return value ? "true" : "false"; };
    std::cout << "{\n  \"schema_version\":\"1.0.0\",\n  \"probe\":\"docksr-vulkan-capabilities\",\n"
              << "  \"evidence_class\":" << json_string(evidence_class(context.properties.deviceType)) << ",\n"
              << "  \"device\":" << device_json(context) << ",\n"
              << "  \"external_buffer\":{\"status\":" << json_string(dma_buf_extension ? "queried" : "unsupported")
              << ",\"handle_type\":\"DMA_BUF\",\"usage\":[\"STORAGE_BUFFER\",\"TRANSFER_SRC\",\"TRANSFER_DST\"],"
              << "\"extension_supported\":" << boolean(dma_buf_extension)
              << ",\"exportable\":" << boolean((features & VK_EXTERNAL_MEMORY_FEATURE_EXPORTABLE_BIT) != 0)
              << ",\"importable\":" << boolean((features & VK_EXTERNAL_MEMORY_FEATURE_IMPORTABLE_BIT) != 0)
              << ",\"dedicated_only\":" << boolean((features & VK_EXTERNAL_MEMORY_FEATURE_DEDICATED_ONLY_BIT) != 0)
              << ",\"compatible_handle_types_raw\":" << buffer_properties.externalMemoryProperties.compatibleHandleTypes
              << ",\"export_from_imported_handle_types_raw\":" << buffer_properties.externalMemoryProperties.exportFromImportedHandleTypes << "},\n"
              << "  \"foreign_queue_family_extension_supported\":" << boolean(context.has_extension(VK_EXT_QUEUE_FAMILY_FOREIGN_EXTENSION_NAME)) << ",\n"
              << "  \"sync_fd\":{\"semaphore\":{\"extension_supported\":" << boolean(semaphore_extension)
              << ",\"exportable\":" << boolean((semaphore_features & VK_EXTERNAL_SEMAPHORE_FEATURE_EXPORTABLE_BIT) != 0)
              << ",\"importable\":" << boolean((semaphore_features & VK_EXTERNAL_SEMAPHORE_FEATURE_IMPORTABLE_BIT) != 0)
              << "},\"fence\":{\"extension_supported\":" << boolean(fence_extension)
              << ",\"exportable\":" << boolean((fence_features & VK_EXTERNAL_FENCE_FEATURE_EXPORTABLE_BIT) != 0)
              << ",\"importable\":" << boolean((fence_features & VK_EXTERNAL_FENCE_FEATURE_IMPORTABLE_BIT) != 0) << "}},\n"
              << "  \"limitations\":[\"Capability queries only; no memory handle was exported or imported.\","
              << "\"No XRT, NPU inference, device-to-device synchronization or Linux graphics interop was exercised.\","
              << "\"A software Vulkan driver does not establish target handheld support.\"]\n}\n";
}

int run(const Options& options) {
    Context context;
    context.initialize_device();
    if (options.probe) {
        print_probe(context);
        return 0;
    }
    std::filesystem::create_directories(options.artifact_dir);
    for (const auto* name : {"input.ppm", "output.ppm", "samples.csv", "result.json"}) {
        if (std::filesystem::exists(options.artifact_dir / name)) {
            throw std::runtime_error("Refusing to overwrite existing artifact: " + (options.artifact_dir / name).string());
        }
    }
    const auto shader = load_shader();
    context.initialize_scaler(options.scaling, shader);
    auto input = make_pattern(options.scaling.input_width, options.scaling.input_height, 0);
    for (std::uint32_t index = 0; index < options.warmup; ++index) {
        const auto frame = options.changing_frames ? index : 0;
        if (frame != 0) input = make_pattern(options.scaling.input_width, options.scaling.input_height, frame);
        (void)dispatch(context, options.scaling, input, index, frame);
    }
    std::vector<Sample> samples;
    samples.reserve(options.iterations);
    for (std::uint32_t index = 0; index < options.iterations; ++index) {
        const auto frame = options.changing_frames ? options.warmup + index : 0;
        if (options.changing_frames) input = make_pattern(options.scaling.input_width, options.scaling.input_height, frame);
        samples.push_back(dispatch(context, options.scaling, input, index, frame));
    }
    const auto maximum_error = check_output(input, static_cast<const std::uint32_t*>(context.output.mapped), options.scaling);
    save_results(options, context, samples, input, shader, maximum_error);
    const auto allowed_error = options.scaling.filter_kind == 0 ? 0U : 1U;
    std::cout << "Artifacts: " << (options.artifact_dir / "result.json").string() << '\n'
              << "Evidence: " << evidence_class(context.properties.deviceType) << " (" << context.properties.deviceName << ")\n"
              << "Correctness: " << (maximum_error <= allowed_error ? "passed" : "FAILED")
              << "; maximum channel error " << maximum_error << " (allowed " << allowed_error << ")\n";
    return maximum_error <= allowed_error ? 0 : 1;
}
} // namespace

int main(int argc, char** argv) {
    try {
        const auto options = parse_options(argc, argv);
        if (options.help) { print_help(); return 0; }
        return run(options);
    } catch (const std::invalid_argument& error) {
        std::cerr << "Argument error: " << error.what() << "\nUse --help for supported options.\n";
        return 2;
    } catch (const Unavailable& error) {
        std::cerr << "Vulkan unavailable: " << error.what() << '\n';
        return 77;
    } catch (const std::exception& error) {
        std::cerr << "Dock SR benchmark failed: " << error.what() << '\n';
        return 1;
    }
}

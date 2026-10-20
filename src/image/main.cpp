#include <docksr/core/status_snapshot.hpp>
#include <docksr/image/image.hpp>

#include <algorithm>
#include <array>
#include <charconv>
#include <chrono>
#include <cstdint>
#include <filesystem>
#include <iomanip>
#include <iostream>
#include <optional>
#include <stdexcept>
#include <string>
#include <string_view>
#include <vector>

namespace {
using docksr::core::Extent;
using docksr::core::StatusTracker;
using docksr::image::Filter;
using docksr::image::Image;

struct Options {
    std::optional<std::filesystem::path> input;
    bool generate = false;
    std::optional<std::filesystem::path> output;
    std::optional<Extent> output_size;
    Filter filter = Filter::Bilinear;
    std::optional<std::filesystem::path> status_path;
    bool self_test = false;
    bool help = false;
};

std::uint32_t dimension(std::string_view value) {
    std::uint32_t parsed = 0;
    const auto [end, error] = std::from_chars(value.data(), value.data() + value.size(), parsed);
    if (value.empty() || error != std::errc{} || end != value.data() + value.size() ||
        parsed == 0 || parsed > docksr::image::maximum_dimension) {
        throw std::invalid_argument("Dimensions must be decimal integers in [1, 8192]");
    }
    return parsed;
}

Extent parse_size(std::string_view value) {
    const auto separator = value.find('x');
    if (separator == std::string_view::npos) throw std::invalid_argument("Size must be WIDTHxHEIGHT");
    const Extent size{dimension(value.substr(0, separator)), dimension(value.substr(separator + 1))};
    (void)docksr::image::checked_rgb_bytes(size.width, size.height);
    return size;
}

Options parse_options(int argc, char** argv) {
    Options options;
    bool processing_argument = false;
    for (int index = 1; index < argc; ++index) {
        const std::string_view flag(argv[index]);
        const auto next = [&]() -> std::string_view {
            if (++index >= argc) throw std::invalid_argument("Missing value for " + std::string(flag));
            return argv[index];
        };
        const auto path = [&]() -> std::filesystem::path {
            const auto value = next();
            if (value.empty()) throw std::invalid_argument("An empty file path is not allowed");
            return value;
        };
        if (flag == "--help" || flag == "-h") {
            options.help = true;
        } else if (flag == "--input") {
            options.input = path();
            processing_argument = true;
        } else if (flag == "--generate") {
            options.generate = true;
            processing_argument = true;
        } else if (flag == "--output") {
            options.output = path();
            processing_argument = true;
        } else if (flag == "--size") {
            options.output_size = parse_size(next());
            processing_argument = true;
        } else if (flag == "--filter") {
            options.filter = docksr::image::parse_filter(next());
            processing_argument = true;
        } else if (flag == "--dump-status-json") {
            options.status_path = path();
        } else if (flag == "--self-test") {
            options.self_test = true;
        } else {
            throw std::invalid_argument("Unknown option: " + std::string(flag));
        }
    }
    if (options.help) return options;
    if (options.self_test) {
        if (processing_argument) throw std::invalid_argument("--self-test cannot be combined with image-processing options");
        return options;
    }
    if (options.input.has_value() == options.generate) {
        throw std::invalid_argument("Specify exactly one of --input FILE.ppm or --generate");
    }
    if (!options.output || !options.output_size) throw std::invalid_argument("--output and --size are required");
    return options;
}

void print_help() {
    std::cout << "Dock SR CPU spatial reference scaler (no GPU or NPU execution).\n"
                 "Usage: docksr-scale (--input FILE.ppm | --generate) --output NEW.ppm\n"
                 "                    --size WIDTHxHEIGHT [--filter nearest|bilinear]\n"
                 "                    [--dump-status-json PATH]\n"
                 "       docksr-scale --self-test [--dump-status-json PATH]\n"
                 "\n"
                 "--generate creates a deterministic 1280x720 gradient/edge/UI/pixel-art image.\n"
                 "P6 PPM input only, maxval 255; header comments are supported.\n"
                 "Dimensions: 1..8192; each image <=16777216 pixels. Default filter: bilinear.\n"
                 "Sampling uses pixel centers, clamped borders and RGB bytes; no color transfer.\n"
                 "Existing image outputs are never replaced. The output directory must exist.\n"
                 "Stdout contains shared status JSON; frames_processed advances after image publication.\n"
                 "CPU timing measures resize wall duration on this host only, excluding validation\n"
                 "and image I/O; it is not game FPS or comparative image-quality evidence.\n"
                 "--self-test checks real CPU 720p->1080p/4K nearest/bilinear outputs in memory.\n"
                 "Its status counter stays zero because no output image is published; case results\n"
                 "and resize-only local CPU durations are printed to stderr.\n"
                 "Status snapshots require a private directory owned by this user; existing private\n"
                 "Dock SR status documents may be replaced atomically, other files are protected.\n";
}

void accept(const docksr::core::StatusResult& result) {
    if (!result) throw std::runtime_error("Status operation rejected: " + result.reason);
}

void validate_distinct_status_path(const Options& options) {
    if (!options.status_path) return;
    const auto status = std::filesystem::weakly_canonical(*options.status_path);
    if ((options.input && status == std::filesystem::weakly_canonical(*options.input)) ||
        (options.output && status == std::filesystem::weakly_canonical(*options.output))) {
        throw std::invalid_argument("Status snapshot path must differ from input and output image paths");
    }
}

// Independent direct pixel formulas, deliberately separate from resize()'s
// precomputed separable axes. Four-corner integer weights make half-up ties
// exact, so CPU bilinear output must agree byte-for-byte (no tolerance).
void validate_self_test_output(const Image& source, const Image& output,
                               Extent requested, Filter filter) {
    docksr::image::validate(source);
    docksr::image::validate(output);
    if (output.width != requested.width || output.height != requested.height) {
        throw std::runtime_error("CPU self-test output dimensions do not match the request");
    }
    const auto dx = std::int64_t(2) * output.width;
    const auto dy = std::int64_t(2) * output.height;
    const auto denominator = static_cast<std::uint64_t>(dx * dy);
    const auto floor_divide = [](std::int64_t numerator, std::int64_t divisor) {
        const auto quotient = numerator / divisor;
        return quotient - (numerator % divisor < 0 ? 1 : 0);
    };
    const auto source_offset = [&](std::int64_t x, std::int64_t y) {
        const auto bounded_x = std::clamp<std::int64_t>(x, 0, source.width - 1);
        const auto bounded_y = std::clamp<std::int64_t>(y, 0, source.height - 1);
        return (static_cast<std::size_t>(bounded_y) * source.width +
                static_cast<std::size_t>(bounded_x)) * 3U;
    };
    for (std::uint32_t y = 0; y < output.height; ++y) {
        const auto numerator_y = (std::int64_t(2) * y + 1) * source.height - output.height;
        const auto top = floor_divide(numerator_y, dy);
        const auto fy = static_cast<std::uint64_t>(numerator_y - top * dy);
        for (std::uint32_t x = 0; x < output.width; ++x) {
            const auto target = (std::size_t(y) * output.width + x) * 3U;
            std::array<std::uint8_t, 3> expected{};
            if (filter == Filter::Nearest) {
                const auto source_x = (std::int64_t(2) * x + 1) * source.width / dx;
                const auto source_y = (std::int64_t(2) * y + 1) * source.height / dy;
                const auto offset = source_offset(source_x, source_y);
                std::copy_n(source.rgb.begin() + static_cast<std::ptrdiff_t>(offset), 3, expected.begin());
            } else {
                const auto numerator_x = (std::int64_t(2) * x + 1) * source.width - output.width;
                const auto left = floor_divide(numerator_x, dx);
                const auto fx = static_cast<std::uint64_t>(numerator_x - left * dx);
                const auto ix = static_cast<std::uint64_t>(dx) - fx;
                const auto iy = static_cast<std::uint64_t>(dy) - fy;
                const std::array<std::size_t, 4> offsets{
                    source_offset(left, top), source_offset(left + 1, top),
                    source_offset(left, top + 1), source_offset(left + 1, top + 1)};
                const std::array<std::uint64_t, 4> weights{ix * iy, fx * iy, ix * fy, fx * fy};
                for (std::size_t channel = 0; channel < 3; ++channel) {
                    std::uint64_t numerator = 0;
                    for (std::size_t corner = 0; corner < 4; ++corner) {
                        numerator += source.rgb[offsets[corner] + channel] * weights[corner];
                    }
                    expected[channel] = static_cast<std::uint8_t>((numerator + denominator / 2U) / denominator);
                }
            }
            for (std::size_t channel = 0; channel < 3; ++channel) {
                if (output.rgb[target + channel] != expected[channel]) {
                    throw std::runtime_error("CPU self-test " + std::string(docksr::image::filter_name(filter)) +
                        " output " + std::to_string(output.width) + "x" + std::to_string(output.height) +
                        " mismatched pixel " + std::to_string(x) + "," + std::to_string(y) +
                        " channel " + std::to_string(channel));
                }
            }
        }
    }
}

void self_test(StatusTracker& tracker) {
    accept(tracker.begin_cpu_reference("cpu-reference-self-test", {2, 1}, {6, 1}));
    const Image source{2, 1, {0,10,20, 100,110,120}};
    const auto nearest = docksr::image::resize(source, 6, 1, Filter::Nearest);
    const auto bilinear = docksr::image::resize(source, 4, 1, Filter::Bilinear);
    if (nearest.rgb != std::vector<std::uint8_t>{0,10,20, 0,10,20, 0,10,20, 100,110,120, 100,110,120, 100,110,120} ||
        bilinear.rgb != std::vector<std::uint8_t>{0,10,20, 25,35,45, 75,85,95, 100,110,120}) {
        throw std::runtime_error("CPU image self-test did not match known pixel values");
    }
    const auto raw = docksr::image::generate_pattern(1280, 720);
    const auto preserved_raw = raw.rgb;
    unsigned cases = 0;
    for (const Extent requested : {Extent{1920, 1080}, Extent{3840, 2160}}) {
        for (const Filter filter : {Filter::Nearest, Filter::Bilinear}) {
            accept(tracker.begin_cpu_reference("cpu-reference-self-test", {raw.width, raw.height}, requested));
            const auto started = std::chrono::steady_clock::now();
            const auto output = docksr::image::resize(raw, requested.width, requested.height, filter);
            const double cpu_ms = std::chrono::duration<double, std::milli>(
                std::chrono::steady_clock::now() - started).count();
            if (raw.rgb != preserved_raw) throw std::runtime_error("CPU self-test modified the preserved raw source");
            validate_self_test_output(raw, output, requested, filter);
            ++cases;
            std::cerr << "SELF_TEST_CASE filter=" << docksr::image::filter_name(filter)
                      << " input=1280x720 output=" << requested.width << 'x' << requested.height
                      << " validated_pixels=" << std::uint64_t(requested.width) * requested.height
                      << " max_channel_error=0 tolerance=0 cpu_resize_ms=" << std::setprecision(9) << cpu_ms
                      << " PASS\n";
        }
    }
    // All four actual outputs were validated in memory and discarded. No image
    // was published, so the existing published-output counter remains zero.
    std::cerr << "SELF_TEST_SUMMARY cases=" << cases << " published_images=0 frames_processed=0 PASS\n";
}
} // namespace

int main(int argc, char** argv) {
    StatusTracker tracker;
    Options options;
    bool parsed = false;
    bool status_path_checked = false;
    bool publication_attempted = false;
    std::string error_code = "CLI_ARGUMENT_ERROR";
    try {
        options = parse_options(argc, argv);
        parsed = true;
        if (options.help) { print_help(); return 0; }
        validate_distinct_status_path(options);
        status_path_checked = true;
        error_code = "IMAGE_PROCESSING_FAILED";
        if (options.self_test) {
            self_test(tracker);
        } else {
            if (std::filesystem::exists(*options.output) || std::filesystem::is_symlink(*options.output)) {
                throw std::runtime_error("Refusing to overwrite existing image output: " + options.output->string());
            }
            const auto input = options.generate ? docksr::image::generate_pattern() : docksr::image::read_ppm(*options.input);
            const auto requested = *options.output_size;
            const Extent input_extent{input.width, input.height};
            accept(tracker.begin_cpu_reference("cpu-reference-" + std::string(docksr::image::filter_name(options.filter)),
                                               input_extent, requested));
            const auto started = std::chrono::steady_clock::now();
            const auto output = docksr::image::resize(input, requested.width, requested.height, options.filter);
            const double cpu_ms = std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - started).count();
            docksr::image::write_ppm_exclusive(*options.output, output);
            accept(tracker.acknowledge_cpu_output(input_extent, {output.width, output.height}, cpu_ms));
            std::cerr << "CPU resize wall duration on this host: " << cpu_ms
                      << " ms (excludes image I/O; no game FPS or quality comparison).\n";
        }
        if (options.status_path) {
            error_code = "STATUS_PUBLICATION_FAILED";
            publication_attempted = true;
            accept(docksr::core::publish_status_json(*options.status_path, tracker.snapshot()));
        }
        std::cout << docksr::core::serialize_status_json(tracker.snapshot()) << '\n';
        return 0;
    } catch (const std::exception& error) {
        std::string diagnostic = error.what();
        if (diagnostic.size() > 1024) {
            diagnostic.resize(1000);
            diagnostic += "... [truncated]";
        }
        const auto failure = tracker.report_failure(error_code, diagnostic);
        if (!failure) {
            std::cerr << "Failed to record the CPU scaler error: " << failure.reason << '\n';
            return 1; // Never serialize the old success/starting state as a failure observation.
        }
        std::cerr << "Dock SR CPU scaler failed: " << diagnostic << '\n';
        if (parsed && status_path_checked && options.status_path && !publication_attempted) {
            const auto result = docksr::core::publish_status_json(*options.status_path, tracker.snapshot());
            if (!result) std::cerr << "Failure status was not published: " << result.reason << '\n';
        }
        try { std::cout << docksr::core::serialize_status_json(tracker.snapshot()) << '\n'; }
        catch (const std::exception& status_error) { std::cerr << "Status serialization failed: " << status_error.what() << '\n'; }
        return error_code == "CLI_ARGUMENT_ERROR" ? 2 : 1;
    }
}

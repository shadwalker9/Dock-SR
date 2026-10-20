#include "docksr/image/image.hpp"
#include "docksr/vulkan/scaler.hpp"

#include <array>
#include <cmath>
#include <cstdint>
#include <functional>
#include <initializer_list>
#include <iostream>
#include <limits>
#include <memory>
#include <optional>
#include <stdexcept>
#include <string>
#include <type_traits>

namespace {
namespace image = docksr::image;
namespace vulkan = docksr::vulkan;
using Pixel = std::array<std::uint8_t, 3>;

static_assert(!std::is_copy_constructible_v<vulkan::Scaler>);
static_assert(!std::is_copy_assignable_v<vulkan::Scaler>);

void check(bool condition, const std::string& message) {
    if (!condition) throw std::runtime_error(message);
}

image::Image fixture(std::uint32_t width, std::uint32_t height,
                     std::initializer_list<Pixel> pixels) {
    image::Image result{width, height, {}};
    for (const auto& pixel : pixels) {
        result.rgb.insert(result.rgb.end(), pixel.begin(), pixel.end());
    }
    check(result.rgb.size() == std::size_t(width) * height * 3,
          "Invalid hardcoded test fixture");
    return result;
}

image::Image pattern(std::uint32_t width, std::uint32_t height, unsigned seed) {
    image::Image result{width, height, {}};
    for (std::uint32_t y = 0; y < height; ++y) {
        for (std::uint32_t x = 0; x < width; ++x) {
            for (unsigned channel = 0; channel < 3; ++channel) {
                result.rgb.push_back(static_cast<std::uint8_t>(
                    (x * 37U + y * 53U + channel * 79U + seed * 17U) % 256U));
            }
        }
    }
    return result;
}

void compare(const image::Image& actual, const image::Image& expected,
             unsigned tolerance, const std::string& label) {
    check(actual.width == expected.width && actual.height == expected.height,
          label + ": incorrect output dimensions");
    check(actual.rgb.size() == expected.rgb.size(), label + ": incorrect RGB byte count");
    for (std::size_t index = 0; index < expected.rgb.size(); ++index) {
        const int error = std::abs(int(actual.rgb[index]) - int(expected.rgb[index]));
        check(unsigned(error) <= tolerance,
              label + ": RGB mismatch at byte " + std::to_string(index) +
              ", expected " + std::to_string(expected.rgb[index]) +
              ", actual " + std::to_string(actual.rgb[index]));
    }
}

class Checks {
public:
    explicit Checks(vulkan::Scaler& scaler) : scaler_(scaler) {}

    vulkan::ScaleResult run(const image::Image& input, const image::Image& expected,
                           image::Filter filter, const std::string& label) {
        const auto original = input;
        auto result = scaler_.scale(input, expected.width, expected.height, filter);
        check(input.width == original.width && input.height == original.height &&
                  input.rgb == original.rgb,
              label + ": scaler modified the caller's input");
        compare(result.image, expected, filter == image::Filter::Nearest ? 0U : 1U, label);
        check(!result.device_name.empty(), label + ": missing Vulkan device name");
        switch (result.evidence) {
        case vulkan::DeviceEvidence::PhysicalGPU:
        case vulkan::DeviceEvidence::Software:
        case vulkan::DeviceEvidence::Unknown:
            break;
        default:
            throw std::runtime_error(label + ": invalid device evidence enum");
        }
        if (!device_name_) {
            device_name_ = result.device_name;
            evidence_ = result.evidence;
        } else {
            check(result.device_name == *device_name_ && result.evidence == *evidence_,
                  label + ": a reused scaler changed device identity or evidence");
        }
        check(std::isfinite(result.host_ms) && result.host_ms >= 0,
              label + ": host timing must be finite and nonnegative");
        if (result.gpu_ms) {
            check(std::isfinite(*result.gpu_ms) && *result.gpu_ms >= 0,
                  label + ": GPU timing must be finite and nonnegative");
        }
        ++successful_;
        return result;
    }

    vulkan::ScaleResult reference(const image::Image& input, std::uint32_t width,
                                 std::uint32_t height, image::Filter filter,
                                 const std::string& label) {
        return run(input, image::resize(input, width, height, filter), filter, label);
    }

    void invalid(const std::string& label, const std::function<void()>& operation) {
        bool rejected = false;
        try {
            operation();
        } catch (const std::invalid_argument&) {
            rejected = true;
        }
        check(rejected, label + ": invalid request was accepted");
        ++rejected_;
        // A validation failure must leave the same engine usable.
        reference(recovery_input_, 5, 3, image::Filter::Nearest, label + " recovery");
    }

    void summary() const {
        std::cout << "PASS reusable Vulkan scaler: " << successful_
                  << " successful dispatches, " << rejected_
                  << " rejected invalid requests\n";
    }

private:
    vulkan::Scaler& scaler_;
    std::optional<std::string> device_name_;
    std::optional<vulkan::DeviceEvidence> evidence_;
    image::Image recovery_input_{pattern(3, 2, 1)};
    unsigned successful_{};
    unsigned rejected_{};
};

void run_tests(vulkan::Scaler& scaler) {
    Checks checks(scaler);
    const Pixel a{3, 17, 91}, b{250, 8, 30}, c{11, 230, 47}, d{64, 128, 192};
    const auto source = fixture(2, 2, {a, b, c, d});
    const auto nearest_golden = fixture(6, 6, {
        a, a, a, b, b, b,
        a, a, a, b, b, b,
        a, a, a, b, b, b,
        c, c, c, d, d, d,
        c, c, c, d, d, d,
        c, c, c, d, d, d,
    });
    const auto retained = checks.run(source, nearest_golden, image::Filter::Nearest,
                                     "nearest threefold hardcoded golden");

    const auto bilinear_source = fixture(2, 2, {
        Pixel{0, 0, 0}, Pixel{120, 60, 30},
        Pixel{60, 120, 90}, Pixel{180, 180, 120},
    });
    const auto bilinear_golden = fixture(3, 3, {
        Pixel{0, 0, 0}, Pixel{60, 30, 15}, Pixel{120, 60, 30},
        Pixel{30, 60, 45}, Pixel{90, 90, 60}, Pixel{150, 120, 75},
        Pixel{60, 120, 90}, Pixel{120, 150, 105}, Pixel{180, 180, 120},
    });
    checks.run(bilinear_source, bilinear_golden, image::Filter::Bilinear,
               "bilinear hardcoded center and clamped borders");
    compare(retained.image, nearest_golden, 0,
            "retained result must own its pixels after another dispatch");

    const auto first = pattern(3, 2, 2);
    const auto changed = pattern(3, 2, 9);
    const auto repeat = checks.reference(first, 5, 3, image::Filter::Nearest,
                                         "odd-aspect first upload");
    checks.reference(changed, 5, 3, image::Filter::Nearest,
                     "same dimensions with changed source bytes");
    checks.reference(changed, 5, 3, image::Filter::Bilinear,
                     "same dimensions with changed filter");
    const auto repeated = checks.reference(first, 5, 3, image::Filter::Nearest,
                                           "same engine repeated original request");
    compare(repeated.image, repeat.image, 0, "repeated request must be deterministic");

    for (const auto filter : {image::Filter::Nearest, image::Filter::Bilinear}) {
        checks.run(first, first, filter, "identity");
        checks.reference(first, 1, 1, filter, "downscale to one pixel");
        checks.reference(first, 7, 9, filter, "grow reusable output buffers");
        checks.reference(pattern(9, 7, 4), 4, 3, filter, "changed input dimensions and downscale");
        checks.reference(pattern(1, 3, 7), 7, 1, filter, "one-pixel input axis");
        const auto one = fixture(1, 1, {Pixel{13, 127, 255}});
        checks.run(one, fixture(3, 2, {
            Pixel{13, 127, 255}, Pixel{13, 127, 255}, Pixel{13, 127, 255},
            Pixel{13, 127, 255}, Pixel{13, 127, 255}, Pixel{13, 127, 255},
        }), filter, "single pixel must fill clamped output");
    }

    const image::Image invalid_images[] = {
        {0, 0, {}}, {0, 1, {}}, {1, 0, {}},
        {1, 1, {1, 2}}, {1, 1, {1, 2, 3, 4}},
        {8193, 1, {}}, {8192, 8192, {}},
        {std::numeric_limits<std::uint32_t>::max(), 1, {}},
    };
    for (std::size_t index = 0; index < std::size(invalid_images); ++index) {
        const auto& input = invalid_images[index];
        const auto original = input;
        checks.invalid("invalid input " + std::to_string(index), [&] {
            (void)scaler.scale(input, 3, 2, image::Filter::Nearest);
        });
        check(input.width == original.width && input.height == original.height &&
                  input.rgb == original.rgb,
              "Rejected input must remain unchanged");
    }
    for (const auto target : {
             std::array<std::uint32_t, 2>{0, 1}, {1, 0}, {8193, 1},
             {1, 8193}, {8192, 8192},
             {std::numeric_limits<std::uint32_t>::max(), 1}}) {
        checks.invalid("invalid target " + std::to_string(target[0]) + "x" +
                       std::to_string(target[1]), [&] {
            (void)scaler.scale(first, target[0], target[1], image::Filter::Bilinear);
        });
    }
    checks.invalid("invalid filter enum", [&] {
        (void)scaler.scale(first, 5, 3, static_cast<image::Filter>(999));
    });
    checks.summary();
}
} // namespace

int main() {
    std::unique_ptr<docksr::vulkan::Scaler> scaler;
    try {
        scaler = std::make_unique<docksr::vulkan::Scaler>();
    } catch (const docksr::vulkan::Unavailable& error) {
        std::cerr << "Vulkan unavailable: " << error.what() << '\n';
        return 77;
    } catch (const std::exception& error) {
        std::cerr << "Vulkan scaler construction failed: " << error.what() << '\n';
        return 1;
    }
    try {
        run_tests(*scaler);
    } catch (const std::exception& error) {
        std::cerr << "FAIL reusable Vulkan scaler: " << error.what() << '\n';
        return 1;
    }
    return 0;
}

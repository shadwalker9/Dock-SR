#include <docksr/image/image.hpp>

#include <filesystem>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>

#include <sys/stat.h>
#include <unistd.h>

namespace {
using docksr::image::Filter;
using docksr::image::Image;

void require(bool condition, const std::string& message) {
    if (!condition) throw std::runtime_error(message);
}

template <typename Function>
void rejects(Function function, const std::string& message) {
    bool rejected = false;
    try { function(); } catch (const std::exception&) { rejected = true; }
    require(rejected, message);
}

void expect_pixels(const Image& image, std::uint32_t width, std::uint32_t height,
                   const std::vector<std::uint8_t>& expected, const std::string& label) {
    require(image.width == width && image.height == height, label + ": dimensions");
    require(image.rgb == expected, label + ": pixel mismatch");
}

struct ScratchDirectory {
    std::filesystem::path path;
    ScratchDirectory() {
        std::string name = (std::filesystem::temp_directory_path() / "docksr-image-tests-XXXXXX").string();
        std::vector<char> bytes(name.begin(), name.end());
        bytes.push_back('\0');
        const auto result = ::mkdtemp(bytes.data());
        if (!result) throw std::runtime_error("Cannot create image-test scratch directory");
        path = result;
    }
    ~ScratchDirectory() { std::error_code ignored; std::filesystem::remove_all(path, ignored); }
};

void write_bytes(const std::filesystem::path& path, const std::string& bytes) {
    std::ofstream output(path, std::ios::binary);
    output.write(bytes.data(), static_cast<std::streamsize>(bytes.size()));
    output.close();
    require(bool(output), "Fixture write failed");
}

void golden_scaling_tests() {
    const Image pair{2, 1, {0, 10, 20, 100, 110, 120}};
    expect_pixels(docksr::image::resize(pair, 6, 1, Filter::Nearest), 6, 1,
                  {0,10,20, 0,10,20, 0,10,20, 100,110,120, 100,110,120, 100,110,120},
                  "nearest 3x");
    for (const auto filter : {Filter::Nearest, Filter::Bilinear}) {
        expect_pixels(docksr::image::resize(pair, 2, 1, filter), 2, 1, pair.rgb, "identity");
    }
    expect_pixels(docksr::image::resize(pair, 4, 1, Filter::Bilinear), 4, 1,
                  {0,10,20, 25,35,45, 75,85,95, 100,110,120}, "bilinear borders");
    const Image square{2, 2, {0,0,0, 100,0,0, 0,100,0, 100,100,100}};
    expect_pixels(docksr::image::resize(square, 3, 3, Filter::Bilinear), 3, 3,
                  {0,0,0, 50,0,0, 100,0,0,
                   0,50,0, 50,50,25, 100,50,50,
                   0,100,0, 50,100,50, 100,100,100}, "bilinear center");
    expect_pixels(docksr::image::resize(square, 1, 1, Filter::Bilinear), 1, 1,
                  {50,50,25}, "bilinear downscale midpoint");
    const Image odd{3, 1, {0,0,0, 100,50,0, 200,100,0}};
    expect_pixels(docksr::image::resize(odd, 5, 3, Filter::Bilinear), 5, 3,
                  {0,0,0, 40,20,0, 100,50,0, 160,80,0, 200,100,0,
                   0,0,0, 40,20,0, 100,50,0, 160,80,0, 200,100,0,
                   0,0,0, 40,20,0, 100,50,0, 160,80,0, 200,100,0}, "odd aspect");
    const Image one{1, 1, {10,32,35}};
    std::vector<std::uint8_t> repeated;
    for (unsigned i = 0; i < 15; ++i) repeated.insert(repeated.end(), one.rgb.begin(), one.rgb.end());
    expect_pixels(docksr::image::resize(one, 3, 5, Filter::Bilinear), 3, 5, repeated, "single pixel clamp");
}

void bounds_and_input_tests() {
    rejects([] { (void)docksr::image::checked_rgb_bytes(0, 1); }, "zero width accepted");
    rejects([] { (void)docksr::image::checked_rgb_bytes(1, 0); }, "zero height accepted");
    rejects([] { (void)docksr::image::checked_rgb_bytes(8193, 1); }, "oversized dimension accepted");
    rejects([] { (void)docksr::image::checked_rgb_bytes(8192, 8192); }, "oversized product accepted");
    rejects([] { docksr::image::validate(Image{2, 2, {1,2,3}}); }, "short storage accepted");
    rejects([] { (void)docksr::image::parse_filter("fsr"); }, "unknown filter accepted");
    rejects([] { (void)docksr::image::resize(Image{1,1,{0,0,0}}, 1, 1, static_cast<Filter>(255)); }, "invalid enum accepted");
    ScratchDirectory scratch;
    const auto fixture = scratch.path / "input.ppm";
    const std::string raw_pixel{"\n #", 3};
    write_bytes(fixture, "P6\n# one comment\n1 # another\n1\n255\n" + raw_pixel);
    expect_pixels(docksr::image::read_ppm(fixture), 1, 1, {10,32,35}, "comments and raw whitespace");
    write_bytes(fixture, "P6\r\n1 1\r\n255\r\n" + raw_pixel);
    expect_pixels(docksr::image::read_ppm(fixture), 1, 1, {10,32,35}, "CRLF");
    write_bytes(fixture, "P6\n1 1\n255\r" + raw_pixel);
    expect_pixels(docksr::image::read_ppm(fixture), 1, 1, {10,32,35}, "single CR with LF raster byte");
    for (const auto& invalid : std::vector<std::string>{
            "", "P3\n1 1\n255\n0 0 0", "P6\n0 1\n255\n", "P6\n1 1\n256\nabc",
            "P6\n1 1\n255\nab", "P6\n1 1\n255\nabcd", "P6\n-1 1\n255\nabc",
            "P6\n999999999999999999999 1\n255\nabc", "P6\n1 1\n255",
            "P6\n#" + std::string(65'536, 'a') + "\n1 1\n255\nabc"}) {
        write_bytes(fixture, invalid);
        rejects([&] { (void)docksr::image::read_ppm(fixture); }, "Malformed PPM accepted");
    }
    rejects([&] { (void)docksr::image::read_ppm(scratch.path); }, "Directory input accepted");
}

void exclusive_output_tests() {
    ScratchDirectory scratch;
    const Image original{2, 1, {0,10,20, 255,254,253}};
    const auto output = scratch.path / "output.ppm";
    docksr::image::write_ppm_exclusive(output, original);
    expect_pixels(docksr::image::read_ppm(output), 2, 1, original.rgb, "PPM roundtrip");
    struct stat attributes{};
    require(::stat(output.c_str(), &attributes) == 0 && (attributes.st_mode & 0777) == 0600,
            "Published image permissions are not 0600");
    rejects([&] { docksr::image::write_ppm_exclusive(output, Image{1,1,{1,2,3}}); }, "Existing output overwritten");
    expect_pixels(docksr::image::read_ppm(output), 2, 1, original.rgb, "Existing output changed");
    const auto alias = scratch.path / "alias.ppm";
    std::filesystem::create_symlink(output.filename(), alias);
    rejects([&] { docksr::image::write_ppm_exclusive(alias, Image{1,1,{1,2,3}}); }, "Output symlink overwritten");
    expect_pixels(docksr::image::read_ppm(output), 2, 1, original.rgb, "Symlink target changed");
    for (const auto& entry : std::filesystem::directory_iterator(scratch.path)) {
        require(entry.path().filename().string().rfind(".docksr-image-", 0) != 0,
                "Temporary output leaked after failure");
    }
}
} // namespace

int main() {
    try {
        golden_scaling_tests();
        bounds_and_input_tests();
        exclusive_output_tests();
        std::cout << "CPU image goldens, bounds, PPM parsing and exclusive output passed\n";
        return 0;
    } catch (const std::exception& error) {
        std::cerr << "Image test failed: " << error.what() << '\n';
        return 1;
    }
}

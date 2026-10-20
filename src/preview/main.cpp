#include "docksr/preview/controller.hpp"

#include <X11/Xlib.h>
#include <X11/Xutil.h>
#include <X11/keysym.h>

#include <algorithm>
#include <charconv>
#include <cmath>
#include <cstdlib>
#include <filesystem>
#include <iomanip>
#include <iostream>
#include <memory>
#include <sstream>
#include <stdexcept>
#include <string>
#include <string_view>

namespace {
using docksr::core::Extent;
using docksr::image::Image;
using docksr::image::Filter;
using docksr::preview::Backend;

struct Options {
    std::optional<std::filesystem::path> input, status, capture;
    Extent output{1920, 1080};
    Filter filter{Filter::Bilinear};
    Backend backend{Backend::Cpu};
};

Extent output_size(std::string_view value) {
    if (value == "1920x1080") return {1920, 1080};
    if (value == "3840x2160") return {3840, 2160};
    throw std::invalid_argument("--size must be 1920x1080 or 3840x2160");
}

Options options(int argc, char** argv) {
    Options result;
    for (int i = 1; i < argc; ++i) {
        const std::string_view key = argv[i];
        if (key == "--help") {
            std::cout << "Dock SR PREVIEW ONLY - NOT GAME INTEGRATION\n"
                "docksr-preview [--input RAW.ppm] [--size 1920x1080|3840x2160]\n"
                "  [--filter nearest|bilinear] [--backend cpu|vulkan]\n"
                "  [--dump-status-json PRIVATE/status.json] [--capture NEW.ppm]\n"
                "Default source: deterministic 1280x720 pattern. Requires an X11 display\n"
                "(XWayland is acceptable). Left: CPU nearest; right: selected backend/method.\n"
                "Keys: M method, V backend, O output size, A A/B, D diagnostics,\n"
                "Z matched center 1:1 crop / fit, R retry, C capture, Q/Escape quit.\n"
                "No continuous animation, game capture, NPU execution or FPS claim.\n";
            std::exit(0);
        }
        if (i + 1 >= argc) throw std::invalid_argument("missing option value");
        const std::string_view value = argv[++i];
        if (key == "--input") result.input = value;
        else if (key == "--size") result.output = output_size(value);
        else if (key == "--filter") result.filter = docksr::image::parse_filter(value);
        else if (key == "--backend") {
            if (value == "cpu") result.backend = Backend::Cpu;
            else if (value == "vulkan") result.backend = Backend::Vulkan;
            else throw std::invalid_argument("--backend must be cpu or vulkan");
        } else if (key == "--dump-status-json") result.status = value;
        else if (key == "--capture") result.capture = value;
        else throw std::invalid_argument("unknown preview option");
    }
    return result;
}

std::string clean(std::string_view text, std::size_t limit = 150) {
    std::string result;
    for (const unsigned char c : text.substr(0, limit))
        result += c >= 32 && c < 127 ? static_cast<char>(c) : '?';
    return result;
}

std::string dimensions(Extent value) {
    return std::to_string(value.width) + "x" + std::to_string(value.height);
}

std::string ms(const std::optional<double>& value) {
    if (!value) return "UNMEASURED";
    std::ostringstream text;
    text << std::fixed << std::setprecision(3) << *value << " ms";
    return text.str();
}

unsigned long channel(unsigned char value, unsigned long mask) {
    if (!mask) return 0;
    unsigned int shift{};
    while ((mask & 1UL) == 0) { mask >>= 1U; ++shift; }
    return ((static_cast<unsigned long>(value) * mask + 127UL) / 255UL) << shift;
}

unsigned char unchannel(unsigned long pixel, unsigned long mask) {
    if (!mask) return 0;
    unsigned int shift{};
    while ((mask & 1UL) == 0) { mask >>= 1U; ++shift; }
    return static_cast<unsigned char>((((pixel >> shift) & mask) * 255UL + mask / 2UL) / mask);
}

struct XImageDeleter { void operator()(XImage* value) const { if (value) XDestroyImage(value); } };
using WindowImage = std::unique_ptr<XImage, XImageDeleter>;

class Window {
public:
    Window() {
        display_ = XOpenDisplay(nullptr);
        if (!display_) throw std::runtime_error("No usable X11 display; set DISPLAY for X11/XWayland. Window execution unavailable.");
        screen_ = DefaultScreen(display_);
        if (DefaultVisual(display_, screen_)->c_class != TrueColor) {
            XCloseDisplay(display_); display_ = nullptr;
            throw std::runtime_error("Preview requires an X11 TrueColor visual");
        }
        window_ = XCreateSimpleWindow(display_, RootWindow(display_, screen_), 0, 0,
                                     width_, height_, 0, 0, 0x101923);
        XStoreName(display_, window_, "Dock SR PREVIEW - NOT GAME INTEGRATION");
        XSelectInput(display_, window_, ExposureMask | KeyPressMask | StructureNotifyMask);
        close_ = XInternAtom(display_, "WM_DELETE_WINDOW", False);
        XSetWMProtocols(display_, window_, &close_, 1);
        XSizeHints limits{};
        limits.flags = PMinSize;
        limits.min_width = 960; limits.min_height = 700;
        XSetWMNormalHints(display_, window_, &limits);
        gc_ = XCreateGC(display_, window_, 0, nullptr);
        font_ = XLoadQueryFont(display_, "fixed");
        if (font_) XSetFont(display_, gc_, font_->fid);
        XMapWindow(display_, window_);
        XSync(display_, False);
    }
    ~Window() {
        if (!display_) return;
        if (font_) XFreeFont(display_, font_);
        if (gc_) XFreeGC(display_, gc_);
        if (window_) XDestroyWindow(display_, window_);
        XCloseDisplay(display_);
    }
    Window(const Window&) = delete;
    Window& operator=(const Window&) = delete;

    XEvent next() { XEvent event{}; XNextEvent(display_, &event); return event; }
    bool is_close(const XEvent& event) const {
        return event.type == ClientMessage && static_cast<Atom>(event.xclient.data.l[0]) == close_;
    }
    void resize(int width, int height) { width_ = width; height_ = height; }
    void text(int x, int y, std::string_view value, unsigned long color = 0xdfe8f2) {
        const int columns = std::max(1, (width_ - x - 8) / 6);
        const auto bounded = clean(value, static_cast<std::size_t>(columns));
        XSetForeground(display_, gc_, color);
        XDrawString(display_, window_, gc_, x, y, bounded.c_str(), static_cast<int>(bounded.size()));
    }
    void rectangle(int x, int y, int width, int height, unsigned long color) {
        if (width <= 0 || height <= 0) return;
        XSetForeground(display_, gc_, color);
        XFillRectangle(display_, window_, gc_, x, y, static_cast<unsigned int>(width), static_cast<unsigned int>(height));
    }
    void pixels(const Image& image, int x, int y, int box_width, int box_height, bool zoom) {
        if (box_width <= 0 || box_height <= 0) return;
        const double factor = std::min(static_cast<double>(box_width) / image.width,
                                      static_cast<double>(box_height) / image.height);
        const auto draw_width = static_cast<std::uint32_t>(zoom ? std::min<int>(box_width, static_cast<int>(image.width)) : std::max(1, static_cast<int>(image.width * factor)));
        const auto draw_height = static_cast<std::uint32_t>(zoom ? std::min<int>(box_height, static_cast<int>(image.height)) : std::max(1, static_cast<int>(image.height * factor)));
        const auto crop_x = zoom ? (image.width - draw_width) / 2U : 0U;
        const auto crop_y = zoom ? (image.height - draw_height) / 2U : 0U;
        WindowImage view(XCreateImage(display_, DefaultVisual(display_, screen_), static_cast<unsigned int>(DefaultDepth(display_, screen_)),
                                     ZPixmap, 0, nullptr, draw_width, draw_height, 32, 0));
        if (!view) throw std::runtime_error("XCreateImage failed");
        const auto bytes = static_cast<std::size_t>(view->bytes_per_line) * draw_height;
        view->data = static_cast<char*>(std::calloc(bytes, 1));
        if (!view->data) throw std::bad_alloc();
        for (std::uint32_t row = 0; row < draw_height; ++row) {
            const auto sy = zoom ? crop_y + row : std::min(image.height - 1U, static_cast<std::uint32_t>((static_cast<std::uint64_t>(2U * row + 1U) * image.height) / (2U * draw_height)));
            for (std::uint32_t col = 0; col < draw_width; ++col) {
                const auto sx = zoom ? crop_x + col : std::min(image.width - 1U, static_cast<std::uint32_t>((static_cast<std::uint64_t>(2U * col + 1U) * image.width) / (2U * draw_width)));
                const auto offset = (static_cast<std::size_t>(sy) * image.width + sx) * 3;
                const auto pixel = channel(image.rgb[offset], view->red_mask) | channel(image.rgb[offset+1], view->green_mask) | channel(image.rgb[offset+2], view->blue_mask);
                XPutPixel(view.get(), static_cast<int>(col), static_cast<int>(row), pixel);
            }
        }
        XPutImage(display_, window_, gc_, view.get(), 0, 0,
                  x + (box_width-static_cast<int>(draw_width))/2, y + (box_height-static_cast<int>(draw_height))/2, draw_width, draw_height);
    }
    void capture(const std::filesystem::path& path) {
        if (width_ <= 0 || height_ <= 0 || width_ > 4096 || height_ > 2160)
            throw std::runtime_error("window capture exceeds preview bounds");
        XSync(display_, False);
        WindowImage view(XGetImage(display_, window_, 0, 0, static_cast<unsigned int>(width_),
                                  static_cast<unsigned int>(height_), AllPlanes, ZPixmap));
        if (!view) throw std::runtime_error("XGetImage did not capture the executed window");
        Image result{static_cast<std::uint32_t>(width_), static_cast<std::uint32_t>(height_), {}};
        result.rgb.resize(docksr::image::checked_rgb_bytes(result.width, result.height));
        for (int y = 0; y < height_; ++y) for (int x = 0; x < width_; ++x) {
            const auto pixel = XGetPixel(view.get(), x, y);
            const auto offset = (static_cast<std::size_t>(y) * result.width + static_cast<unsigned int>(x)) * 3;
            result.rgb[offset] = unchannel(pixel, view->red_mask);
            result.rgb[offset+1] = unchannel(pixel, view->green_mask);
            result.rgb[offset+2] = unchannel(pixel, view->blue_mask);
        }
        docksr::image::write_ppm_exclusive(path, result);
    }
    int width() const { return width_; }
    int height() const { return height_; }
    void flush() { XFlush(display_); }
private:
    Display* display_{};
    int screen_{}, width_{1200}, height_{800};
    ::Window window_{};
    GC gc_{};
    XFontStruct* font_{};
    Atom close_{};
};

void pane_status(Window& window, int x, int y, const docksr::core::StatusSnapshot& status) {
    using docksr::core::to_string;
    window.text(x, y, "Backend: " + status.backend_name);
    window.text(x, y+19, "Evidence: " + std::string(to_string(status.evidence)));
    window.text(x, y+38, "State: " + std::string(to_string(status.runtime_state)));
    window.text(x, y+57, "Completed outputs: " + std::to_string(status.frames_processed));
    window.text(x, y+76, "CPU resize: " + ms(status.timings_ms.cpu));
    window.text(x, y+95, "Vulkan dispatch: " + ms(status.timings_ms.gpu));
    if (status.actual_dimensions)
        window.text(x, y+114, "Actual: " + dimensions(status.actual_dimensions->input) + " -> " + dimensions(status.actual_dimensions->output));
}

void draw(Window& window, const docksr::preview::Controller& controller,
          const Options& config, bool ab, bool diagnostics, bool zoom, const std::string& message) {
    window.rectangle(0, 0, window.width(), window.height(), 0x101923);
    window.text(18, 26, "DOCK SR PREVIEW", 0x72d8bb);
    window.text(18, 48, "PREVIEW ONLY - NOT GAME INTEGRATION", 0xffc76b);
    window.text(18, 70, "M method | V CPU/Vulkan | O 1080p/4K | A A/B/single | D diagnostics | Z fit/1:1 crop | R retry | C capture | Q quit");
    window.text(18, 92, "Requested: " + dimensions({controller.raw().width, controller.raw().height}) + " -> " + dimensions(config.output) +
                " | Actual window: " + std::to_string(window.width()) + "x" + std::to_string(window.height()) +
                " | Display: " + (zoom ? "center crop at 1:1" : "fit, nearest display sampling"));
    if (window.width() > 4096 || window.height() > 2160 || window.width() < 200 || window.height() < 250) {
        window.text(18, 116, "Window outside supported draw bounds (200x250 to 4096x2160); resize or Q to quit.");
        window.flush(); return;
    }
    const auto& pair = controller.frame();
    const int pane_width = ab ? (window.width()-54)/2 : window.width()-36;
    const int pane_height = std::max(1, std::min((pane_width*9)/16, window.height()-(diagnostics ? 410 : 190)));
    window.text(18, 118, ab ? "A: CPU nearest reference" : "B: selected backend / method");
    if (ab) window.text(pane_width+36, 118, "B: " + std::string(docksr::image::filter_name(config.filter)) + " (selected)");
    if (ab) window.pixels(pair.left, 18, 132, pane_width, pane_height, zoom);
    window.pixels(pair.right, ab ? pane_width+36 : 18, 132, pane_width, pane_height, zoom);
    const int base = 154 + pane_height;
    if (diagnostics) {
        pane_status(window, 18, base, ab ? pair.left_status : pair.right_status);
        if (ab) pane_status(window, pane_width+36, base, pair.right_status);
        window.text(18, base+140, "NPU: NOT TESTED, NOT ACTIVE | Model: UNVALIDATED | NPU timing: UNMEASURED", 0xffc76b);
        window.text(18, base+161, "Static source. Counters count completed scales, not repaints. Timings exclude X11 presentation. No measured FPS.");
        const auto error = pair.right_status.last_error;
        window.text(18, base+182, "Last error/fallback: " + (error ? error->code + ": " + error->message : "NONE"), error ? 0xffc76b : 0xdfe8f2);
        window.text(18, base+203, message);
    } else {
        window.text(18, base, "B: " + pair.right_status.backend_name + " | " + std::string(docksr::core::to_string(pair.right_status.evidence)) + " | " + std::string(docksr::core::to_string(pair.right_status.runtime_state)));
        window.text(18, base+22, "NPU NOT ACTIVE | Diagnostics hidden (D) | " + message);
    }
    window.flush();
}

int run(const Options& initial) {
    Options config = initial;
    Image source = config.input ? docksr::image::read_ppm(*config.input) : docksr::image::generate_pattern();
    Window window;
    docksr::preview::Controller controller(std::move(source));
    bool ab = true, diagnostics = true, zoom = false;
    std::string message = "Same unchanged raw source; equal processing dimensions. C captures this actual window if --capture was supplied.";
    auto process = [&] {
        try {
            const auto& frame = controller.process(config.output, config.filter, config.backend);
            if (config.status) {
                const auto result = docksr::core::publish_status_json(*config.status, frame.right_status);
                if (!result) throw std::runtime_error("Status publication failed: " + result.reason);
            }
            std::cout << docksr::core::serialize_status_json(frame.right_status) << '\n' << std::flush;
        } catch (const std::exception& error) {
            message = clean(error.what(), 1024);
            std::cerr << "preview: " << message << '\n';
            if (!controller.has_frame()) throw;
            if (config.status) {
                const auto result = docksr::core::publish_status_json(*config.status, controller.frame().right_status);
                if (!result) std::cerr << "preview: status not saved: " << clean(result.reason) << '\n';
            }
        }
    };
    process();
    draw(window, controller, config, ab, diagnostics, zoom, message);
    bool running = true;
    while (running) {
        const auto event = window.next();
        bool repaint = false, reprocess = false;
        if (window.is_close(event) || event.type == DestroyNotify) running = false;
        else if (event.type == ConfigureNotify) {
            window.resize(event.xconfigure.width, event.xconfigure.height); repaint = true;
        } else if (event.type == Expose && event.xexpose.count == 0) repaint = true;
        else if (event.type == KeyPress) {
            auto key_event = event.xkey;
            const auto key = XLookupKeysym(&key_event, 0);
            switch (key) {
            case XK_Escape: case XK_q: running = false; break;
            case XK_m: config.filter = config.filter == Filter::Nearest ? Filter::Bilinear : Filter::Nearest; reprocess = true; break;
            case XK_v: config.backend = config.backend == Backend::Cpu ? Backend::Vulkan : Backend::Cpu; reprocess = true; break;
            case XK_o: config.output = config.output.width == 1920 ? Extent{3840,2160} : Extent{1920,1080}; reprocess = true; break;
            case XK_r: controller.invalidate(); reprocess = true; break;
            case XK_a: ab = !ab; repaint = true; break;
            case XK_d: diagnostics = !diagnostics; repaint = true; break;
            case XK_z: zoom = !zoom; repaint = true; break;
            case XK_c:
                try {
                    if (!config.capture) throw std::runtime_error("Use --capture NEW.ppm to enable an actual-window capture");
                    window.capture(*config.capture);
                    message = "Captured executed X11 window (PPM); no overwrite: " + config.capture->filename().string();
                } catch (const std::exception& error) { message = clean(error.what(), 1024); }
                repaint = true; break;
            default: break;
            }
        }
        if (reprocess) { process(); repaint = true; }
        if (running && repaint) draw(window, controller, config, ab, diagnostics, zoom, message);
    }
    return 0;
}
} // namespace

int main(int argc, char** argv) {
    std::optional<Options> config;
    try { config = options(argc, argv); return run(*config); }
    catch (const std::exception& error) {
        docksr::core::StatusTracker status;
        const auto result = status.report_failure("preview_startup_failed", clean(error.what(), 1024));
        if (result) {
            std::cout << docksr::core::serialize_status_json(status.snapshot()) << '\n';
            if (config && config->status) {
                const auto saved = docksr::core::publish_status_json(*config->status, status.snapshot());
                if (!saved) std::cerr << "preview: startup status not saved: " << clean(saved.reason) << '\n';
            }
        }
        std::cerr << "preview: " << clean(error.what(), 1024) << '\n';
        return 2;
    }
}

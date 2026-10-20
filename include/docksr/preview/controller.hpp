#pragma once

#include "docksr/core/status_snapshot.hpp"
#include "docksr/image/image.hpp"

#include <functional>
#include <optional>
#include <string>

namespace docksr::preview {

enum class Backend { Cpu, Vulkan };

// The adapter must return completed pixels. No evidence is inferred from its name.
struct VulkanOutput {
    image::Image image;
    core::Evidence evidence{core::Evidence::None};
    std::string device_name;
    std::optional<double> gpu_ms;
    double host_ms{};
};
using VulkanProvider = std::function<VulkanOutput(const image::Image&, core::Extent, image::Filter)>;

struct FramePair {
    image::Image left;
    image::Image right;
    core::StatusSnapshot left_status;
    core::StatusSnapshot right_status;
};

// Headless, single-owner controller. The left pane is always a CPU nearest
// reference; the right pane uses the requested method/backend, with explicit CPU
// fallback. Both panes use identical output geometry and preserve the raw input.
class Controller {
public:
    explicit Controller(image::Image raw, VulkanProvider provider = {});
    const FramePair& process(core::Extent output,
                             image::Filter selected = image::Filter::Bilinear,
                             Backend requested = Backend::Cpu);
    const image::Image& raw() const noexcept { return raw_; }
    const FramePair& frame() const noexcept { return pair_; }
    bool has_frame() const noexcept;
    // Redraw/window size changes do not call invalidate. This explicitly requests
    // a new pair on the next process call (for a retry or new content in future).
    void invalidate() noexcept { dirty_ = true; }

private:
    image::Image raw_;
    VulkanProvider provider_;
    FramePair pair_;
    core::StatusTracker left_tracker_;
    core::StatusTracker right_tracker_;
    std::optional<core::Extent> output_;
    image::Filter selected_{image::Filter::Bilinear};
    Backend requested_{Backend::Cpu};
    bool dirty_{true};
};

} // namespace docksr::preview

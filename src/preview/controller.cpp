#include "docksr/preview/controller.hpp"

#ifdef DOCKSR_PREVIEW_VULKAN
#include "docksr/vulkan/scaler.hpp"
#endif

#include <chrono>
#include <cmath>
#include <memory>
#include <stdexcept>
#include <utility>

namespace docksr::preview {
namespace {

void require(const core::StatusResult& result) {
    if (!result) throw std::runtime_error("Preview status rejected: " + result.reason);
}

std::string error_message(const std::exception& error) {
    std::string message = error.what();
    if (message.empty()) message = "Preview backend failed";
    if (message.size() > 1024) message.resize(1024);
    return message;
}

std::string backend_name(std::string_view prefix, image::Filter filter) {
    return std::string(prefix) + "-" + std::string(image::filter_name(filter));
}

VulkanProvider default_provider() {
#ifdef DOCKSR_PREVIEW_VULKAN
    return [scaler = std::shared_ptr<vulkan::Scaler>{}](const image::Image& raw,
               core::Extent output, image::Filter filter) mutable -> VulkanOutput {
        if (!scaler) scaler = std::make_shared<vulkan::Scaler>();
        auto result = scaler->scale(raw, output.width, output.height, filter);
        const auto evidence = result.evidence == vulkan::DeviceEvidence::PhysicalGPU
            ? core::Evidence::RealGPU
            : result.evidence == vulkan::DeviceEvidence::Software
                ? core::Evidence::SoftwareVulkan : core::Evidence::None;
        return {std::move(result.image), evidence, std::move(result.device_name),
                result.gpu_ms, result.host_ms};
    };
#else
    return [](const image::Image&, core::Extent, image::Filter) -> VulkanOutput {
        throw std::runtime_error("Vulkan preview backend was not built; using the CPU reference");
    };
#endif
}

image::Image cpu_scale(const image::Image& raw, core::Extent output,
                      image::Filter filter, core::StatusTracker& status,
                      const std::string& fallback_reason = {}) {
    const core::Extent input{raw.width, raw.height};
    const auto name = backend_name("cpu-reference", filter);
    if (fallback_reason.empty())
        require(status.begin_cpu_reference(name, input, output));
    else
        require(status.begin_cpu_fallback(name, input, output,
                                         "vulkan_unavailable", fallback_reason));
    const auto start = std::chrono::steady_clock::now();
    auto completed = image::resize(raw, output.width, output.height, filter);
    const auto milliseconds = std::chrono::duration<double, std::milli>(
        std::chrono::steady_clock::now() - start).count();
    require(status.acknowledge_cpu_output(input, output, milliseconds));
    return completed;
}

} // namespace

Controller::Controller(image::Image raw, VulkanProvider provider)
    : raw_(std::move(raw)), provider_(provider ? std::move(provider) : default_provider()) {
    image::validate(raw_);
    pair_.left_status = left_tracker_.snapshot();
    pair_.right_status = right_tracker_.snapshot();
}

bool Controller::has_frame() const noexcept {
    return !pair_.left.rgb.empty() && !pair_.right.rgb.empty();
}

const FramePair& Controller::process(core::Extent output, image::Filter selected,
                                     Backend requested) {
    try {
        (void)image::checked_rgb_bytes(output.width, output.height);
        if (selected != image::Filter::Nearest && selected != image::Filter::Bilinear)
            throw std::invalid_argument("Unsupported preview scaling method");
        if (requested != Backend::Cpu && requested != Backend::Vulkan)
            throw std::invalid_argument("Unsupported preview backend");
        if (!dirty_ && output_ == output && selected_ == selected && requested_ == requested)
            return pair_;

        // Stage both image/status updates. A failed request never partially
        // publishes a pair or increments its completed-output counters.
        auto left_status = left_tracker_;
        auto right_status = right_tracker_;
        std::optional<image::Image> left;
        if (dirty_ || !output_ || *output_ != output)
            left = cpu_scale(raw_, output, image::Filter::Nearest, left_status);

        image::Image right;
        if (requested == Backend::Cpu) {
            right = cpu_scale(raw_, output, selected, right_status);
        } else {
            try {
                auto completed = provider_(raw_, output, selected);
                image::validate(completed.image);
                if (completed.image.width != output.width || completed.image.height != output.height)
                    throw std::runtime_error("Vulkan returned unexpected output dimensions");
                if (completed.evidence != core::Evidence::RealGPU &&
                    completed.evidence != core::Evidence::SoftwareVulkan)
                    throw std::runtime_error("Vulkan device evidence is unverified; using the CPU reference");
                if (!std::isfinite(completed.host_ms) || completed.host_ms < 0 ||
                    (completed.gpu_ms && (!std::isfinite(*completed.gpu_ms) || *completed.gpu_ms < 0)))
                    throw std::runtime_error("Vulkan returned an invalid timing observation");
                // The synchronous adapter identifies its device with completed
                // output. These staged transitions publish only that actual
                // evidence, never a guessed device type before initialization.
                require(right_status.begin_vulkan_reference(backend_name("vulkan-reference", selected),
                    {raw_.width, raw_.height}, output, completed.evidence));
                require(right_status.acknowledge_vulkan_output({raw_.width, raw_.height},
                    output, completed.gpu_ms));
                right = std::move(completed.image);
            } catch (const std::exception& error) {
                right = cpu_scale(raw_, output, selected, right_status, error_message(error));
            }
        }

        // Prepare potentially allocating snapshot copies before committing pixels.
        auto published_left_status = left_status.snapshot();
        auto published_right_status = right_status.snapshot();
        if (left) pair_.left = std::move(*left);
        pair_.right = std::move(right);
        left_tracker_ = std::move(left_status);
        right_tracker_ = std::move(right_status);
        pair_.left_status = std::move(published_left_status);
        pair_.right_status = std::move(published_right_status);
        output_ = output;
        selected_ = selected;
        requested_ = requested;
        dirty_ = false;
        return pair_;
    } catch (const std::exception& error) {
        dirty_ = true;
        require(right_tracker_.report_failure("preview_processing_failed", error_message(error)));
        pair_.right_status = right_tracker_.snapshot();
        throw;
    }
}

} // namespace docksr::preview

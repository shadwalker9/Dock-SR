#include "docksr/preview/controller.hpp"

#include <array>
#include <iostream>
#include <stdexcept>
#include <string>

namespace {
using docksr::core::Evidence;
using docksr::core::Extent;
using docksr::core::RuntimeState;
using docksr::image::Filter;
using docksr::image::Image;
using docksr::preview::Backend;
using docksr::preview::Controller;
using docksr::preview::VulkanOutput;

void require(bool condition, const std::string& message) {
    if (!condition) throw std::runtime_error(message);
}

template <typename Function>
void rejects(Function operation, const std::string& message) {
    bool rejected = false;
    try { operation(); } catch (const std::exception&) { rejected = true; }
    require(rejected, message);
}

void validate_status(const docksr::core::StatusSnapshot& status) {
    require(bool(docksr::core::validate_status_snapshot(status)), "Invalid preview status snapshot");
    require(!docksr::core::serialize_status_json(status).empty(), "Status serialization failed");
    require(!status.timings_ms.npu.has_value(), "Invented NPU timing");
    require(status.npu_model == docksr::core::ModelStatus::Unvalidated, "NPU model was validated");
}

void exact_pixels_and_cache() {
    const Image raw{2, 2, {0,0,0, 100,0,0, 0,100,0, 100,100,100}};
    Controller controller(raw);
    require(!controller.has_frame(), "Unprocessed controller has a completed frame");
    const auto& pair = controller.process({3,3});
    require(controller.raw().rgb == raw.rgb, "Raw source was modified");
    require(pair.left.width == pair.right.width && pair.left.height == pair.right.height,
            "A/B output geometry differs");
    require(pair.right.rgb == std::vector<std::uint8_t>{
        0,0,0, 50,0,0, 100,0,0,
        0,50,0, 50,50,25, 100,50,50,
        0,100,0, 50,100,50, 100,100,100}, "Bilinear output differs from explicit golden pixels");
    require(pair.left.rgb != pair.right.rgb, "Distinct A/B filters produced identical fixture output");
    require(pair.left_status.frames_processed == 1 && pair.right_status.frames_processed == 1,
            "Completed pair must increment each actual scaling operation once");
    const auto* left_storage = pair.left.rgb.data();
    const auto* right_storage = pair.right.rgb.data();
    for (int redraw = 0; redraw < 5; ++redraw) {
        const auto& cached = controller.process({3,3});
        require(cached.left.rgb.data() == left_storage && cached.right.rgb.data() == right_storage,
                "Redraw regenerated cached image storage");
        require(cached.left_status.frames_processed == 1 && cached.right_status.frames_processed == 1,
                "Redraw incremented a completed-output counter");
    }
    const auto& nearest = controller.process({3,3}, Filter::Nearest);
    require(nearest.left.rgb == nearest.right.rgb, "Selected nearest is not the same reference method");
    require(nearest.left_status.frames_processed == 1 && nearest.right_status.frames_processed == 2,
            "Changing right method reprocessed the unchanged left reference");
    require(nearest.right_status.evidence == Evidence::RealCPU, "CPU reference mislabeled");
    validate_status(nearest.left_status);
    validate_status(nearest.right_status);
    controller.invalidate();
    const auto& repeated = controller.process({3,3}, Filter::Nearest);
    require(repeated.left_status.frames_processed == 2 && repeated.right_status.frames_processed == 3,
            "Explicit invalidation did not process a new pair exactly once");
}

void full_resolution_dimensions() {
    auto raw = docksr::image::generate_pattern();
    const auto preserved = raw.rgb;
    Controller controller(std::move(raw));
    for (const auto output : std::array{Extent{1920,1080}, Extent{3840,2160}}) {
        const auto& pair = controller.process(output);
        for (const auto* image : {&pair.left, &pair.right}) {
            require(image->width == output.width && image->height == output.height,
                    "Requested processing canvas dimensions were not produced");
            require(image->rgb.size() == std::size_t(output.width) * output.height * 3,
                    "Completed output storage has an invalid length");
        }
        require(pair.left.rgb != pair.right.rgb, "720p A/B fixture has no filter difference");
        require(pair.right_status.actual_dimensions->input == Extent{1280,720}, "Wrong actual input dimensions");
        require(pair.right_status.actual_dimensions->output == output, "Wrong actual output dimensions");
        require(pair.right_status.evidence == Evidence::RealCPU, "CPU canvas mislabeled GPU");
        require(!pair.right_status.timings_ms.gpu && !pair.right_status.timings_ms.npu,
                "CPU canvas invented accelerator timings");
    }
    require(controller.raw().rgb == preserved, "Full-size processing changed raw input");
    require(controller.frame().right_status.frames_processed == 2, "Output-size change counted incorrectly");
}

void explicit_cpu_fallback() {
    unsigned attempts = 0;
    Controller controller(Image{2,1,{0,0,0,255,255,255}},
        [&attempts](const Image&, Extent, Filter) -> VulkanOutput {
            ++attempts;
            throw std::runtime_error("Injected unavailable Vulkan device");
        });
    const auto& pair = controller.process({4,2}, Filter::Bilinear, Backend::Vulkan);
    require(attempts == 1, "Provider was not attempted once");
    require(pair.right_status.runtime_state == RuntimeState::Fallback, "Fallback was hidden");
    require(pair.right_status.evidence == Evidence::RealCPU, "Fallback mislabeled as GPU");
    require(pair.right_status.backend_name == "cpu-reference-bilinear", "Wrong actual fallback method");
    require(pair.right_status.last_error && pair.right_status.last_error->message.find("Injected") != std::string::npos,
            "Fallback reason was lost");
    require(pair.right_status.frames_processed == 1, "Failed Vulkan attempt counted as completed output");
    controller.process({4,2}, Filter::Bilinear, Backend::Vulkan);
    require(attempts == 1, "Repaint retried an unavailable Vulkan device");
    require(controller.frame().right_status.frames_processed == 1, "Cached fallback incremented count");
    const auto& cpu = controller.process({4,2}, Filter::Bilinear, Backend::Cpu);
    require(cpu.right_status.runtime_state == RuntimeState::CpuReferenceActive && !cpu.right_status.last_error,
            "Explicit CPU selection retained a stale fallback state");
    require(cpu.right_status.frames_processed == 2, "CPU selection failed to count its actual output");
    validate_status(cpu.right_status);
}

void reject_untrusted_provider_output() {
    for (const bool wrong_dimensions : {false, true}) {
        Controller controller(Image{1,1,{10,20,30}},
            [wrong_dimensions](const Image& raw, Extent output, Filter filter) -> VulkanOutput {
                auto image = docksr::image::resize(raw, wrong_dimensions ? 1 : output.width,
                                                  wrong_dimensions ? 1 : output.height, filter);
                // Injected test data verifies rejection, never hardware execution.
                return {std::move(image), Evidence::None, "unverified test fixture", {}, 0};
            });
        const auto& pair = controller.process({3,3}, Filter::Nearest, Backend::Vulkan);
        require(pair.right.width == 3 && pair.right.height == 3, "Fallback dimensions differ");
        require(pair.right_status.runtime_state == RuntimeState::Fallback &&
                pair.right_status.evidence == Evidence::RealCPU, "Unverified adapter claimed GPU evidence");
        require(pair.right_status.frames_processed == 1, "Rejected provider output counted twice");
        validate_status(pair.right_status);
    }
}

void errors_preserve_completed_pixels_and_counts() {
    Controller controller(Image{1,1,{10,20,30}});
    controller.process({3,3});
    const auto original = controller.frame().right.rgb;
    rejects([&] { controller.process({0,3}); }, "Zero dimensions accepted");
    require(controller.frame().right.rgb == original, "Failed request replaced the previous pixels");
    require(controller.frame().right_status.frames_processed == 1, "Failed request incremented count");
    require(controller.frame().right_status.runtime_state == RuntimeState::Error &&
            controller.frame().right_status.last_error.has_value(), "Failed request lacks error status");
    validate_status(controller.frame().right_status);
    rejects([&] { controller.process({3,3}, static_cast<Filter>(255)); }, "Invalid filter accepted");
    rejects([&] { controller.process({3,3}, Filter::Nearest, static_cast<Backend>(255)); }, "Invalid backend accepted");
    rejects([] { Controller invalid(Image{2,2,{0}}); }, "Invalid source storage accepted");
}

} // namespace

int main() {
    try {
        exact_pixels_and_cache();
        full_resolution_dimensions();
        explicit_cpu_fallback();
        reject_untrusted_provider_output();
        errors_preserve_completed_pixels_and_counts();
        std::cout << "5 preview controller groups passed: pixels/cache, full-size canvases, fallback, rejected adapter output and errors\n";
        return 0;
    } catch (const std::exception& error) {
        std::cerr << "Preview controller failure: " << error.what() << '\n';
        return 1;
    }
}

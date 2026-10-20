#pragma once

#include "docksr/core/profile_registry.hpp"

#include <cstdint>
#include <filesystem>
#include <optional>
#include <string>
#include <string_view>

namespace docksr::core {

using MonotonicNs = std::uint64_t;
MonotonicNs monotonic_now_ns();

enum class RuntimeState {
  Starting, CpuReferenceActive, GpuBaselineActive, SoftwareVulkan, MockNpuActive,
  NpuReady, NpuActive, Fallback, Error, Bypass
};
enum class Evidence { None, RealCPU, RealGPU, SoftwareVulkan, Simulated, RealNPU };
enum class NpuDeviceStatus { NotTested, NotDetected, Detected, Error };
enum class ModelStatus { Unvalidated, Missing, Invalid };

struct StatusDimensions {
  Extent input;
  Extent output;
  bool operator==(const StatusDimensions&) const = default;
};

struct StatusTimings {
  std::optional<double> cpu;
  std::optional<double> gpu;
  std::optional<double> npu;
};

struct StatusError {
  std::string code;
  std::string message;
};

struct StatusSnapshot {
  RuntimeState runtime_state{RuntimeState::Starting};
  Evidence evidence{Evidence::None};
  std::string backend_name{"none"};
  std::optional<StatusDimensions> requested_dimensions;
  std::optional<StatusDimensions> actual_dimensions;
  std::uint64_t frames_processed{};
  std::optional<StatusError> last_error;
  NpuDeviceStatus npu_device{NpuDeviceStatus::NotTested};
  ModelStatus npu_model{ModelStatus::Unvalidated};
  StatusTimings timings_ms;
  MonotonicNs updated_at_monotonic_ns{};
};

struct StatusResult {
  bool accepted{};
  std::string reason;
  explicit operator bool() const { return accepted; }
};

// Single-owner state, with timestamps supplied by a same-host monotonic clock.
// None of these APIs establishes NPU readiness. Hardware NPU states are reserved
// and cannot be serialized or published by this increment.
class StatusTracker {
 public:
  explicit StatusTracker(MonotonicNs now = monotonic_now_ns());
  StatusResult begin_cpu_reference(std::string backend_name, Extent input,
                                  Extent requested_output,
                                  MonotonicNs now = monotonic_now_ns());
  StatusResult begin_cpu_fallback(std::string backend_name, Extent input,
                                 Extent requested_output, std::string code,
                                 std::string message,
                                 MonotonicNs now = monotonic_now_ns());
  // Trusted CPU writer acknowledgement, only AFTER output was successfully
  // produced and published. Starting/processing/failure never increments count.
  StatusResult acknowledge_cpu_output(Extent actual_input, Extent actual_output,
                                      std::optional<double> cpu_ms = {},
                                      MonotonicNs now = monotonic_now_ns());
  // One synchronous scaling operation per begin. Evidence is supplied by the
  // actual Vulkan engine; software and unknown devices cannot claim RealGPU.
  StatusResult begin_vulkan_reference(std::string backend_name, Extent input,
                                     Extent requested_output, Evidence evidence,
                                     MonotonicNs now = monotonic_now_ns());
  // Acknowledge only after scaling completed and output pixels are available
  // to the preview. Repainting existing pixels is not a new completed output.
  // gpu_ms, when present, is a measured Vulkan timestamp interval, not host time.
  StatusResult acknowledge_vulkan_output(Extent actual_input, Extent actual_output,
                                         std::optional<double> gpu_ms = {},
                                         MonotonicNs now = monotonic_now_ns());
  StatusResult report_failure(std::string code, std::string message,
                              bool fallback = false,
                              MonotonicNs now = monotonic_now_ns());
  StatusResult note_npu_device(NpuDeviceStatus status,
                               MonotonicNs now = monotonic_now_ns());
  StatusResult note_model(ModelStatus status,
                          MonotonicNs now = monotonic_now_ns());
  const StatusSnapshot& snapshot() const { return snapshot_; }

 private:
  StatusSnapshot snapshot_;
  bool vulkan_output_pending_{false};
};

StatusResult validate_status_snapshot(const StatusSnapshot& snapshot);
// Throws invalid_argument for an invalid or unsupported snapshot.
std::string serialize_status_json(const StatusSnapshot& snapshot);
// Future timestamps and observations outside this same-host monotonic clock
// cannot establish freshness. Exactly max_age_ns old is still fresh.
bool status_is_stale(const StatusSnapshot& snapshot, MonotonicNs now,
                     MonotonicNs max_age_ns);
// Destination must be in a directory owned by this effective user and not
// writable by group/others. Refuses symlinks, hardlinks and unrelated contents.
// Existing owner-only DockSR status documents may be atomically replaced.
StatusResult publish_status_json(const std::filesystem::path& path,
                                 const StatusSnapshot& snapshot);

std::string_view to_string(RuntimeState value);
std::string_view to_string(Evidence value);
std::string_view to_string(NpuDeviceStatus value);
std::string_view to_string(ModelStatus value);

}  // namespace docksr::core

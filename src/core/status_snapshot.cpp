#include "docksr/core/status_snapshot.hpp"

#include "docksr/core/json.hpp"

#include <algorithm>
#include <atomic>
#include <cerrno>
#include <chrono>
#include <cmath>
#include <cstring>
#include <iomanip>
#include <limits>
#include <locale>
#include <sstream>
#include <stdexcept>
#include <utility>

#include <fcntl.h>
#include <sys/stat.h>
#include <unistd.h>

namespace docksr::core {
namespace {
constexpr std::string_view document_prefix =
    "{\"schema_version\":\"1.0.0\",\"document_type\":\"docksr_status\",";

StatusResult accepted() { return {true, "accepted"}; }
StatusResult rejected(std::string reason) { return {false, std::move(reason)}; }

bool dimensions_valid(const StatusDimensions& value) {
  const auto valid = [](Extent size) {
    return size.width > 0 && size.height > 0 &&
           size.width <= 16384 && size.height <= 16384;
  };
  return valid(value.input) && valid(value.output);
}

bool token(std::string_view value, std::size_t maximum) {
  return !value.empty() && value.size() <= maximum &&
         std::all_of(value.begin(), value.end(), [](unsigned char c) {
           return (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') ||
                  (c >= '0' && c <= '9') || c == '_' || c == '-' || c == '.';
         });
}

bool timing_valid(const std::optional<double>& value) {
  return !value || (std::isfinite(*value) && *value >= 0.0);
}

bool terminal_state(RuntimeState state) {
  return state == RuntimeState::Error || state == RuntimeState::Fallback ||
         state == RuntimeState::Bypass;
}

std::string dimensions_json(const std::optional<StatusDimensions>& value) {
  if (!value) return "null";
  return "{\"input\":{\"width\":" + std::to_string(value->input.width) +
         ",\"height\":" + std::to_string(value->input.height) +
         "},\"output\":{\"width\":" + std::to_string(value->output.width) +
         ",\"height\":" + std::to_string(value->output.height) + "}}";
}

class FileDescriptor {
 public:
  explicit FileDescriptor(int fd) : fd_(fd) {}
  ~FileDescriptor() { if (fd_ >= 0) ::close(fd_); }
  FileDescriptor(const FileDescriptor&) = delete;
  FileDescriptor& operator=(const FileDescriptor&) = delete;
  int get() const { return fd_; }
 private:
  int fd_;
};

StatusResult system_error(std::string_view operation) {
  const int saved_errno = errno;
  return rejected(std::string(operation) + ": " + std::strerror(saved_errno));
}
}  // namespace

MonotonicNs monotonic_now_ns() {
  const auto elapsed = std::chrono::steady_clock::now().time_since_epoch();
  const auto count = std::chrono::duration_cast<std::chrono::nanoseconds>(elapsed).count();
  return count < 0 ? 0 : static_cast<MonotonicNs>(count);
}

StatusTracker::StatusTracker(MonotonicNs now) {
  snapshot_.updated_at_monotonic_ns = now;
}

StatusResult StatusTracker::begin_cpu_reference(std::string backend, Extent input,
                                               Extent output, MonotonicNs now) {
  if (now < snapshot_.updated_at_monotonic_ns) return rejected("monotonic_time_went_backwards");
  auto next = snapshot_;
  next.runtime_state = RuntimeState::CpuReferenceActive;
  next.evidence = Evidence::RealCPU;
  next.backend_name = std::move(backend);
  next.requested_dimensions = StatusDimensions{input, output};
  next.last_error.reset();
  next.timings_ms = {};
  next.updated_at_monotonic_ns = now;
  const auto validation = validate_status_snapshot(next);
  if (!validation) return validation;
  snapshot_ = std::move(next);
  vulkan_output_pending_ = false;
  return accepted();
}

StatusResult StatusTracker::begin_cpu_fallback(
    std::string backend, Extent input, Extent output, std::string code,
    std::string message, MonotonicNs now) {
  if (now < snapshot_.updated_at_monotonic_ns) return rejected("monotonic_time_went_backwards");
  auto next = snapshot_;
  next.runtime_state = RuntimeState::Fallback;
  next.evidence = Evidence::RealCPU;
  next.backend_name = std::move(backend);
  next.requested_dimensions = StatusDimensions{input, output};
  next.last_error = StatusError{std::move(code), std::move(message)};
  next.timings_ms = {};
  next.updated_at_monotonic_ns = now;
  const auto validation = validate_status_snapshot(next);
  if (!validation) return validation;
  snapshot_ = std::move(next);
  vulkan_output_pending_ = false;
  return accepted();
}

StatusResult StatusTracker::acknowledge_cpu_output(
    Extent input, Extent output, std::optional<double> cpu_ms, MonotonicNs now) {
  if (now < snapshot_.updated_at_monotonic_ns) return rejected("monotonic_time_went_backwards");
  if ((snapshot_.runtime_state != RuntimeState::CpuReferenceActive &&
       snapshot_.runtime_state != RuntimeState::Fallback) ||
      snapshot_.evidence != Evidence::RealCPU || !snapshot_.requested_dimensions)
    return rejected("cpu_reference_not_active");
  if (snapshot_.frames_processed == std::numeric_limits<std::uint64_t>::max())
    return rejected("completed_frame_counter_exhausted");
  auto next = snapshot_;
  next.actual_dimensions = StatusDimensions{input, output};
  next.timings_ms = {cpu_ms, {}, {}};
  ++next.frames_processed;
  if (next.runtime_state != RuntimeState::Fallback) next.last_error.reset();
  next.updated_at_monotonic_ns = now;
  const auto validation = validate_status_snapshot(next);
  if (!validation) return validation;
  snapshot_ = std::move(next);
  return accepted();
}

StatusResult StatusTracker::begin_vulkan_reference(
    std::string backend, Extent input, Extent output, Evidence evidence,
    MonotonicNs now) {
  if (now < snapshot_.updated_at_monotonic_ns) return rejected("monotonic_time_went_backwards");
  if (evidence != Evidence::RealGPU && evidence != Evidence::SoftwareVulkan)
    return rejected("vulkan_requires_physical_gpu_or_software_vulkan_evidence");
  if (vulkan_output_pending_) return rejected("vulkan_operation_already_pending");
  auto next = snapshot_;
  next.runtime_state = evidence == Evidence::RealGPU
                           ? RuntimeState::GpuBaselineActive
                           : RuntimeState::SoftwareVulkan;
  next.evidence = evidence;
  next.backend_name = std::move(backend);
  next.requested_dimensions = StatusDimensions{input, output};
  next.last_error.reset();
  next.timings_ms = {};
  next.updated_at_monotonic_ns = now;
  const auto validation = validate_status_snapshot(next);
  if (!validation) return validation;
  snapshot_ = std::move(next);
  vulkan_output_pending_ = true;
  return accepted();
}

StatusResult StatusTracker::acknowledge_vulkan_output(
    Extent input, Extent output, std::optional<double> gpu_ms, MonotonicNs now) {
  if (now < snapshot_.updated_at_monotonic_ns) return rejected("monotonic_time_went_backwards");
  const bool active =
      (snapshot_.runtime_state == RuntimeState::GpuBaselineActive && snapshot_.evidence == Evidence::RealGPU) ||
      (snapshot_.runtime_state == RuntimeState::SoftwareVulkan && snapshot_.evidence == Evidence::SoftwareVulkan);
  if (!vulkan_output_pending_ || !active || !snapshot_.requested_dimensions)
    return rejected("vulkan_output_not_pending");
  if (snapshot_.frames_processed == std::numeric_limits<std::uint64_t>::max())
    return rejected("completed_frame_counter_exhausted");
  auto next = snapshot_;
  next.actual_dimensions = StatusDimensions{input, output};
  next.timings_ms = {{}, gpu_ms, {}};
  ++next.frames_processed;
  next.last_error.reset();
  next.updated_at_monotonic_ns = now;
  const auto validation = validate_status_snapshot(next);
  if (!validation) return validation;
  snapshot_ = std::move(next);
  vulkan_output_pending_ = false;
  return accepted();
}

StatusResult StatusTracker::report_failure(std::string code, std::string message,
                                          bool fallback, MonotonicNs now) {
  if (now < snapshot_.updated_at_monotonic_ns) return rejected("monotonic_time_went_backwards");
  auto next = snapshot_;
  next.runtime_state = fallback ? RuntimeState::Fallback : RuntimeState::Error;
  next.last_error = StatusError{std::move(code), std::move(message)};
  next.timings_ms = {};
  next.updated_at_monotonic_ns = now;
  const auto validation = validate_status_snapshot(next);
  if (!validation) return validation;
  snapshot_ = std::move(next);
  vulkan_output_pending_ = false;
  return accepted();
}

StatusResult StatusTracker::note_npu_device(NpuDeviceStatus status, MonotonicNs now) {
  if (now < snapshot_.updated_at_monotonic_ns) return rejected("monotonic_time_went_backwards");
  auto next = snapshot_;
  next.npu_device = status;
  next.updated_at_monotonic_ns = now;
  const auto validation = validate_status_snapshot(next);
  if (!validation) return validation;
  snapshot_ = std::move(next);
  return accepted();
}

StatusResult StatusTracker::note_model(ModelStatus status, MonotonicNs now) {
  if (now < snapshot_.updated_at_monotonic_ns) return rejected("monotonic_time_went_backwards");
  auto next = snapshot_;
  next.npu_model = status;
  next.updated_at_monotonic_ns = now;
  const auto validation = validate_status_snapshot(next);
  if (!validation) return validation;
  snapshot_ = std::move(next);
  return accepted();
}

StatusResult validate_status_snapshot(const StatusSnapshot& snapshot) {
  if (snapshot.runtime_state == RuntimeState::NpuReady ||
      snapshot.runtime_state == RuntimeState::NpuActive || snapshot.evidence == Evidence::RealNPU)
    return rejected("real_npu_status_unavailable_in_this_build");
  if (to_string(snapshot.runtime_state) == "UNKNOWN_ENUM" ||
      to_string(snapshot.evidence) == "UNKNOWN_ENUM" ||
      to_string(snapshot.npu_device) == "UNKNOWN_ENUM" ||
      to_string(snapshot.npu_model) == "UNKNOWN_ENUM")
    return rejected("invalid_status_enum");
  const bool compatible = terminal_state(snapshot.runtime_state) ||
      (snapshot.runtime_state == RuntimeState::Starting && snapshot.evidence == Evidence::None) ||
      (snapshot.runtime_state == RuntimeState::CpuReferenceActive && snapshot.evidence == Evidence::RealCPU) ||
      (snapshot.runtime_state == RuntimeState::GpuBaselineActive && snapshot.evidence == Evidence::RealGPU) ||
      (snapshot.runtime_state == RuntimeState::SoftwareVulkan && snapshot.evidence == Evidence::SoftwareVulkan) ||
      (snapshot.runtime_state == RuntimeState::MockNpuActive && snapshot.evidence == Evidence::Simulated);
  if (!compatible) return rejected("runtime_state_evidence_mismatch");
  if (!token(snapshot.backend_name, 128)) return rejected("invalid_backend_name");
  if ((snapshot.requested_dimensions && !dimensions_valid(*snapshot.requested_dimensions)) ||
      (snapshot.actual_dimensions && !dimensions_valid(*snapshot.actual_dimensions)))
    return rejected("invalid_status_dimensions");
  if (snapshot.actual_dimensions && !snapshot.requested_dimensions)
    return rejected("actual_dimensions_without_request");
  if (snapshot.frames_processed > 0 && (!snapshot.actual_dimensions || snapshot.evidence == Evidence::None))
    return rejected("completed_frames_without_actual_output");
  if (snapshot.frames_processed == 0 && snapshot.actual_dimensions)
    return rejected("actual_dimensions_without_completed_output");
  if (!terminal_state(snapshot.runtime_state) && snapshot.runtime_state != RuntimeState::Starting &&
      !snapshot.requested_dimensions)
    return rejected("active_backend_without_requested_dimensions");
  if (snapshot.last_error && (!token(snapshot.last_error->code, 64) ||
      snapshot.last_error->message.empty() || snapshot.last_error->message.size() > 1024))
    return rejected("invalid_status_error");
  if ((snapshot.runtime_state == RuntimeState::Error || snapshot.runtime_state == RuntimeState::Fallback) &&
      !snapshot.last_error)
    return rejected("failure_status_without_reason");
  const auto& timing = snapshot.timings_ms;
  if (!timing_valid(timing.cpu) || !timing_valid(timing.gpu) || !timing_valid(timing.npu))
    return rejected("nonfinite_or_negative_timing");
  const bool has_timing = timing.cpu || timing.gpu || timing.npu;
  if (has_timing && snapshot.frames_processed == 0)
    return rejected("timing_without_completed_output");
  if (timing.npu) return rejected("npu_timing_unavailable_in_this_build");
  if (snapshot.evidence == Evidence::Simulated && has_timing)
    return rejected("simulated_status_cannot_report_physical_timing");
  if (snapshot.evidence == Evidence::RealCPU && timing.gpu)
    return rejected("cpu_status_cannot_report_gpu_timing");
  return accepted();
}

std::string serialize_status_json(const StatusSnapshot& snapshot) {
  const auto result = validate_status_snapshot(snapshot);
  if (!result) throw std::invalid_argument(result.reason);
  std::ostringstream out;
  out.imbue(std::locale::classic());
  out << std::setprecision(std::numeric_limits<double>::max_digits10)
      << document_prefix << "\"runtime_state\":" << json_string(to_string(snapshot.runtime_state))
      << ",\"evidence\":" << json_string(to_string(snapshot.evidence))
      << ",\"backend_name\":" << json_string(snapshot.backend_name)
      << ",\"dimensions\":{\"requested\":" << dimensions_json(snapshot.requested_dimensions)
      << ",\"actual\":" << dimensions_json(snapshot.actual_dimensions)
      << "},\"frames_processed\":" << snapshot.frames_processed << ",\"last_error\":";
  if (snapshot.last_error)
    out << "{\"code\":" << json_string(snapshot.last_error->code)
        << ",\"message\":" << json_string(snapshot.last_error->message) << '}';
  else out << "null";
  out << ",\"npu\":{\"device_status\":" << json_string(to_string(snapshot.npu_device))
      << ",\"model_status\":" << json_string(to_string(snapshot.npu_model))
      << "},\"timings_ms\":{\"cpu\":";
  const auto write_timing = [&out](const std::optional<double>& value) {
    if (value) out << *value;
    else out << "null";
  };
  write_timing(snapshot.timings_ms.cpu);
  out << ",\"gpu\":";
  write_timing(snapshot.timings_ms.gpu);
  out << ",\"npu\":";
  write_timing(snapshot.timings_ms.npu);
  out << "},\"updated_at_monotonic_ns\":" << snapshot.updated_at_monotonic_ns << '}';
  return out.str();
}

bool status_is_stale(const StatusSnapshot& snapshot, MonotonicNs now, MonotonicNs max_age) {
  return !validate_status_snapshot(snapshot) || now < snapshot.updated_at_monotonic_ns ||
         now - snapshot.updated_at_monotonic_ns > max_age;
}

StatusResult publish_status_json(const std::filesystem::path& path,
                                 const StatusSnapshot& snapshot) {
  const auto validation = validate_status_snapshot(snapshot);
  if (!validation) return validation;
  const auto name = path.filename().string();
  if (name.empty() || name == "." || name == "..") return rejected("invalid_status_path");
  const auto parent = path.has_parent_path() ? path.parent_path() : std::filesystem::path(".");
  const FileDescriptor directory(::open(parent.c_str(), O_RDONLY | O_DIRECTORY | O_CLOEXEC | O_NOFOLLOW));
  if (directory.get() < 0) return system_error("status_parent_open_failed");
  struct stat parent_info {};
  if (::fstat(directory.get(), &parent_info) < 0) return system_error("status_parent_stat_failed");
  if (parent_info.st_uid != ::geteuid() || (parent_info.st_mode & 0022) != 0)
    return rejected("status_parent_must_be_owned_and_not_group_or_world_writable");

  bool replacing = false;
  struct stat prior_info {};
  {
    const FileDescriptor prior(::openat(directory.get(), name.c_str(),
        O_RDONLY | O_CLOEXEC | O_NOFOLLOW | O_NONBLOCK));
    if (prior.get() >= 0) {
      if (::fstat(prior.get(), &prior_info) < 0) return system_error("status_target_stat_failed");
      if (!S_ISREG(prior_info.st_mode) || prior_info.st_uid != ::geteuid() ||
          (prior_info.st_mode & 0777) != 0600 || prior_info.st_nlink != 1)
        return rejected("status_target_must_be_owner_regular_0600_without_hardlinks");
      std::string prefix(document_prefix.size(), '\0');
      const auto length = ::pread(prior.get(), prefix.data(), prefix.size(), 0);
      if (length != static_cast<ssize_t>(prefix.size()) || prefix != document_prefix)
        return rejected("refusing_to_replace_unrelated_file");
      replacing = true;
    } else if (errno != ENOENT) {
      return system_error("status_target_open_failed");
    }
  }

  static std::atomic<std::uint64_t> sequence{0};
  std::string temporary;
  int temporary_fd = -1;
  for (int attempt = 0; attempt < 64; ++attempt) {
    temporary = ".docksr-status-" + std::to_string(::getpid()) + "-" +
                std::to_string(sequence.fetch_add(1, std::memory_order_relaxed));
    temporary_fd = ::openat(directory.get(), temporary.c_str(),
        O_WRONLY | O_CREAT | O_EXCL | O_CLOEXEC | O_NOFOLLOW, 0600);
    if (temporary_fd >= 0) break;
    if (errno != EEXIST) return system_error("status_temporary_open_failed");
  }
  if (temporary_fd < 0) return rejected("status_temporary_name_exhausted");
  const FileDescriptor output(temporary_fd);
  struct RemoveTemporary {
    int directory;
    const std::string& name;
    ~RemoveTemporary() { ::unlinkat(directory, name.c_str(), 0); }
  } cleanup{directory.get(), temporary};
  if (::fchmod(output.get(), 0600) < 0) return system_error("status_temporary_mode_failed");
  const auto contents = serialize_status_json(snapshot) + '\n';
  std::size_t position = 0;
  while (position < contents.size()) {
    const auto count = ::write(output.get(), contents.data() + position, contents.size() - position);
    if (count < 0) {
      if (errno == EINTR) continue;
      return system_error("status_write_failed");
    }
    if (count == 0) return rejected("status_write_made_no_progress");
    position += static_cast<std::size_t>(count);
  }
  if (::fsync(output.get()) < 0) return system_error("status_file_fsync_failed");
  if (replacing) {
    struct stat current_info {};
    if (::fstatat(directory.get(), name.c_str(), &current_info, AT_SYMLINK_NOFOLLOW) < 0)
      return system_error("status_target_recheck_failed");
    if (current_info.st_dev != prior_info.st_dev || current_info.st_ino != prior_info.st_ino ||
        !S_ISREG(current_info.st_mode) || current_info.st_nlink != 1 ||
        current_info.st_uid != ::geteuid() || (current_info.st_mode & 0777) != 0600)
      return rejected("status_target_changed_during_publish");
    if (::renameat(directory.get(), temporary.c_str(), directory.get(), name.c_str()) < 0)
      return system_error("status_atomic_replace_failed");
  } else {
    // Atomic no-replace creation: a concurrently appearing unrelated target is
    // preserved. The temporary and destination are on the same filesystem.
    if (::linkat(directory.get(), temporary.c_str(), directory.get(), name.c_str(), 0) < 0)
      return system_error("status_atomic_create_failed");
    if (::unlinkat(directory.get(), temporary.c_str(), 0) < 0)
      return system_error("status_published_temporary_cleanup_failed");
  }
  if (::fsync(directory.get()) < 0)
    return system_error("status_published_directory_fsync_failed");
  return accepted();
}

std::string_view to_string(RuntimeState value) {
  switch (value) {
    case RuntimeState::Starting: return "STARTING";
    case RuntimeState::CpuReferenceActive: return "CPU_REFERENCE_ACTIVE";
    case RuntimeState::GpuBaselineActive: return "GPU_BASELINE_ACTIVE";
    case RuntimeState::SoftwareVulkan: return "SOFTWARE_VULKAN";
    case RuntimeState::MockNpuActive: return "MOCK_NPU_ACTIVE";
    case RuntimeState::NpuReady: return "NPU_READY";
    case RuntimeState::NpuActive: return "NPU_ACTIVE";
    case RuntimeState::Fallback: return "FALLBACK";
    case RuntimeState::Error: return "ERROR";
    case RuntimeState::Bypass: return "BYPASS";
  }
  return "UNKNOWN_ENUM";
}

std::string_view to_string(Evidence value) {
  switch (value) {
    case Evidence::None: return "NONE";
    case Evidence::RealCPU: return "REAL_CPU";
    case Evidence::RealGPU: return "REAL_GPU";
    case Evidence::SoftwareVulkan: return "SOFTWARE_VULKAN";
    case Evidence::Simulated: return "SIMULATED";
    case Evidence::RealNPU: return "REAL_NPU";
  }
  return "UNKNOWN_ENUM";
}

std::string_view to_string(NpuDeviceStatus value) {
  switch (value) {
    case NpuDeviceStatus::NotTested: return "NOT_TESTED";
    case NpuDeviceStatus::NotDetected: return "NOT_DETECTED";
    case NpuDeviceStatus::Detected: return "DETECTED";
    case NpuDeviceStatus::Error: return "ERROR";
  }
  return "UNKNOWN_ENUM";
}

std::string_view to_string(ModelStatus value) {
  switch (value) {
    case ModelStatus::Unvalidated: return "UNVALIDATED";
    case ModelStatus::Missing: return "MISSING";
    case ModelStatus::Invalid: return "INVALID";
  }
  return "UNKNOWN_ENUM";
}
}  // namespace docksr::core

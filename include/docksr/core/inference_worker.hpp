#pragma once

#include "docksr/core/frame_scheduler.hpp"

#include <cstddef>
#include <cstdint>
#include <functional>
#include <optional>
#include <span>
#include <string>
#include <string_view>
#include <vector>

namespace docksr::inference {

using Nanoseconds = std::uint64_t;
using Ticket = core::FrameTicket;

struct Extent {
  std::uint32_t width{}, height{};
  bool operator==(const Extent&) const = default;
};

struct TilePlacement {
  std::uint32_t source_x{}, source_y{}, core_width{}, core_height{};
  std::uint32_t halo_left{}, halo_top{}, halo_right{}, halo_bottom{};
  std::uint32_t output_x{}, output_y{}, output_width{}, output_height{};
  bool operator==(const TilePlacement&) const = default;
};

// Monotonic nanoseconds in one explicitly shared clock domain, not wall-clock
// timestamps. Contiguous byte strides only in this bounded first interface.
struct Request {
  std::string schema_version{"1.0.0"};
  std::string session_id;
  std::uint64_t frame_id{}, configuration_generation{};
  std::string model_id, model_sha256;
  Extent source_extent;
  std::string source_format{"RGB8"};
  std::vector<std::uint64_t> tensor_shape;
  std::string tensor_dtype{"int8"}, tensor_layout{"NHWC"};
  std::uint64_t buffer_size{};
  std::vector<std::uint64_t> buffer_stride;
  std::string buffer_ownership{"TRANSFERRED_HOST"};
  Nanoseconds submit_timestamp{}, deadline{};
  std::string trace_id;
  std::optional<TilePlacement> tile;
  // An exact expected output signature permits admission-time reservation.
  Extent expected_output_extent;
  std::string expected_output_format{"RGB_INT8"};
  std::vector<std::uint64_t> expected_output_shape;
  std::string expected_output_dtype{"int8"}, expected_output_layout{"NHWC"};
};

struct Ledger {
  std::uint64_t source_logical_bytes{};
  std::uint64_t tensor_preparation_read_bytes{}, tensor_preparation_write_bytes{};
  std::uint64_t host_copy_bytes{}, host_copy_count{};
  std::string host_copy_direction{"NONE"};
  std::string host_copy_scope{"CALLER_VISIBLE_ONLY"};
  std::uint64_t inference_input_logical_bytes{}, inference_output_logical_bytes{};
  std::uint64_t tile_count{}, tile_overlap_pixels{}, stitched_output_bytes{}, crop_bytes{};
  std::optional<std::uint64_t> gpu_upload_bytes;
  // Owned host-vector capacities observed by this interface only. Runtime
  // allocator/internal copies are unknown, never represented as zero traffic.
  std::uint64_t allocation_high_water_bytes{};
  std::optional<Nanoseconds> submit_to_complete_duration;
  std::optional<Nanoseconds> complete_to_consume_duration;
  bool deadline_missed{};
  std::string timing_class{"NOT_RUN"};
  std::string runtime_internal_allocation_status{"UNKNOWN"};
  std::string runtime_internal_copy_status{"UNKNOWN"};
};

struct Result {
  std::string schema_version{"1.0.0"};
  std::string session_id;
  std::uint64_t frame_id{}, configuration_generation{};
  std::string model_id, model_sha256, trace_id;
  Extent output_extent;
  std::string output_format, output_dtype, output_layout;
  std::vector<std::uint64_t> output_shape;
  std::string backend_kind{"UNAVAILABLE"}, evidence_class{"NOT_RUN"};
  bool valid{};
  Nanoseconds completion_timestamp{};
  std::uint64_t copy_count{}, logical_bytes{};
  std::optional<Nanoseconds> inference_duration;
  std::string fallback_reason;
  std::vector<std::uint8_t> output;
  Ledger ledger;
};

// Real CPU implementations are injected at this boundary. The executor must
// execute a reviewed CPU workload now, not relabel mock/cached output as CPU.
class Backend {
 public:
  virtual ~Backend() = default;
  virtual std::string_view kind() const = 0;
  virtual Result execute(const Request&, std::span<const std::uint8_t>) = 0;
};

class CpuReferenceBackend final : public Backend {
 public:
  using Executor = std::function<Result(const Request&, std::span<const std::uint8_t>)>;
  explicit CpuReferenceBackend(Executor executor);
  std::string_view kind() const override { return "CPU_REFERENCE"; }
  Result execute(const Request&, std::span<const std::uint8_t>) override;
 private:
  Executor executor_;
};

class UnavailableBackend final : public Backend {
 public:
  std::string_view kind() const override { return "UNAVAILABLE"; }
  Result execute(const Request&, std::span<const std::uint8_t>) override;
};

class DeterministicMockBackend final : public Backend {
 public:
  explicit DeterministicMockBackend(Nanoseconds assumed_duration = 1) : duration_(assumed_duration) {}
  std::string_view kind() const override { return "DETERMINISTIC_MOCK"; }
  Result execute(const Request&, std::span<const std::uint8_t>) override;
 private:
  Nanoseconds duration_;
};

struct Limits {
  std::size_t max_in_flight{2};
  std::uint64_t max_queue_bytes{64u * 1024u * 1024u};
  std::uint64_t max_result_bytes{128u * 1024u * 1024u};
  std::uint64_t max_tensor_bytes{64u * 1024u * 1024u};
};

struct Submission {
  bool accepted{};
  std::optional<Ticket> ticket;
  std::string reason;
};

struct WorkItem {
  Ticket ticket;
  const Request* request{};
  std::span<const std::uint8_t> input;
};

struct Counts {
  std::uint64_t submitted{}, completed{}, consumed{}, released{}, rejected{};
  std::uint64_t discarded{}, stale_events{}, fallback_count{};
};

// One trusted owner thread. This is a bounded producer/consumer adapter around
// FrameScheduler, not a presentation scheduler, IPC service or NPU backend.
// WorkItem views remain valid until completion/acknowledged producer stop.
// Consumer Result views remain valid until explicit release. On shutdown or
// invalidation, active producer/consumer storage is retained until completion
// or an explicit acknowledgement that ALL accesses have ceased.
class Worker {
 public:
  Worker(std::string session_id, std::uint64_t generation = 1, Limits limits = {});
  // This owner has stable identity while request/result views escape. Copying
  // would duplicate active tickets; assignment/movement can invalidate views
  // without the producer/consumer acknowledgements required below.
  Worker(const Worker&) = delete;
  Worker& operator=(const Worker&) = delete;
  Worker(Worker&&) = delete;
  Worker& operator=(Worker&&) = delete;
  Submission submit(Request request, std::vector<std::uint8_t> input, Nanoseconds now);
  std::optional<WorkItem> start_next(Nanoseconds now);
  bool complete(Ticket, Result, Nanoseconds now);
  const Result* consume(Ticket, std::string_view session_id, std::uint64_t frame_id,
                        std::uint64_t generation, Nanoseconds now);
  bool release(Ticket, Nanoseconds now);
  bool advance(Nanoseconds now);
  bool invalidate(std::uint64_t new_generation, Nanoseconds now);
  bool shutdown(Nanoseconds now);
  bool acknowledge_quiescence(Nanoseconds now);

  std::size_t in_flight() const { return scheduler_.in_flight(); }
  std::uint64_t queue_bytes() const { return input_owned_bytes_; }
  std::uint64_t reserved_result_bytes() const { return reserved_result_bytes_; }
  std::uint64_t result_bytes() const { return result_owned_bytes_; }
  std::uint64_t allocation_high_water_bytes() const { return high_water_bytes_; }
  std::uint64_t generation() const { return generation_; }
  bool shutting_down() const { return shutting_down_; }
  bool shutdown_complete() const { return shutting_down_ && in_flight() == 0; }
  const Counts& counts() const { return counts_; }
  const std::string& last_error() const { return last_error_; }

 private:
  enum class Phase { Queued, Running, Ready, Consuming };
  struct Entry {
    Request request;
    std::vector<std::uint8_t> input;
    std::optional<Result> result;
    Ticket ticket;
    std::uint64_t output_reservation{};
    Phase phase{Phase::Queued};
    Nanoseconds started_at{};
    bool invalidated{}, fallback_reported{};
  };
  std::string session_id_;
  std::uint64_t generation_, last_frame_id_{};
  Limits limits_;
  core::FrameScheduler scheduler_;
  std::vector<std::optional<Entry>> entries_;
  Counts counts_;
  bool shutting_down_{};
  Nanoseconds now_{};
  std::uint64_t input_owned_bytes_{}, reserved_result_bytes_{}, result_owned_bytes_{}, high_water_bytes_{};
  std::string last_error_;
  Entry* find(Ticket);
  void erase(std::size_t slot);
  void fallback(Entry&, std::string_view reason);
  void observe_allocation();
  bool reject_event(std::string_view reason);
};

// Helpers used by the reviewed CPU bridge and independent schema consumers.
std::optional<std::uint64_t> tensor_bytes(std::span<const std::uint64_t> shape,
                                        std::string_view dtype);
std::vector<std::uint64_t> contiguous_strides(std::span<const std::uint64_t> shape,
                                            std::string_view dtype);
std::string validate_request(const Request&, std::uint64_t max_tensor_bytes);
Result failure(const Request&, std::string_view backend, std::string_view evidence,
               std::string_view reason, Nanoseconds completed_at);
std::string request_json(const Request&);
std::string result_json(const Result&);
std::string ledger_json(const Ledger&);
std::string future_backends_json();

}  // namespace docksr::inference

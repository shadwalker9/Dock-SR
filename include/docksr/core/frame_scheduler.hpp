#pragma once

#include <cstddef>
#include <cstdint>
#include <deque>
#include <optional>
#include <string_view>
#include <vector>

namespace docksr::core {

using Tick = std::uint64_t;  // Virtual simulation units; never physical timing.

struct FrameTicket {
  std::size_t slot{};
  std::uint64_t generation{};
  std::uint64_t serial{};
  bool operator==(const FrameTicket&) const = default;
};

enum class FrameDecision {
  Submitted, OutputReady, FallbackDeadline, FallbackExhausted,
  FallbackUnavailable, FallbackDuplicateFrame, FallbackResize, FallbackSuspend,
  FallbackCrash, CompletionDiscarded, StaleCompletion, Resized, Suspended,
  Resumed, BackendCrashed, QuiescenceAcknowledged, Restarted,
  OutputConsumed, OutputReleased, FallbackStaleOutput,
  InvalidConsumerAcquire, InvalidConsumerRelease
};

enum class SchedulerState { Running, Suspended, Crashed };

struct FrameEvent {
  FrameDecision decision;
  std::optional<std::uint64_t> frame_id;
  std::optional<FrameTicket> ticket;
  Tick at_tick{};
};

struct Submission {
  FrameDecision decision;
  std::optional<FrameTicket> ticket;
};

struct SchedulerCounts {
  std::uint64_t submitted{};
  std::uint64_t outputs{};
  std::uint64_t outputs_consumed{};
  std::uint64_t consumer_releases{};
  std::uint64_t fallbacks{};
  std::uint64_t discarded_completions{};
  std::uint64_t stale_completions{};
  std::uint64_t dropped_events{};
};

// Deterministic ownership model, not an inference backend. Single-owner API.
// Deadlines never release an owned slot. Producer completion makes output ready;
// consumer acquisition and completion/release are separate acknowledgements.
class FrameScheduler {
 public:
  static constexpr std::size_t max_slots = 64;
  static constexpr std::size_t event_capacity = 256;
  explicit FrameScheduler(std::size_t capacity = 2);

  Submission submit(std::uint64_t frame_id, Tick now, Tick deadline);
  FrameDecision complete(FrameTicket ticket, Tick now);
  // Accepts increasing frame IDs within the current generation. The future
  // adapter must still preserve GPU/WSI order and check generation at present.
  FrameDecision consume_output(FrameTicket ticket, Tick now);
  // Called only once the GPU consumer has finished ALL access, or the adapter
  // has established that ready output will never be submitted to a consumer.
  FrameDecision release_output(FrameTicket ticket, Tick now);
  void advance_to(Tick now);
  void resize(Tick now);
  void suspend(Tick now);
  bool resume(Tick now);
  void crash(Tick now);
  // Trusted acknowledgement: ALL GPU consumers and NPU producers have stopped
  // accessing memory. A timeout or NPU process exit alone is not such evidence.
  bool acknowledge_quiescence(Tick now);
  bool restart(Tick now);

  std::size_t capacity() const { return slots_.size(); }
  std::size_t in_flight() const;
  std::uint64_t generation() const { return generation_; }
  Tick now() const { return now_; }
  SchedulerState state() const { return state_; }
  const SchedulerCounts& counts() const { return counts_; }
  const std::deque<FrameEvent>& events() const { return events_; }

 private:
  struct Slot {
    enum class Phase { ProducerPending, OutputReady, ConsumerPending };
    std::optional<FrameTicket> ticket;
    std::uint64_t frame_id{};
    Tick deadline{};
    bool fallback_reported{};
    bool invalidated{};
    Phase phase{Phase::ProducerPending};
  };
  void invalidate(FrameDecision reason);
  void emit(FrameDecision, std::optional<std::uint64_t> = {},
            std::optional<FrameTicket> = {});
  std::vector<Slot> slots_;
  std::deque<FrameEvent> events_;
  SchedulerCounts counts_;
  SchedulerState state_{SchedulerState::Running};
  std::uint64_t generation_{1};
  std::uint64_t next_serial_{1};
  std::optional<std::uint64_t> latest_consumed_frame_;
  Tick now_{};
};

std::string_view to_string(FrameDecision decision);
std::string_view to_string(SchedulerState state);

}  // namespace docksr::core

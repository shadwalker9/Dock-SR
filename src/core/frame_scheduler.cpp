#include "docksr/core/frame_scheduler.hpp"

#include <algorithm>
#include <limits>
#include <stdexcept>

namespace docksr::core {

FrameScheduler::FrameScheduler(std::size_t capacity) {
  if (capacity == 0 || capacity > max_slots)
    throw std::invalid_argument("slot capacity must be between 1 and 64");
  slots_.resize(capacity);
}

std::size_t FrameScheduler::in_flight() const {
  return static_cast<std::size_t>(std::count_if(slots_.begin(), slots_.end(),
                                              [](const auto& s) { return s.ticket.has_value(); }));
}

void FrameScheduler::emit(FrameDecision decision,
                          std::optional<std::uint64_t> frame,
                          std::optional<FrameTicket> ticket) {
  switch (decision) {
    case FrameDecision::Submitted: ++counts_.submitted; break;
    case FrameDecision::OutputReady: ++counts_.outputs; break;
    case FrameDecision::OutputConsumed: ++counts_.outputs_consumed; break;
    case FrameDecision::OutputReleased: ++counts_.consumer_releases; break;
    case FrameDecision::CompletionDiscarded: ++counts_.discarded_completions; break;
    case FrameDecision::StaleCompletion: ++counts_.stale_completions; break;
    case FrameDecision::FallbackDeadline:
    case FrameDecision::FallbackExhausted:
    case FrameDecision::FallbackUnavailable:
    case FrameDecision::FallbackDuplicateFrame:
    case FrameDecision::FallbackResize:
    case FrameDecision::FallbackSuspend:
    case FrameDecision::FallbackCrash:
    case FrameDecision::FallbackStaleOutput: ++counts_.fallbacks; break;
    default: break;
  }
  if (events_.size() == event_capacity) {
    events_.pop_front();
    ++counts_.dropped_events;
  }
  events_.push_back({decision, frame, ticket, now_});
}

void FrameScheduler::advance_to(Tick now) {
  if (now < now_) throw std::invalid_argument("virtual time cannot move backwards");
  now_ = now;
  for (auto& slot : slots_) {
    // A completion at the exact deadline is late by this model's contract.
    if (slot.ticket && !slot.fallback_reported && now_ >= slot.deadline) {
      slot.fallback_reported = true;
      emit(FrameDecision::FallbackDeadline, slot.frame_id, slot.ticket);
    }
  }
}

Submission FrameScheduler::submit(std::uint64_t frame, Tick now, Tick deadline) {
  advance_to(now);
  auto reject = [&](FrameDecision decision) {
    emit(decision, frame);
    return Submission{decision, {}};
  };
  if (state_ != SchedulerState::Running)
    return reject(FrameDecision::FallbackUnavailable);
  if (deadline <= now_) return reject(FrameDecision::FallbackDeadline);
  if (std::any_of(slots_.begin(), slots_.end(), [frame](const auto& slot) {
        return slot.ticket && slot.frame_id == frame;
      }))
    return reject(FrameDecision::FallbackDuplicateFrame);
  const auto it = std::find_if(slots_.begin(), slots_.end(),
                               [](const auto& slot) { return !slot.ticket; });
  if (it == slots_.end()) return reject(FrameDecision::FallbackExhausted);
  if (next_serial_ == std::numeric_limits<std::uint64_t>::max())
    throw std::overflow_error("frame serial exhausted");
  const FrameTicket ticket{static_cast<std::size_t>(it - slots_.begin()),
                            generation_, next_serial_++};
  *it = Slot{ticket, frame, deadline, false, false};
  emit(FrameDecision::Submitted, frame, ticket);
  return {FrameDecision::Submitted, ticket};
}

FrameDecision FrameScheduler::complete(FrameTicket ticket, Tick now) {
  advance_to(now);
  if (ticket.slot >= slots_.size() || slots_[ticket.slot].ticket != ticket ||
      slots_[ticket.slot].phase != Slot::Phase::ProducerPending) {
    emit(FrameDecision::StaleCompletion, {}, ticket);
    return FrameDecision::StaleCompletion;
  }
  auto& slot = slots_[ticket.slot];
  if (!slot.invalidated && !slot.fallback_reported && latest_consumed_frame_ &&
      slot.frame_id <= *latest_consumed_frame_) {
    slot.invalidated = true;
    slot.fallback_reported = true;
    emit(FrameDecision::FallbackStaleOutput, slot.frame_id, ticket);
  }
  const auto decision = slot.invalidated || slot.fallback_reported ||
                                ticket.generation != generation_ ||
                                state_ != SchedulerState::Running
                            ? FrameDecision::CompletionDiscarded
                            : FrameDecision::OutputReady;
  emit(decision, slot.frame_id, ticket);
  if (decision == FrameDecision::OutputReady)
    slot.phase = Slot::Phase::OutputReady;
  else
    slot = Slot{};  // Producer stopped and no consumer ever acquired this output.
  return decision;
}

FrameDecision FrameScheduler::consume_output(FrameTicket ticket, Tick now) {
  advance_to(now);
  if (ticket.slot >= slots_.size() || slots_[ticket.slot].ticket != ticket) {
    emit(FrameDecision::StaleCompletion, {}, ticket);
    return FrameDecision::StaleCompletion;
  }
  auto& slot = slots_[ticket.slot];
  if (slot.phase != Slot::Phase::OutputReady || slot.invalidated ||
      slot.fallback_reported || state_ != SchedulerState::Running ||
      ticket.generation != generation_) {
    emit(FrameDecision::InvalidConsumerAcquire, slot.frame_id, ticket);
    return FrameDecision::InvalidConsumerAcquire;
  }
  if (latest_consumed_frame_ && slot.frame_id <= *latest_consumed_frame_) {
    slot.invalidated = true;
    slot.fallback_reported = true;
    emit(FrameDecision::FallbackStaleOutput, slot.frame_id, ticket);
    return FrameDecision::FallbackStaleOutput;
  }
  latest_consumed_frame_ = slot.frame_id;
  slot.phase = Slot::Phase::ConsumerPending;
  emit(FrameDecision::OutputConsumed, slot.frame_id, ticket);
  return FrameDecision::OutputConsumed;
}

FrameDecision FrameScheduler::release_output(FrameTicket ticket, Tick now) {
  advance_to(now);
  if (ticket.slot >= slots_.size() || slots_[ticket.slot].ticket != ticket) {
    emit(FrameDecision::StaleCompletion, {}, ticket);
    return FrameDecision::StaleCompletion;
  }
  auto& slot = slots_[ticket.slot];
  if (slot.phase == Slot::Phase::ProducerPending) {
    emit(FrameDecision::InvalidConsumerRelease, slot.frame_id, ticket);
    return FrameDecision::InvalidConsumerRelease;
  }
  emit(FrameDecision::OutputReleased, slot.frame_id, ticket);
  slot = Slot{};
  return FrameDecision::OutputReleased;
}

FrameDecision FrameScheduler::acknowledge_unstarted_cancel(FrameTicket ticket, Tick now) {
  advance_to(now);
  if (ticket.slot >= slots_.size() || slots_[ticket.slot].ticket != ticket) {
    emit(FrameDecision::StaleCompletion, {}, ticket);
    return FrameDecision::StaleCompletion;
  }
  auto& slot = slots_[ticket.slot];
  if (slot.phase != Slot::Phase::ProducerPending) {
    emit(FrameDecision::InvalidQueuedCancellation, slot.frame_id, ticket);
    return FrameDecision::InvalidQueuedCancellation;
  }
  emit(FrameDecision::QueuedCancelled, slot.frame_id, ticket);
  slot = Slot{};
  return FrameDecision::QueuedCancelled;
}

void FrameScheduler::invalidate(FrameDecision reason) {
  if (generation_ == std::numeric_limits<std::uint64_t>::max())
    throw std::overflow_error("scheduler generation exhausted");
  ++generation_;
  latest_consumed_frame_.reset();
  for (auto& slot : slots_) {
    if (!slot.ticket) continue;
    slot.invalidated = true;
    if (!slot.fallback_reported) {
      slot.fallback_reported = true;
      emit(reason, slot.frame_id, slot.ticket);
    }
  }
}

void FrameScheduler::resize(Tick now) {
  advance_to(now);
  invalidate(FrameDecision::FallbackResize);
  emit(FrameDecision::Resized);
}

void FrameScheduler::suspend(Tick now) {
  advance_to(now);
  if (state_ == SchedulerState::Crashed || state_ == SchedulerState::Suspended) return;
  invalidate(FrameDecision::FallbackSuspend);
  state_ = SchedulerState::Suspended;
  emit(FrameDecision::Suspended);
}

bool FrameScheduler::resume(Tick now) {
  advance_to(now);
  if (state_ != SchedulerState::Suspended) return false;
  state_ = SchedulerState::Running;
  emit(FrameDecision::Resumed);
  return true;
}

void FrameScheduler::crash(Tick now) {
  advance_to(now);
  if (state_ == SchedulerState::Crashed) return;
  invalidate(FrameDecision::FallbackCrash);
  state_ = SchedulerState::Crashed;
  emit(FrameDecision::BackendCrashed);
}

bool FrameScheduler::acknowledge_quiescence(Tick now) {
  advance_to(now);
  if (state_ == SchedulerState::Running) return false;
  for (auto& slot : slots_) slot = Slot{};
  emit(FrameDecision::QuiescenceAcknowledged);
  return true;
}

bool FrameScheduler::restart(Tick now) {
  advance_to(now);
  if (state_ != SchedulerState::Crashed || in_flight() != 0) return false;
  state_ = SchedulerState::Running;
  emit(FrameDecision::Restarted);
  return true;
}

std::string_view to_string(FrameDecision decision) {
  switch (decision) {
    case FrameDecision::Submitted: return "submitted";
    case FrameDecision::OutputReady: return "output_ready";
    case FrameDecision::FallbackDeadline: return "fallback_deadline";
    case FrameDecision::FallbackExhausted: return "fallback_exhausted";
    case FrameDecision::FallbackUnavailable: return "fallback_unavailable";
    case FrameDecision::FallbackDuplicateFrame: return "fallback_duplicate_frame";
    case FrameDecision::FallbackResize: return "fallback_resize";
    case FrameDecision::FallbackSuspend: return "fallback_suspend";
    case FrameDecision::FallbackCrash: return "fallback_crash";
    case FrameDecision::CompletionDiscarded: return "completion_discarded";
    case FrameDecision::StaleCompletion: return "stale_completion";
    case FrameDecision::Resized: return "resized";
    case FrameDecision::Suspended: return "suspended";
    case FrameDecision::Resumed: return "resumed";
    case FrameDecision::BackendCrashed: return "backend_crashed";
    case FrameDecision::QuiescenceAcknowledged: return "quiescence_acknowledged";
    case FrameDecision::Restarted: return "restarted";
    case FrameDecision::OutputConsumed: return "output_consumed";
    case FrameDecision::OutputReleased: return "output_released";
    case FrameDecision::FallbackStaleOutput: return "fallback_stale_output";
    case FrameDecision::InvalidConsumerAcquire: return "invalid_consumer_acquire";
    case FrameDecision::InvalidConsumerRelease: return "invalid_consumer_release";
    case FrameDecision::QueuedCancelled: return "queued_cancelled";
    case FrameDecision::InvalidQueuedCancellation: return "invalid_queued_cancellation";
  }
  return "unknown_enum";
}

std::string_view to_string(SchedulerState state) {
  switch (state) {
    case SchedulerState::Running: return "running";
    case SchedulerState::Suspended: return "suspended";
    case SchedulerState::Crashed: return "crashed";
  }
  return "unknown_enum";
}
}  // namespace docksr::core

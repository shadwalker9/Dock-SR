#include "docksr/core/frame_scheduler.hpp"
#include "docksr/core/schedule_simulation.hpp"

#include <array>
#include <functional>
#include <iostream>
#include <limits>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

using namespace docksr::core;
#define CHECK(value) do { if (!(value)) throw std::runtime_error("line " + std::to_string(__LINE__) + ": " #value); } while (false)

namespace {
ScheduleConfig base() {
  ScheduleConfig config;
  config.fps = 40; config.service_ms = 20; config.gpu_ms = 0;
  config.frames = 40; config.delay_frames = 0; config.slots = 1;
  config.queue_capacity = 0;
  return config;
}

template<class Function> void rejects(Function function) {
  bool rejected = false;
  try { function(); } catch (const std::invalid_argument&) { rejected = true; }
  catch (const std::overflow_error&) { rejected = true; }
  CHECK(rejected);
}
}

int main() {
  const std::vector<std::pair<std::string, std::function<void()>>> tests{
    {"40fps 20ms one slot presents every frame with release before arrival", [] {
      const auto result = simulate_schedule(base());
      CHECK(result.horizon_ticks == 18000);
      CHECK(result.completed == 40 && result.presented_unique == 40);
      CHECK(result.presentation_bypass == 0 && result.dropped == 0);
      CHECK(result.backlog == 0 && result.max_queue_depth == 0);
      CHECK(result.max_in_flight == 1 && result.completed_latency_ticks == 40 * 360);
      CHECK(!result.demand_exceeds_assumed_capacity);
    }},
    {"strict exact-deadline completion is late despite consumer lease", [] {
      auto config = base(); config.service_ms = 25;
      const auto result = simulate_schedule(config);
      CHECK(result.completed == 40 && result.presented_unique == 0);
      CHECK(result.met_deadline == 0 && result.missed_deadline == 40);
      CHECK(result.presentation_bypass == 40 && result.backlog == 0);
    }},
    {"one frame delayed presentation helps latency but retains slots", [] {
      auto config = base(); config.service_ms = 25; config.delay_frames = 1;
      config.slots = 2;
      const auto result = simulate_schedule(config);
      CHECK(result.completed == 40 && result.presented_unique == 40);
      CHECK(result.presentation_bypass == 0 && result.max_in_flight == 2);
      CHECK(result.horizon_ticks == 18450);
    }},
    {"60fps 20ms six frames hand calculated throughput and no horizon drain", [] {
      auto config = base(); config.fps = 60; config.frames = 6;
      config.slots = 3; config.queue_capacity = 2;
      const auto result = simulate_schedule(config);
      // 100ms observation: one server completes at20,40,60,80,100ms.
      CHECK(result.horizon_ticks == 1800);
      CHECK(result.submitted == 6 && result.completed == 5);
      CHECK(result.presented_unique == 0 && result.presentation_bypass == 6);
      CHECK(result.unfinished_work == 1 && result.backlog == 1);
      CHECK(result.assumed_capacity_fps == 50 && result.offered_inference_fps == 60);
      CHECK(result.demand_exceeds_assumed_capacity);
    }},
    {"one two three slots cannot create additional NPU servers", [] {
      for (std::uint64_t slots = 1; slots <= 3; ++slots) {
        auto config = base(); config.fps = 60; config.frames = 600;
        config.slots = slots; config.queue_capacity = 3; config.delay_frames = 1;
        const auto result = simulate_schedule(config);
        CHECK(result.completed <= result.horizon_ticks / 360);
        CHECK(result.max_in_flight <= slots && result.backlog <= slots);
        CHECK(result.demand_exceeds_assumed_capacity);
        CHECK(result.assumed_capacity_fps == 50);
      }
    }},
    {"serial versus hypothetical pipeline has explicit capacity assumptions", [] {
      auto config = base(); config.gpu_ms = 10; config.slots = 3;
      config.queue_capacity = 2; config.delay_frames = 1;
      config.overlap = false;
      const auto serial = simulate_schedule(config);
      config.overlap = true;
      const auto overlap = simulate_schedule(config);
      CHECK(serial.demand_exceeds_assumed_capacity);
      CHECK(serial.assumed_capacity_fps < 34);
      CHECK(!overlap.demand_exceeds_assumed_capacity && overlap.assumed_capacity_fps == 50);
      CHECK(overlap.completed > serial.completed);
    }},
    {"intentional inference cadence never relabels bypass as completion", [] {
      auto config = base(); config.infer_every = 2;
      const auto result = simulate_schedule(config);
      CHECK(result.eligible == 20 && result.deliberately_bypassed == 20);
      CHECK(result.submitted == 20 && result.completed == 20);
      CHECK(result.presented_unique == 20 && result.presentation_bypass == 20);
      CHECK(result.delivered == 40 && result.offered_inference_fps == 20);
    }},
    {"bounded queues and cancellation preserve finite-work accounting", [] {
      auto config = base(); config.fps = 60; config.gpu_ms = 25;
      config.service_ms = 25; config.slots = 3; config.queue_capacity = 2;
      config.overlap = false; config.frames = 60;
      const auto result = simulate_schedule(config);
      CHECK(result.cancelled > 0 && result.demand_exceeds_assumed_capacity);
      CHECK(result.submitted == result.completed + result.cancelled + result.unfinished_work);
      CHECK(result.submitted + result.dropped == result.eligible);
      CHECK(result.max_queue_depth <= config.queue_capacity);
    }},
    {"all requested timing grid combinations reconcile accounting", [] {
      for (const auto fps : {40ULL, 45ULL, 60ULL})
      for (std::uint64_t service = 1; service <= 25; ++service)
      for (std::uint64_t slots = 1; slots <= 3; ++slots)
      for (const bool overlap : {false, true})
      for (std::uint64_t delay = 0; delay <= 1; ++delay) {
        auto config = base(); config.fps = fps; config.service_ms = service;
        config.slots = slots; config.queue_capacity = 2; config.frames = 90;
        config.gpu_ms = 2; config.overlap = overlap; config.delay_frames = delay;
        const auto result = simulate_schedule(config);
        CHECK(result.submitted + result.dropped + result.deliberately_bypassed == config.frames);
        CHECK(result.submitted == result.completed + result.cancelled + result.unfinished_work);
        CHECK(result.met_deadline + result.missed_deadline == result.submitted);
        CHECK(result.presented_unique + result.presentation_bypass == config.frames);
        CHECK(result.presented_unique <= result.completed);
        CHECK(result.max_in_flight <= slots && result.max_queue_depth <= 2);
        CHECK(result.completed * service * 18 <= result.horizon_ticks);
        CHECK(result.ready_outputs == 0);
      }
    }},
    {"same input yields byte-identical structured result", [] {
      auto config = base(); config.fps = 45; config.slots = 3; config.queue_capacity = 2;
      CHECK(schedule_json(simulate_schedule(config)) == schedule_json(simulate_schedule(config)));
      const auto json = schedule_json(simulate_schedule(config));
      CHECK(json.find("\"evidence\":\"SIMULATED\"") != std::string::npos);
      CHECK(json.find("REAL_NPU") == std::string::npos);
    }},
    {"invalid values and overflow-sized requests fail before allocation", [] {
      const std::array<std::uint64_t ScheduleConfig::*, 8> fields{
        &ScheduleConfig::fps, &ScheduleConfig::service_ms, &ScheduleConfig::gpu_ms,
        &ScheduleConfig::slots, &ScheduleConfig::queue_capacity, &ScheduleConfig::frames,
        &ScheduleConfig::delay_frames, &ScheduleConfig::infer_every};
      for (const auto field : fields) {
        auto config = base(); config.*field = std::numeric_limits<std::uint64_t>::max();
        rejects([&] { simulate_schedule(config); });
      }
      for (const auto field : {&ScheduleConfig::fps, &ScheduleConfig::service_ms,
                              &ScheduleConfig::slots, &ScheduleConfig::frames, &ScheduleConfig::infer_every}) {
        auto config = base(); config.*field = 0;
        rejects([&] { simulate_schedule(config); });
      }
    }},
    {"trusted unstarted cancellation retires only producer pending tickets", [] {
      FrameScheduler scheduler(1);
      const auto pending = scheduler.submit(1, 0, 100).ticket.value();
      CHECK(scheduler.acknowledge_unstarted_cancel(pending, 1) == FrameDecision::QueuedCancelled);
      CHECK(scheduler.in_flight() == 0 && scheduler.counts().outputs == 0);
      CHECK(scheduler.complete(pending, 2) == FrameDecision::StaleCompletion);
      const auto current = scheduler.submit(2, 2, 100).ticket.value();
      CHECK(scheduler.complete(current, 3) == FrameDecision::OutputReady);
      CHECK(scheduler.acknowledge_unstarted_cancel(current, 3) == FrameDecision::InvalidQueuedCancellation);
      CHECK(scheduler.consume_output(current, 3) == FrameDecision::OutputConsumed);
      CHECK(scheduler.acknowledge_unstarted_cancel(current, 4) == FrameDecision::InvalidQueuedCancellation);
      CHECK(scheduler.release_output(current, 4) == FrameDecision::OutputReleased);
    }},
  };
  std::size_t passed = 0;
  for (const auto& [name, run] : tests) {
    try { run(); ++passed; std::cout << "PASS " << name << '\n'; }
    catch (const std::exception& error) { std::cerr << "FAIL " << name << ": " << error.what() << '\n'; }
  }
  std::cout << passed << '/' << tests.size() << " scheduler tests passed\n";
  return passed == tests.size() ? 0 : 1;
}

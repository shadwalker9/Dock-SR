#pragma once

#include <cstdint>
#include <string>

namespace docksr::core {

// Assumed virtual work only; these fields never configure a hardware backend.
struct ScheduleConfig {
  std::uint64_t fps{60};
  std::uint64_t service_ms{20};
  std::uint64_t gpu_ms{2};
  std::uint64_t slots{3};
  std::uint64_t queue_capacity{2};
  std::uint64_t frames{600};
  std::uint64_t delay_frames{1};
  std::uint64_t infer_every{1};
  bool overlap{true};
};

struct ScheduleResult {
  static constexpr std::uint64_t ticks_per_second = 18000;
  ScheduleConfig config;
  std::uint64_t frame_period_ticks{};
  std::uint64_t horizon_ticks{};
  std::uint64_t eligible{};
  std::uint64_t deliberately_bypassed{};
  std::uint64_t submitted{};
  std::uint64_t completed{};
  std::uint64_t cancelled{};
  std::uint64_t dropped{};
  std::uint64_t met_deadline{};
  std::uint64_t missed_deadline{};
  std::uint64_t presented_unique{};
  std::uint64_t presentation_bypass{};
  std::uint64_t delivered{};
  std::uint64_t backlog{};
  std::uint64_t unfinished_work{};
  std::uint64_t ready_outputs{};
  std::uint64_t max_queue_depth{};
  std::uint64_t queue_tick_integral{};
  std::uint64_t max_npu_queue_depth{};
  std::uint64_t npu_queue_tick_integral{};
  std::uint64_t max_in_flight{};
  std::uint64_t completed_latency_ticks{};
  double assumed_capacity_fps{};
  double offered_inference_fps{};
  bool demand_exceeds_assumed_capacity{};
};

ScheduleResult simulate_schedule(const ScheduleConfig& config);
std::string schedule_json(const ScheduleResult& result);
std::string schedule_summary(const ScheduleResult& result);
int schedule_cli(int argc, char** argv);

}  // namespace docksr::core

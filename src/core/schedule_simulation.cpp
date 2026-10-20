#include "docksr/core/schedule_simulation.hpp"
#include "docksr/core/frame_scheduler.hpp"
#include "docksr/core/json.hpp"

#include <algorithm>
#include <charconv>
#include <deque>
#include <iomanip>
#include <iostream>
#include <limits>
#include <optional>
#include <sstream>
#include <stdexcept>
#include <string_view>
#include <vector>

namespace docksr::core {
namespace {
using Index = std::size_t;
enum class Phase { NotSubmitted, AdmissionQueue, Gpu, NpuQueue, Npu, Ready, Retired };
struct Job {
  Phase phase{Phase::NotSubmitted};
  std::optional<FrameTicket> ticket;
  Tick arrival{};
  Tick presentation{};
};
struct Active { Index index; Tick end; };

std::uint64_t multiply(std::uint64_t left, std::uint64_t right) {
  if (right && left > std::numeric_limits<std::uint64_t>::max() / right)
    throw std::overflow_error("simulation time/count product overflows uint64");
  return left * right;
}

std::uint64_t parse_integer(std::string_view value) {
  std::uint64_t result{};
  const auto parsed = std::from_chars(value.data(), value.data() + value.size(), result);
  if (parsed.ec != std::errc{} || parsed.ptr != value.data() + value.size())
    throw std::invalid_argument("simulation options require unsigned decimal integers");
  return result;
}

void require(bool condition, std::string_view message) {
  if (!condition) throw std::logic_error(std::string(message));
}
}  // namespace

ScheduleResult simulate_schedule(const ScheduleConfig& config) {
  // Establish resource budgets before allocating frames or multiplying times.
  if (config.fps != 40 && config.fps != 45 && config.fps != 60)
    throw std::invalid_argument("fps must be 40, 45 or 60");
  if (config.service_ms < 1 || config.service_ms > 25 || config.gpu_ms > 25)
    throw std::invalid_argument("service-ms must be 1..25 and gpu-ms 0..25");
  if (config.slots < 1 || config.slots > 3 || config.queue_capacity > 3)
    throw std::invalid_argument("slots must be 1..3 and queue-capacity 0..3");
  if (config.frames < 1 || config.frames > 100000 || config.delay_frames > 1 ||
      config.infer_every < 1 || config.infer_every > 60)
    throw std::invalid_argument("frames must be 1..100000, delay-frames 0..1 and infer-every 1..60");

  ScheduleResult result;
  result.config = config;
  const Tick period = ScheduleResult::ticks_per_second / config.fps;
  const Tick service = multiply(config.service_ms, 18);
  const Tick gpu = multiply(config.gpu_ms, 18);
  result.frame_period_ticks = period;
  result.horizon_ticks = multiply(config.frames + config.delay_frames, period);
  result.assumed_capacity_fps = 1000.0 / static_cast<double>(
      config.overlap ? std::max(config.service_ms, config.gpu_ms) : config.service_ms + config.gpu_ms);
  result.offered_inference_fps = static_cast<double>(config.fps) / static_cast<double>(config.infer_every);
  result.demand_exceeds_assumed_capacity = result.offered_inference_fps > result.assumed_capacity_fps;

  FrameScheduler scheduler(static_cast<std::size_t>(config.slots));
  std::vector<Job> jobs(static_cast<std::size_t>(config.frames));
  std::deque<Index> admission_queue, npu_queue;
  std::optional<Active> gpu_active, npu_active;
  Index next_arrival = 0, next_presentation = 0;
  Tick now = 0;

  auto complete_npu = [&](Index index) {
    auto& job = jobs[index];
    ++result.completed;
    result.completed_latency_ticks += now - job.arrival;
    const auto decision = scheduler.complete(*job.ticket, now);
    if (now < job.presentation && decision == FrameDecision::OutputReady) {
      require(scheduler.consume_output(*job.ticket, now) == FrameDecision::OutputConsumed,
              "timely output could not acquire consumer ownership");
      job.phase = Phase::Ready;
    } else {
      if (decision == FrameDecision::OutputReady)
        require(scheduler.release_output(*job.ticket, now) == FrameDecision::OutputReleased,
                "late ready output could not be released");
      else require(decision == FrameDecision::CompletionDiscarded,
                   "producer completion unexpectedly lost its owned ticket");
      job.phase = Phase::Retired;
    }
  };

  auto dispatch = [&] {
    if (!config.overlap) {
      if (!npu_active && !admission_queue.empty()) {
        const auto index = admission_queue.front(); admission_queue.pop_front();
        jobs[index].phase = Phase::Npu;
        npu_active = Active{index, now + gpu + service};
      }
    } else {
      if (!gpu_active && !admission_queue.empty()) {
        const auto index = admission_queue.front(); admission_queue.pop_front();
        jobs[index].phase = Phase::Gpu;
        gpu_active = Active{index, now + gpu};
      }
      if (!npu_active && !npu_queue.empty()) {
        const auto index = npu_queue.front(); npu_queue.pop_front();
        jobs[index].phase = Phase::Npu;
        npu_active = Active{index, now + service};
      }
    }
  };

  while (next_arrival < jobs.size() || next_presentation < jobs.size() ||
         gpu_active || npu_active || !admission_queue.empty() || !npu_queue.empty()) {
    Tick event = result.horizon_ticks;
    if (next_arrival < jobs.size()) event = std::min(event, multiply(next_arrival, period));
    if (next_presentation < jobs.size())
      event = std::min(event, multiply(next_presentation + 1 + config.delay_frames, period));
    if (gpu_active) event = std::min(event, gpu_active->end);
    if (npu_active) event = std::min(event, npu_active->end);
    require(event >= now, "simulation event moved backwards");
    result.queue_tick_integral += multiply(admission_queue.size(), event - now);
    result.npu_queue_tick_integral += multiply(npu_queue.size(), event - now);
    now = event;

    // Producer completions first. Equality still misses the exclusive inference
    // deadline; the extra lease tick exists only for presentation ownership.
    if (npu_active && npu_active->end == now) {
      const auto index = npu_active->index; npu_active.reset();
      complete_npu(index);
    }
    if (gpu_active && gpu_active->end == now) {
      const auto index = gpu_active->index; gpu_active.reset();
      jobs[index].phase = Phase::NpuQueue;
      npu_queue.push_back(index);
    }

    // Release presentation ownership before same-tick arrivals. A queued ticket
    // can be cancelled only if neither GPU nor NPU stage ever started it.
    if (next_presentation < jobs.size() &&
        multiply(next_presentation + 1 + config.delay_frames, period) == now) {
      auto& job = jobs[next_presentation];
      ++result.delivered;
      if (job.phase == Phase::Ready) {
        require(scheduler.release_output(*job.ticket, now) == FrameDecision::OutputReleased,
                "presentation could not release owned ready output");
        job.phase = Phase::Retired;
        ++result.met_deadline;
        ++result.presented_unique;
      } else {
        ++result.presentation_bypass;
        if (job.ticket) ++result.missed_deadline;
        if (job.phase == Phase::AdmissionQueue) {
          admission_queue.erase(std::find(admission_queue.begin(), admission_queue.end(), next_presentation));
          require(scheduler.acknowledge_unstarted_cancel(*job.ticket, now) == FrameDecision::QueuedCancelled,
                  "undispatched queue cancellation failed");
          job.phase = Phase::Retired;
          ++result.cancelled;
        }
        // Interstage or actively executing work has begun; no fake cancellation.
      }
      ++next_presentation;
    }

    dispatch();
    if (next_arrival < jobs.size() && multiply(next_arrival, period) == now) {
      auto& job = jobs[next_arrival];
      job.arrival = now;
      job.presentation = multiply(next_arrival + 1 + config.delay_frames, period);
      if (next_arrival % config.infer_every != 0) ++result.deliberately_bypassed;
      else {
        ++result.eligible;
        const bool immediately_available = config.overlap ? !gpu_active : !npu_active;
        if ((!immediately_available && admission_queue.size() >= config.queue_capacity) ||
            scheduler.in_flight() == config.slots) ++result.dropped;
        else {
          const auto submission = scheduler.submit(next_arrival, now, job.presentation + 1);
          require(submission.ticket.has_value(), "admissible frame unexpectedly exhausted ownership slots");
          job.ticket = submission.ticket;
          job.phase = Phase::AdmissionQueue;
          admission_queue.push_back(next_arrival);
          ++result.submitted;
          dispatch();
        }
      }
      ++next_arrival;
    }
    result.max_queue_depth = std::max<std::uint64_t>(result.max_queue_depth, admission_queue.size());
    result.max_npu_queue_depth = std::max<std::uint64_t>(result.max_npu_queue_depth, npu_queue.size());
    result.max_in_flight = std::max<std::uint64_t>(result.max_in_flight, scheduler.in_flight());
    if (now == result.horizon_ticks) break;  // Never drain beyond observation horizon.
  }

  result.backlog = scheduler.in_flight();
  for (const auto& job : jobs) {
    if (job.phase == Phase::Ready) ++result.ready_outputs;
    else if (job.ticket && job.phase != Phase::Retired) ++result.unfinished_work;
  }
  require(result.submitted == result.completed + result.cancelled + result.unfinished_work,
          "submitted work accounting does not reconcile");
  require(result.delivered == result.presented_unique + result.presentation_bypass &&
          result.delivered == config.frames, "presentation accounting does not reconcile");
  require(result.submitted == result.met_deadline + result.missed_deadline,
          "deadline accounting does not reconcile");
  return result;
}

std::string schedule_json(const ScheduleResult& r) {
  const auto& c = r.config;
  const double seconds = static_cast<double>(r.horizon_ticks) / ScheduleResult::ticks_per_second;
  std::ostringstream out;
  out << std::setprecision(17) << std::boolalpha
      << "{\"schema_version\":\"1.0.0\",\"document_type\":\"docksr_schedule_simulation\","
         "\"evidence\":\"SIMULATED\",\"hardware_validated\":false,\"seed\":null,"
         "\"config\":{\"fps\":" << c.fps << ",\"service_ms\":" << c.service_ms
      << ",\"gpu_ms\":" << c.gpu_ms << ",\"slots\":" << c.slots
      << ",\"queue_capacity\":" << c.queue_capacity << ",\"frames\":" << c.frames
      << ",\"delay_frames\":" << c.delay_frames << ",\"infer_every\":" << c.infer_every
      << ",\"execution\":" << json_string(c.overlap ? "overlap" : "serial") << "},"
      << "\"clock\":{\"kind\":\"virtual\",\"ticks_per_second\":" << ScheduleResult::ticks_per_second
      << ",\"frame_period_ticks\":" << r.frame_period_ticks
      << ",\"frame_period_ms\":" << static_cast<double>(r.frame_period_ticks) / 18
      << ",\"observation_horizon_ticks\":" << r.horizon_ticks << "},"
      << "\"service_model\":{\"kind\":\"constant_assumed\",\"npu_servers\":1,"
         "\"assumed_capacity_fps\":" << r.assumed_capacity_fps
      << ",\"offered_inference_fps\":" << r.offered_inference_fps
      << ",\"demand_exceeds_assumed_capacity\":" << r.demand_exceeds_assumed_capacity << "},"
      << "\"counts\":{\"arrivals\":" << c.frames << ",\"eligible\":" << r.eligible
      << ",\"deliberately_bypassed\":" << r.deliberately_bypassed << ",\"submitted\":" << r.submitted
      << ",\"completed\":" << r.completed << ",\"processed_unique_frames\":" << r.completed
      << ",\"cancelled_before_processing\":" << r.cancelled << ",\"dropped\":" << r.dropped
      << ",\"results_met_deadline\":" << r.met_deadline << ",\"results_missed_deadline\":" << r.missed_deadline
      << ",\"presented_unique_results\":" << r.presented_unique
      << ",\"presentation_bypass_fallback\":" << r.presentation_bypass
      << ",\"delivered_frames\":" << r.delivered << ",\"end_of_run_backlog\":" << r.backlog
      << ",\"unfinished_work\":" << r.unfinished_work << ",\"ready_outputs_at_end\":" << r.ready_outputs << "},"
      << "\"queues\":{\"admission_capacity\":" << c.queue_capacity
      << ",\"maximum_queue_depth\":" << r.max_queue_depth
      << ",\"average_queue_depth\":" << static_cast<double>(r.queue_tick_integral) / static_cast<double>(r.horizon_ticks)
      << ",\"maximum_interstage_npu_queue_depth\":" << r.max_npu_queue_depth
      << ",\"average_interstage_npu_queue_depth\":" << static_cast<double>(r.npu_queue_tick_integral) / static_cast<double>(r.horizon_ticks)
      << ",\"maximum_in_flight\":" << r.max_in_flight << "},"
      << "\"observations\":{\"completed_unique_per_second\":" << static_cast<double>(r.completed) / seconds
      << ",\"presented_unique_per_second\":" << static_cast<double>(r.presented_unique) / seconds
      << ",\"delivered_frames_per_second\":" << static_cast<double>(r.delivered) / seconds
      << ",\"average_completed_latency_ms\":";
  if (r.completed) out << static_cast<double>(r.completed_latency_ticks) / (18.0 * static_cast<double>(r.completed));
  else out << "null";
  out << "},\"timing_assumptions\":["
         "\"No randomness or wall-clock sleeping; ticks are assumed time, not AMD measurements.\","
         "\"Serial shares one GPU-plus-NPU work resource; overlap pipelines one GPU stage and one serial NPU server.\","
         "\"GPU stage is assumed preprocessing; base fallback is always available and presentation/release cost zero.\","
         "\"Queue capacity bounds admission waiting only; interstage NPU waiting is separately reported and slot-bounded.\","
         "\"Slots include queued, active and retained-ready work; slots do not add NPU servers.\","
         "\"Presentation is next frame boundary plus delay_frames; completion equality is late.\","
         "\"Consumer acquisition occurs on timely completion; ownership is retained until presentation using one extra lease tick.\","
         "\"Completions, presentations/releases, queued dispatch and arrivals occur in that order at equal time.\","
         "\"Only never-started admission work can cancel; started stages retain ownership until producer completion.\","
         "\"Observation ends at final presentation; post-horizon work is backlog, never drained into throughput.\","
         "\"Bounded queue depth does not establish sustainable service; capacity/overload is reported independently.\"]}";
  return out.str();
}

std::string schedule_summary(const ScheduleResult& r) {
  // Keep this human report's accounting fields aligned with the JSON contract.
  std::ostringstream out;
  out << std::fixed << std::setprecision(3) << "SIMULATED only: " << r.config.fps
      << " FPS arrivals, " << r.config.service_ms << " ms NPU, " << r.config.gpu_ms
      << " ms GPU, " << r.config.slots << " slots; " << (r.config.overlap ? "overlap" : "serial")
      << ". Assumed capacity " << r.assumed_capacity_fps << " unique/s; offered " << r.offered_inference_fps
      << " unique/s; capacity overload " << (r.demand_exceeds_assumed_capacity ? "YES" : "NO")
      << ". Submitted " << r.submitted << ", completed " << r.completed
      << ", cancelled " << r.cancelled << ", dropped " << r.dropped
      << "; admission queue capacity " << r.config.queue_capacity << ", max " << r.max_queue_depth
      << ", time-average " << static_cast<double>(r.queue_tick_integral) / static_cast<double>(r.horizon_ticks)
      << "; presented unique " << r.presented_unique
      << ", fallback " << r.presentation_bypass << ", delivered " << r.delivered
      << ", end backlog " << r.backlog << ". No hardware inference or game FPS measured.";
  return out.str();
}

int schedule_cli(int argc, char** argv) {
  try {
    ScheduleConfig config;
    for (int i = 0; i < argc; ++i) {
      const std::string_view option(argv[i]);
      if (option == "--help") {
        std::cout << "Usage: docksr-mock --schedule [--fps 40|45|60] [--service-ms 1..25] [--gpu-ms 0..25]\n"
                     "  [--slots 1..3] [--queue-capacity 0..3] [--frames 1..100000]\n"
                     "  [--delay-frames 0|1] [--infer-every 1..60] [--execution serial|overlap]\n"
                     "Deterministic SIMULATED JSON on stdout; concise summary on stderr. No hardware dispatch.\n";
        return 0;
      }
      if (i + 1 >= argc) throw std::invalid_argument("schedule option requires a value");
      const std::string_view value(argv[++i]);
      if (option == "--execution") {
        if (value != "serial" && value != "overlap") throw std::invalid_argument("execution must be serial or overlap");
        config.overlap = value == "overlap";
      } else {
        const auto number = parse_integer(value);
        if (option == "--fps") config.fps = number;
        else if (option == "--service-ms") config.service_ms = number;
        else if (option == "--gpu-ms") config.gpu_ms = number;
        else if (option == "--slots") config.slots = number;
        else if (option == "--queue-capacity") config.queue_capacity = number;
        else if (option == "--frames") config.frames = number;
        else if (option == "--delay-frames") config.delay_frames = number;
        else if (option == "--infer-every") config.infer_every = number;
        else throw std::invalid_argument("unknown schedule option");
      }
    }
    const auto result = simulate_schedule(config);
    std::cout << schedule_json(result) << '\n';
    std::cerr << schedule_summary(result) << '\n';
    return 0;
  } catch (const std::exception& error) {
    std::cout << "{\"schema_version\":\"1.0.0\",\"document_type\":\"docksr_schedule_simulation\","
                 "\"evidence\":\"SIMULATED\",\"hardware_validated\":false,\"status\":\"ERROR\",\"error\":"
              << json_string(error.what()) << "}\n";
    return 2;
  }
}
}  // namespace docksr::core

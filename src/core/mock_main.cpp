#include "docksr/core/frame_scheduler.hpp"
#include "docksr/core/json.hpp"
#include "docksr/core/profile_registry.hpp"

#include <algorithm>
#include <array>
#include <iostream>
#include <stdexcept>
#include <string>

namespace {
using namespace docksr::core;

void require(bool condition, std::string_view reason) {
  if (!condition) throw std::runtime_error(std::string(reason));
}

FrameTicket submit(FrameScheduler& scheduler, std::uint64_t frame, Tick now, Tick deadline) {
  const auto result = scheduler.submit(frame, now, deadline);
  require(result.ticket.has_value(), "scenario submission unexpectedly fell back");
  return *result.ticket;
}

void consume_and_release(FrameScheduler& scheduler, FrameTicket ticket, Tick now) {
  require(scheduler.consume_output(ticket, now) == FrameDecision::OutputConsumed,
          "output consumer acquisition failed");
  require(scheduler.release_output(ticket, now) == FrameDecision::OutputReleased,
          "output consumer release failed");
}

void run_scenario(FrameScheduler& scheduler, std::string_view name) {
  const auto first = submit(scheduler, 1, 0,
                            name == "late" || name == "late-consumer" ? 5 : 10);
  if (name == "normal") {
    require(scheduler.complete(first, 4) == FrameDecision::OutputReady, "normal output missing");
    consume_and_release(scheduler, first, 4);
    const auto next = submit(scheduler, 2, 4, 14);
    require(scheduler.complete(next, 8) == FrameDecision::OutputReady, "reused slot failed");
    consume_and_release(scheduler, next, 8);
  } else if (name == "late") {
    scheduler.advance_to(5);
    require(scheduler.in_flight() == 1, "deadline released an in-flight slot");
    const auto next = submit(scheduler, 2, 5, 12);
    require(scheduler.submit(3, 5, 20).decision == FrameDecision::FallbackExhausted,
            "late slot was reused");
    require(scheduler.complete(first, 6) == FrameDecision::CompletionDiscarded,
            "late result was presented");
    require(scheduler.complete(next, 8) == FrameDecision::OutputReady, "timely result discarded");
    consume_and_release(scheduler, next, 8);
  } else if (name == "late-consumer") {
    require(scheduler.complete(first, 2) == FrameDecision::OutputReady, "producer output missing");
    require(scheduler.consume_output(first, 2) == FrameDecision::OutputConsumed,
            "consumer acquisition failed");
    const auto next = submit(scheduler, 2, 2, 12);
    scheduler.advance_to(5);
    require(scheduler.in_flight() == 2, "late consumer ownership was released");
    require(scheduler.submit(3, 5, 20).decision == FrameDecision::FallbackExhausted,
            "late consumer slot was reused");
    require(scheduler.release_output(first, 6) == FrameDecision::OutputReleased,
            "late consumer release failed");
    require(scheduler.complete(next, 7) == FrameDecision::OutputReady, "next output missing");
    consume_and_release(scheduler, next, 7);
  } else if (name == "crash") {
    scheduler.crash(2);
    require(!scheduler.restart(3), "restart reused outstanding crash memory");
    require(scheduler.submit(2, 3, 10).decision == FrameDecision::FallbackUnavailable,
            "crashed backend accepted a frame");
    require(scheduler.acknowledge_quiescence(4), "simulated quiescence failed");
    require(scheduler.restart(4), "quiescent restart failed");
    const auto next = submit(scheduler, 3, 4, 14);
    require(scheduler.complete(first, 5) == FrameDecision::StaleCompletion,
            "crashed old ticket matched restarted work");
    require(scheduler.complete(next, 6) == FrameDecision::OutputReady, "restart output failed");
    consume_and_release(scheduler, next, 6);
  } else if (name == "resize") {
    scheduler.resize(1);
    const auto next = submit(scheduler, 2, 1, 11);
    require(scheduler.complete(first, 2) == FrameDecision::CompletionDiscarded,
            "pre-resize result was presented");
    require(scheduler.complete(next, 3) == FrameDecision::OutputReady, "resized output failed");
    consume_and_release(scheduler, next, 3);
    const auto reused = submit(scheduler, 3, 3, 12);
    require(scheduler.complete(first, 4) == FrameDecision::StaleCompletion,
            "old generation released a reused slot");
    require(scheduler.complete(reused, 5) == FrameDecision::OutputReady, "reused output failed");
    consume_and_release(scheduler, reused, 5);
  } else if (name == "suspend") {
    scheduler.suspend(1);
    require(scheduler.submit(2, 1, 10).decision == FrameDecision::FallbackUnavailable,
            "suspended backend accepted a frame");
    require(scheduler.resume(2), "resume failed");
    const auto next = submit(scheduler, 3, 2, 12);
    require(scheduler.complete(first, 3) == FrameDecision::CompletionDiscarded,
            "pre-suspend output was presented");
    require(scheduler.complete(next, 4) == FrameDecision::OutputReady, "resumed output failed");
    consume_and_release(scheduler, next, 4);
  } else if (name == "exhaustion") {
    const auto next = submit(scheduler, 2, 0, 10);
    require(scheduler.submit(3, 0, 10).decision == FrameDecision::FallbackExhausted,
            "pool grew past its bound");
    require(scheduler.complete(next, 2) == FrameDecision::OutputReady, "out-of-order output failed");
    require(scheduler.complete(first, 3) == FrameDecision::OutputReady, "first output failed");
    consume_and_release(scheduler, first, 3);
    consume_and_release(scheduler, next, 3);
  } else if (name == "stale") {
    require(scheduler.complete(first, 1) == FrameDecision::OutputReady, "first output failed");
    consume_and_release(scheduler, first, 1);
    const auto next = submit(scheduler, 2, 1, 10);
    require(scheduler.complete(first, 2) == FrameDecision::StaleCompletion,
            "duplicate completion released current work");
    auto forged = next;
    ++forged.generation;
    require(scheduler.complete(forged, 2) == FrameDecision::StaleCompletion,
            "wrong generation matched current work");
    require(scheduler.complete(next, 3) == FrameDecision::OutputReady, "current output failed");
    consume_and_release(scheduler, next, 3);
  }
}

void write_identity(const ValidationIdentity& identity) {
  std::cout << "{\"device_id\":" << json_string(identity.device_id)
            << ",\"driver_version\":" << json_string(identity.driver_version)
            << ",\"runtime_version\":" << json_string(identity.runtime_version)
            << ",\"model_id\":" << json_string(identity.model_id)
            << ",\"model_sha256\":" << json_string(identity.model_sha256)
            << ",\"model_identity_kind\":\"simulation_placeholder\""
            << ",\"mode\":" << json_string(identity.mode)
            << ",\"quality\":" << json_string(identity.quality)
            << ",\"scope\":" << json_string(to_string(identity.scope)) << '}';
}

void list_profiles() {
  std::cout << "{\"schema_version\":\"1.0.0\",\"evidence_class\":\"mock_state_machine\","
               "\"simulated\":true,\"hardware_validated\":false,\"profiles\":[";
  bool comma = false;
  for (const auto& profile : ProfileRegistry::profiles()) {
    if (comma) std::cout << ',';
    comma = true;
    std::cout << "{\"id\":" << json_string(profile.id)
              << ",\"revision\":" << profile.revision
              << ",\"input\":{\"width\":" << profile.input.width
              << ",\"height\":" << profile.input.height
              << "},\"output\":{\"width\":" << profile.output.width
              << ",\"height\":" << profile.output.height
              << "},\"mode\":" << json_string(profile.mode)
              << ",\"hardware_validation_status\":\"unvalidated\"}";
  }
  std::cout << "]}\n";
}

int error(std::string_view message, int code = 2) {
  std::cout << "{\"schema_version\":\"1.0.0\",\"evidence_class\":\"mock_state_machine\","
               "\"simulated\":true,\"hardware_validated\":false,\"error\":"
            << json_string(message) << "}\n";
  return code;
}
}  // namespace

int main(int argc, char** argv) {
  try {
    std::string profile_id(ProfileRegistry::default_profile);
    std::string scenario = "normal";
    bool enable = false;
    bool listing = false;
    for (int i = 1; i < argc; ++i) {
      const std::string_view arg(argv[i]);
      if (arg == "--enable") enable = true;
      else if (arg == "--list-profiles") listing = true;
      else if (arg == "--profile" || arg == "--scenario") {
        if (i + 1 >= argc) return error(std::string(arg) + " requires a value");
        (arg == "--profile" ? profile_id : scenario) = argv[++i];
      } else if (arg == "--help") {
        std::cout << "Dock SR deterministic host simulation; no NPU or physical timing.\n"
                     "Usage: docksr-mock [--enable] [--profile ID] [--scenario NAME]\n"
                     "Scenarios: normal late late-consumer crash resize suspend exhaustion stale\n"
                     "Without --enable: disabled/unvalidated state; no scenario executes.\n"
                     "--enable validates a simulation tuple only. --list-profiles lists IDs.\n";
        return 0;
      } else return error("unknown option: " + std::string(arg));
    }
    constexpr std::array<std::string_view, 8> scenarios{
        "normal", "late", "late-consumer", "crash", "resize", "suspend", "exhaustion", "stale"};
    if (std::find(scenarios.begin(), scenarios.end(), scenario) == scenarios.end())
      return error("scenario_not_allowlisted: " + scenario);
    ProfileRegistry registry;
    const auto requested = registry.request_profile(profile_id);
    if (!requested) return error(requested.reason);
    if (listing) {
      list_profiles();
      return 0;
    }
    const auto* profile = ProfileRegistry::find(profile_id);
    ValidationIdentity identity{"simulated-device", "mock-driver-v1", "mock-runtime-v1",
        "mock_scheduler_v1", std::string(64, '0'), std::string(profile->mode), "balanced",
        ValidationScope::Simulation};
    if (enable) {
      const auto validation = registry.record_validation(
          {profile_id, profile->revision, identity, ValidationStatus::Validated});
      if (!validation) return error(validation.reason);
      const auto activation = registry.activate(identity);
      if (!activation) return error(activation.reason);
    }
    FrameScheduler scheduler(2);
    if (registry.enabled()) run_scenario(scheduler, scenario);
    std::cout << std::boolalpha
              << "{\"schema_version\":\"1.0.0\",\"evidence_class\":\"mock_state_machine\","
                 "\"simulated\":true,\"hardware_validated\":false,\"scenario\":"
              << json_string(scenario) << ",\"scenario_executed\":" << registry.enabled()
              << ",\"clock\":\"virtual_ticks\",\"unit\":\"simulated_tick\",\"profile_state\":{\"enabled\":"
              << registry.enabled() << ",\"requested_profile\":" << json_string(registry.requested_profile())
              << ",\"active_profile\":"
              << (registry.active() ? json_string(registry.active()->profile_id) : "null")
              << ",\"profile_revision\":" << profile->revision
              << ",\"validation_status\":" << json_string(to_string(registry.validation_status(identity)))
              << ",\"validation_scope\":\"simulation\",\"hardware_validation_status\":\"unvalidated\",\"identity\":";
    write_identity(identity);
    std::cout << "},\"scheduler\":{\"capacity\":" << scheduler.capacity()
              << ",\"in_flight\":" << scheduler.in_flight()
              << ",\"generation\":" << scheduler.generation()
              << ",\"state\":" << json_string(to_string(scheduler.state()))
              << ",\"events\":[";
    bool comma = false;
    for (const auto& event : scheduler.events()) {
      if (comma) std::cout << ',';
      comma = true;
      std::cout << "{\"decision\":" << json_string(to_string(event.decision))
                << ",\"frame_id\":";
      if (event.frame_id) std::cout << *event.frame_id;
      else std::cout << "null";
      std::cout << ",\"slot\":";
      if (event.ticket) std::cout << event.ticket->slot;
      else std::cout << "null";
      std::cout << ",\"generation\":";
      if (event.ticket) std::cout << event.ticket->generation;
      else std::cout << "null";
      std::cout << ",\"serial\":";
      if (event.ticket) std::cout << event.ticket->serial;
      else std::cout << "null";
      std::cout << ",\"at_tick\":" << event.at_tick << '}';
    }
    const auto& counts = scheduler.counts();
    std::cout << "],\"counts\":{\"submitted\":" << counts.submitted
              << ",\"outputs\":" << counts.outputs << ",\"fallbacks\":" << counts.fallbacks
              << ",\"outputs_consumed\":" << counts.outputs_consumed
              << ",\"consumer_releases\":" << counts.consumer_releases
              << ",\"discarded_completions\":" << counts.discarded_completions
              << ",\"stale_completions\":" << counts.stale_completions
              << ",\"dropped_events\":" << counts.dropped_events << "}}}\n";
    return 0;
  } catch (const std::exception& exception) {
    return error(exception.what(), 1);
  }
}

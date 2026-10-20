#include "docksr/core/frame_scheduler.hpp"
#include "docksr/core/json.hpp"
#include "docksr/core/profile_registry.hpp"

#include <algorithm>
#include <functional>
#include <iostream>
#include <limits>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

namespace {
using namespace docksr::core;
#define CHECK(expression) do { if (!(expression)) throw std::runtime_error( \
  std::string(__FILE__) + ":" + std::to_string(__LINE__) + ": " #expression); } while (false)

ValidationIdentity identity() {
  return {"simulated-device", "driver-v1", "runtime-v1", "model_v1",
          std::string(64, 'a'), "docked", "balanced", ValidationScope::Simulation};
}

ValidationRecord validated(ValidationIdentity id = identity(),
                           std::string profile = "probe_720_1080") {
  return {std::move(profile), 1, std::move(id), ValidationStatus::Validated};
}

FrameTicket ticket(Submission submission) {
  CHECK(submission.decision == FrameDecision::Submitted);
  CHECK(submission.ticket.has_value());
  return *submission.ticket;
}

void consume_and_release(FrameScheduler& scheduler, FrameTicket value, Tick now) {
  CHECK(scheduler.consume_output(value, now) == FrameDecision::OutputConsumed);
  CHECK(scheduler.release_output(value, now) == FrameDecision::OutputReleased);
}

template <typename F>
void invalid_argument(F&& fn) {
  bool thrown = false;
  try { fn(); } catch (const std::invalid_argument&) { thrown = true; }
  CHECK(thrown);
}

using Test = std::pair<std::string, std::function<void()>>;
}  // namespace

int main() {
  const std::vector<Test> tests{
    {"registry defaults remain disabled and unvalidated", [] {
      ProfileRegistry registry;
      CHECK(!registry.enabled());
      CHECK(!registry.active());
      CHECK(registry.requested_profile() == "probe_720_1080");
      CHECK(registry.validations().empty());
      CHECK(registry.validation_status(identity()) == ValidationStatus::Unvalidated);
      CHECK(!registry.activate(identity()));
      CHECK(!registry.active());
    }},
    {"versioned allowlist contains six documented dimensions", [] {
      CHECK(ProfileRegistry::profiles().size() == 6);
      CHECK(ProfileRegistry::find("television_900_2160")->input == (Extent{1600, 900}));
      CHECK(ProfileRegistry::find("television_720_2160")->output == (Extent{3840, 2160}));
      for (const auto& profile : ProfileRegistry::profiles()) CHECK(profile.revision == 1);
      CHECK(ProfileRegistry::find("720p_to_1080p_balanced") == nullptr);
    }},
    {"validated simulation activates and disable preserves validation", [] {
      ProfileRegistry registry;
      CHECK(registry.record_validation(validated()));
      CHECK(!registry.enabled());
      CHECK(registry.activate(identity()));
      CHECK(registry.enabled());
      CHECK(registry.active()->identity == identity());
      registry.disable();
      CHECK(!registry.active());
      CHECK(registry.validation_status(identity()) == ValidationStatus::Validated);
    }},
    {"unknown requests and arbitrary paths cannot enter allowlist", [] {
      ProfileRegistry registry;
      CHECK(!registry.request_profile("../../model.onnx"));
      CHECK(!registry.request_profile("probe_720_1080; touch /tmp/unsafe"));
      CHECK(registry.requested_profile() == "probe_720_1080");
      auto record = validated();
      record.profile_id = "/tmp/model.onnx";
      CHECK(!registry.record_validation(record));
      CHECK(registry.validations().empty());
    }},
    {"each exact identity field participates in activation", [] {
      const std::vector<std::function<void(ValidationIdentity&)>> changes{
        [](auto& id) { id.device_id = "other-device"; },
        [](auto& id) { id.driver_version = "driver-v2"; },
        [](auto& id) { id.runtime_version = "runtime-v2"; },
        [](auto& id) { id.model_id = "other_model"; },
        [](auto& id) { id.model_sha256[0] = 'b'; },
        [](auto& id) { id.mode = "portable"; },
        [](auto& id) { id.quality = "quality"; },
        [](auto& id) { id.scope = ValidationScope::Hardware; },
      };
      for (const auto& change : changes) {
        ProfileRegistry registry;
        CHECK(registry.record_validation(validated()));
        CHECK(registry.activate(identity()));
        auto changed = identity();
        change(changed);
        CHECK(!registry.activate(changed));
        CHECK(!registry.enabled());
        CHECK(!registry.active());
      }
    }},
    {"revision mismatch and unsupported mode reject validation", [] {
      ProfileRegistry registry;
      auto record = validated();
      record.profile_revision = 2;
      CHECK(!registry.record_validation(record));
      record = validated();
      record.identity.mode = "portable";
      CHECK(!registry.record_validation(record));
      record = validated();
      record.identity.quality = "unbounded_custom";
      CHECK(!registry.record_validation(record));
      CHECK(registry.validations().empty());
    }},
    {"validation refuses model paths commands and malformed hashes", [] {
      ProfileRegistry registry;
      auto record = validated();
      record.identity.model_id = "../weights/model.onnx";
      CHECK(!registry.record_validation(record));
      record = validated();
      record.identity.runtime_version = "xrt; echo unsafe";
      CHECK(!registry.record_validation(record));
      record = validated();
      record.identity.model_sha256 = "abcd";
      CHECK(!registry.record_validation(record));
      record = validated();
      record.identity.model_sha256[0] = 'g';
      CHECK(!registry.record_validation(record));
      record = validated();
      record.identity.device_id.clear();
      CHECK(!registry.record_validation(record));
    }},
    {"hardware validation is unavailable in this increment", [] {
      ProfileRegistry registry;
      auto record = validated();
      record.identity.scope = ValidationScope::Hardware;
      CHECK(registry.record_validation(record).reason == "hardware_backend_unavailable");
      CHECK(registry.validations().empty());
    }},
    {"only validated status activates and revocation disables immediately", [] {
      for (const auto status : {ValidationStatus::Unknown, ValidationStatus::Unvalidated,
          ValidationStatus::Compiling, ValidationStatus::Incompatible,
          ValidationStatus::Revoked, ValidationStatus::Fallback}) {
        ProfileRegistry registry;
        auto record = validated();
        record.status = status;
        CHECK(registry.record_validation(record));
        CHECK(!registry.activate(identity()));
      }
      ProfileRegistry registry;
      CHECK(registry.record_validation(validated()));
      CHECK(registry.activate(identity()));
      auto revoked = validated();
      revoked.status = ValidationStatus::Revoked;
      CHECK(registry.record_validation(revoked));
      CHECK(!registry.enabled());
      CHECK(!registry.active());
      CHECK(!registry.activate(identity()));
    }},
    {"changing requested profile requires its own validation", [] {
      ProfileRegistry registry;
      CHECK(registry.record_validation(validated()));
      CHECK(registry.activate(identity()));
      CHECK(registry.request_profile("television_720_2160"));
      CHECK(!registry.active());
      CHECK(!registry.activate(identity()));
      CHECK(registry.record_validation(validated(identity(), "television_720_2160")));
      CHECK(registry.activate(identity()));
      CHECK(registry.active()->profile_id == "television_720_2160");
    }},
    {"portable profile binds the portable mode", [] {
      ProfileRegistry registry;
      CHECK(registry.request_profile("portable_720_1080"));
      auto id = identity();
      CHECK(!registry.record_validation(validated(id, "portable_720_1080")));
      id.mode = "portable";
      CHECK(registry.record_validation(validated(id, "portable_720_1080")));
      CHECK(registry.activate(id));
    }},
    {"validation storage is bounded and existing tuples can update", [] {
      ProfileRegistry registry;
      for (int i = 0; i < 64; ++i) {
        auto id = identity();
        id.device_id = "device-" + std::to_string(i);
        CHECK(registry.record_validation(validated(id)));
      }
      CHECK(!registry.record_validation(validated()));
      auto id = identity();
      id.device_id = "device-0";
      auto record = validated(id);
      record.status = ValidationStatus::Revoked;
      CHECK(registry.record_validation(record));
      CHECK(registry.validations().size() == 64);
    }},
    {"slot pool rejects zero and excessive capacity", [] {
      invalid_argument([] { FrameScheduler scheduler(0); });
      invalid_argument([] { FrameScheduler scheduler(65); });
      FrameScheduler scheduler(64);
      CHECK(scheduler.capacity() == 64);
    }},
    {"timely completion releases persistent slot", [] {
      FrameScheduler scheduler(1);
      const auto first = ticket(scheduler.submit(1, 0, 10));
      CHECK(scheduler.in_flight() == 1);
      CHECK(scheduler.complete(first, 9) == FrameDecision::OutputReady);
      consume_and_release(scheduler, first, 9);
      const auto second = ticket(scheduler.submit(2, 9, 20));
      CHECK(second.slot == first.slot);
      CHECK(second.serial != first.serial);
      CHECK(scheduler.complete(second, 10) == FrameDecision::OutputReady);
      consume_and_release(scheduler, second, 10);
      CHECK(scheduler.counts().outputs == 2);
    }},
    {"deadline fallback retains ownership until late completion", [] {
      FrameScheduler scheduler(1);
      const auto first = ticket(scheduler.submit(1, 0, 5));
      scheduler.advance_to(5);
      CHECK(scheduler.counts().fallbacks == 1);
      CHECK(scheduler.in_flight() == 1);
      CHECK(scheduler.submit(2, 5, 10).decision == FrameDecision::FallbackExhausted);
      scheduler.advance_to(6);
      CHECK(scheduler.counts().fallbacks == 2);
      CHECK(scheduler.complete(first, 7) == FrameDecision::CompletionDiscarded);
      CHECK(scheduler.in_flight() == 0);
      CHECK(scheduler.counts().fallbacks == 2);
      CHECK(scheduler.counts().outputs == 0);
      CHECK(scheduler.submit(3, 7, 10).ticket.has_value());
    }},
    {"completion exactly at deadline is never presented", [] {
      FrameScheduler scheduler(1);
      const auto first = ticket(scheduler.submit(1, 0, 5));
      CHECK(scheduler.complete(first, 5) == FrameDecision::CompletionDiscarded);
      CHECK(scheduler.counts().fallbacks == 1);
      CHECK(scheduler.counts().outputs == 0);
    }},
    {"already expired submissions allocate no slot", [] {
      FrameScheduler scheduler(1);
      CHECK(scheduler.submit(1, 4, 4).decision == FrameDecision::FallbackDeadline);
      CHECK(scheduler.submit(2, 4, 3).decision == FrameDecision::FallbackDeadline);
      CHECK(scheduler.in_flight() == 0);
      CHECK(scheduler.counts().submitted == 0);
    }},
    {"exhaustion remains bounded and completion can be non-FIFO", [] {
      FrameScheduler scheduler(2);
      const auto first = ticket(scheduler.submit(1, 0, 10));
      const auto second = ticket(scheduler.submit(2, 0, 10));
      CHECK(scheduler.submit(3, 0, 10).decision == FrameDecision::FallbackExhausted);
      CHECK(scheduler.capacity() == 2);
      CHECK(scheduler.complete(second, 1) == FrameDecision::OutputReady);
      CHECK(scheduler.in_flight() == 2);
      CHECK(scheduler.complete(first, 2) == FrameDecision::OutputReady);
      consume_and_release(scheduler, first, 2);
      consume_and_release(scheduler, second, 2);
      CHECK(scheduler.in_flight() == 0);
    }},
    {"duplicate completion cannot free a reused slot", [] {
      FrameScheduler scheduler(1);
      const auto first = ticket(scheduler.submit(1, 0, 10));
      CHECK(scheduler.complete(first, 1) == FrameDecision::OutputReady);
      consume_and_release(scheduler, first, 1);
      const auto second = ticket(scheduler.submit(2, 1, 10));
      CHECK(scheduler.complete(first, 2) == FrameDecision::StaleCompletion);
      CHECK(scheduler.in_flight() == 1);
      CHECK(scheduler.submit(3, 2, 10).decision == FrameDecision::FallbackExhausted);
      CHECK(scheduler.complete(second, 3) == FrameDecision::OutputReady);
    }},
    {"resize invalidates old output and retains old allocation ownership", [] {
      FrameScheduler scheduler(1);
      const auto first = ticket(scheduler.submit(1, 0, 10));
      scheduler.resize(1);
      CHECK(scheduler.generation() != first.generation);
      CHECK(scheduler.in_flight() == 1);
      CHECK(scheduler.submit(2, 1, 10).decision == FrameDecision::FallbackExhausted);
      CHECK(scheduler.complete(first, 2) == FrameDecision::CompletionDiscarded);
      const auto second = ticket(scheduler.submit(3, 2, 10));
      CHECK(second.generation == scheduler.generation());
      CHECK(scheduler.complete(first, 3) == FrameDecision::StaleCompletion);
      CHECK(scheduler.in_flight() == 1);
      CHECK(scheduler.complete(second, 4) == FrameDecision::OutputReady);
    }},
    {"suspend blocks work and resume never presents pre-suspend result", [] {
      FrameScheduler scheduler(2);
      const auto first = ticket(scheduler.submit(1, 0, 10));
      scheduler.suspend(1);
      CHECK(scheduler.state() == SchedulerState::Suspended);
      CHECK(scheduler.in_flight() == 1);
      CHECK(scheduler.submit(2, 1, 10).decision == FrameDecision::FallbackUnavailable);
      CHECK(scheduler.resume(2));
      const auto second = ticket(scheduler.submit(3, 2, 10));
      CHECK(scheduler.complete(first, 3) == FrameDecision::CompletionDiscarded);
      CHECK(scheduler.complete(second, 4) == FrameDecision::OutputReady);
    }},
    {"crash retains ownership and blocks premature restart", [] {
      FrameScheduler scheduler(1);
      const auto first = ticket(scheduler.submit(1, 0, 10));
      scheduler.crash(1);
      CHECK(scheduler.state() == SchedulerState::Crashed);
      CHECK(scheduler.in_flight() == 1);
      CHECK(!scheduler.restart(2));
      CHECK(!scheduler.resume(2));
      CHECK(scheduler.submit(2, 2, 10).decision == FrameDecision::FallbackUnavailable);
      CHECK(scheduler.complete(first, 3) == FrameDecision::CompletionDiscarded);
      CHECK(scheduler.restart(4));
      CHECK(scheduler.submit(3, 4, 10).ticket.has_value());
    }},
    {"quiescence acknowledgement reclaims crashed slots safely", [] {
      FrameScheduler scheduler(1);
      CHECK(!scheduler.acknowledge_quiescence(0));
      const auto old = ticket(scheduler.submit(1, 0, 10));
      scheduler.crash(1);
      CHECK(scheduler.acknowledge_quiescence(2));
      CHECK(scheduler.in_flight() == 0);
      CHECK(scheduler.restart(3));
      const auto current = ticket(scheduler.submit(2, 3, 10));
      CHECK(scheduler.complete(old, 4) == FrameDecision::StaleCompletion);
      CHECK(scheduler.in_flight() == 1);
      CHECK(scheduler.complete(current, 5) == FrameDecision::OutputReady);
    }},
    {"repeated invalidation does not duplicate frame fallback", [] {
      FrameScheduler scheduler(1);
      const auto first = ticket(scheduler.submit(1, 0, 10));
      scheduler.resize(1);
      scheduler.suspend(2);
      scheduler.crash(3);
      scheduler.advance_to(20);
      CHECK(scheduler.counts().fallbacks == 1);
      CHECK(scheduler.in_flight() == 1);
      CHECK(scheduler.complete(first, 21) == FrameDecision::CompletionDiscarded);
    }},
    {"invalid tickets cannot release an occupied slot", [] {
      FrameScheduler scheduler(1);
      const auto first = ticket(scheduler.submit(1, 0, 10));
      CHECK(scheduler.complete({1, first.generation, first.serial}, 1) == FrameDecision::StaleCompletion);
      CHECK(scheduler.complete({0, first.generation + 1, first.serial}, 1) == FrameDecision::StaleCompletion);
      CHECK(scheduler.complete({0, first.generation, first.serial + 1}, 1) == FrameDecision::StaleCompletion);
      CHECK(scheduler.in_flight() == 1);
      CHECK(scheduler.complete(first, 2) == FrameDecision::OutputReady);
    }},
    {"duplicate live frame identifiers fall back without overwriting", [] {
      FrameScheduler scheduler(2);
      const auto first = ticket(scheduler.submit(1, 0, 10));
      CHECK(scheduler.submit(1, 1, 10).decision == FrameDecision::FallbackDuplicateFrame);
      CHECK(scheduler.in_flight() == 1);
      CHECK(scheduler.complete(first, 2) == FrameDecision::OutputReady);
    }},
    {"virtual clock rejects backwards movement before mutation", [] {
      FrameScheduler scheduler(1);
      const auto first = ticket(scheduler.submit(1, 5, 10));
      invalid_argument([&] { scheduler.complete(first, 4); });
      invalid_argument([&] { scheduler.resize(4); });
      CHECK(scheduler.now() == 5);
      CHECK(scheduler.generation() == first.generation);
      CHECK(scheduler.in_flight() == 1);
      CHECK(scheduler.complete(first, 6) == FrameDecision::OutputReady);
    }},
    {"diagnostic event history is bounded without losing counters", [] {
      FrameScheduler scheduler(1);
      for (Tick i = 0; i < 400; ++i) {
        const auto current = ticket(scheduler.submit(i, i, i + 1));
        CHECK(scheduler.complete(current, i) == FrameDecision::OutputReady);
        consume_and_release(scheduler, current, i);
      }
      CHECK(scheduler.events().size() == FrameScheduler::event_capacity);
      CHECK(scheduler.counts().submitted == 400);
      CHECK(scheduler.counts().outputs == 400);
      CHECK(scheduler.counts().outputs_consumed == 400);
      CHECK(scheduler.counts().consumer_releases == 400);
      CHECK(scheduler.counts().dropped_events == 1600 - FrameScheduler::event_capacity);
    }},
    {"producer completion retains ready output through consumer release", [] {
      FrameScheduler scheduler(1);
      const auto first = ticket(scheduler.submit(1, 0, 10));
      CHECK(scheduler.complete(first, 1) == FrameDecision::OutputReady);
      CHECK(scheduler.in_flight() == 1);
      CHECK(scheduler.submit(2, 1, 10).decision == FrameDecision::FallbackExhausted);
      CHECK(scheduler.consume_output(first, 2) == FrameDecision::OutputConsumed);
      CHECK(scheduler.in_flight() == 1);
      CHECK(scheduler.complete(first, 2) == FrameDecision::StaleCompletion);
      CHECK(scheduler.in_flight() == 1);
      CHECK(scheduler.release_output(first, 3) == FrameDecision::OutputReleased);
      CHECK(scheduler.in_flight() == 0);
      CHECK(scheduler.submit(2, 3, 10).ticket.has_value());
    }},
    {"late GPU consumer fallback retains slot until consumer acknowledgement", [] {
      FrameScheduler scheduler(1);
      const auto first = ticket(scheduler.submit(1, 0, 5));
      CHECK(scheduler.complete(first, 1) == FrameDecision::OutputReady);
      CHECK(scheduler.consume_output(first, 2) == FrameDecision::OutputConsumed);
      scheduler.advance_to(5);
      CHECK(scheduler.counts().fallbacks == 1);
      CHECK(scheduler.in_flight() == 1);
      CHECK(scheduler.submit(2, 5, 10).decision == FrameDecision::FallbackExhausted);
      CHECK(scheduler.release_output(first, 6) == FrameDecision::OutputReleased);
      CHECK(scheduler.in_flight() == 0);
      CHECK(scheduler.counts().fallbacks == 2);
    }},
    {"ready output that misses acquisition deadline remains owned until dropped", [] {
      FrameScheduler scheduler(1);
      const auto first = ticket(scheduler.submit(1, 0, 5));
      CHECK(scheduler.complete(first, 2) == FrameDecision::OutputReady);
      scheduler.advance_to(5);
      CHECK(scheduler.in_flight() == 1);
      CHECK(scheduler.consume_output(first, 5) == FrameDecision::InvalidConsumerAcquire);
      CHECK(scheduler.counts().outputs_consumed == 0);
      CHECK(scheduler.release_output(first, 6) == FrameDecision::OutputReleased);
      CHECK(scheduler.in_flight() == 0);
      CHECK(scheduler.counts().fallbacks == 1);
    }},
    {"resize retains ready and consuming slots until explicit release", [] {
      for (const bool consuming : {false, true}) {
        FrameScheduler scheduler(1);
        const auto first = ticket(scheduler.submit(1, 0, 10));
        CHECK(scheduler.complete(first, 1) == FrameDecision::OutputReady);
        if (consuming) CHECK(scheduler.consume_output(first, 1) == FrameDecision::OutputConsumed);
        scheduler.resize(2);
        CHECK(scheduler.in_flight() == 1);
        CHECK(scheduler.consume_output(first, 2) == FrameDecision::InvalidConsumerAcquire);
        CHECK(scheduler.submit(2, 2, 10).decision == FrameDecision::FallbackExhausted);
        CHECK(scheduler.release_output(first, 3) == FrameDecision::OutputReleased);
        const auto second = ticket(scheduler.submit(2, 3, 10));
        CHECK(scheduler.release_output(first, 4) == FrameDecision::StaleCompletion);
        CHECK(scheduler.in_flight() == 1);
        CHECK(scheduler.complete(second, 5) == FrameDecision::OutputReady);
      }
    }},
    {"consumer cannot release a producer-owned allocation", [] {
      FrameScheduler scheduler(1);
      const auto first = ticket(scheduler.submit(1, 0, 10));
      CHECK(scheduler.release_output(first, 1) == FrameDecision::InvalidConsumerRelease);
      CHECK(scheduler.consume_output(first, 1) == FrameDecision::InvalidConsumerAcquire);
      CHECK(scheduler.in_flight() == 1);
      CHECK(scheduler.complete(first, 2) == FrameDecision::OutputReady);
      CHECK(scheduler.release_output(first, 2) == FrameDecision::OutputReleased);
      CHECK(scheduler.counts().outputs_consumed == 0);
    }},
    {"older producer result cannot follow newer accepted frame", [] {
      FrameScheduler scheduler(2);
      const auto old = ticket(scheduler.submit(1, 0, 10));
      const auto newer = ticket(scheduler.submit(2, 0, 10));
      CHECK(scheduler.complete(newer, 1) == FrameDecision::OutputReady);
      consume_and_release(scheduler, newer, 1);
      CHECK(scheduler.complete(old, 2) == FrameDecision::CompletionDiscarded);
      CHECK(scheduler.counts().outputs_consumed == 1);
      CHECK(scheduler.counts().fallbacks == 1);
      CHECK(scheduler.in_flight() == 0);
    }},
    {"older ready output cannot be consumed after newer frame", [] {
      FrameScheduler scheduler(2);
      const auto old = ticket(scheduler.submit(1, 0, 10));
      const auto newer = ticket(scheduler.submit(2, 0, 10));
      CHECK(scheduler.complete(old, 1) == FrameDecision::OutputReady);
      CHECK(scheduler.complete(newer, 1) == FrameDecision::OutputReady);
      consume_and_release(scheduler, newer, 2);
      CHECK(scheduler.consume_output(old, 3) == FrameDecision::FallbackStaleOutput);
      CHECK(scheduler.in_flight() == 1);
      CHECK(scheduler.release_output(old, 3) == FrameDecision::OutputReleased);
      CHECK(scheduler.counts().outputs_consumed == 1);
    }},
    {"generation change resets frame ordering while retaining old consumer", [] {
      FrameScheduler scheduler(2);
      const auto old = ticket(scheduler.submit(100, 0, 10));
      CHECK(scheduler.complete(old, 1) == FrameDecision::OutputReady);
      CHECK(scheduler.consume_output(old, 1) == FrameDecision::OutputConsumed);
      scheduler.resize(2);
      const auto current = ticket(scheduler.submit(1, 2, 10));
      CHECK(scheduler.complete(current, 3) == FrameDecision::OutputReady);
      consume_and_release(scheduler, current, 3);
      CHECK(scheduler.in_flight() == 1);
      CHECK(scheduler.release_output(old, 4) == FrameDecision::OutputReleased);
      CHECK(scheduler.in_flight() == 0);
    }},
    {"crash cannot recycle GPU consumer before all-device quiescence", [] {
      FrameScheduler scheduler(1);
      const auto old = ticket(scheduler.submit(1, 0, 10));
      CHECK(scheduler.complete(old, 1) == FrameDecision::OutputReady);
      CHECK(scheduler.consume_output(old, 1) == FrameDecision::OutputConsumed);
      scheduler.crash(2);
      CHECK(!scheduler.restart(3));
      CHECK(scheduler.in_flight() == 1);
      CHECK(scheduler.acknowledge_quiescence(4));
      CHECK(scheduler.restart(4));
      const auto current = ticket(scheduler.submit(2, 4, 10));
      CHECK(scheduler.release_output(old, 5) == FrameDecision::StaleCompletion);
      CHECK(scheduler.in_flight() == 1);
      CHECK(scheduler.complete(current, 6) == FrameDecision::OutputReady);
    }},
    {"JSON encoding escapes controls quotes slashes and arbitrary bytes", [] {
      CHECK(json_string("a\"\\\n\t\r\b\f") == "\"a\\\"\\\\\\n\\t\\r\\b\\f\"");
      const std::string bytes{static_cast<char>(0), static_cast<char>(1),
                              static_cast<char>(0x7f), static_cast<char>(0xff)};
      CHECK(json_string(bytes) == "\"\\u0000\\u0001\\u007f\\u00ff\"");
      CHECK(json_string("/tmp/no-execution") == "\"/tmp/no-execution\"");
    }},
  };

  std::size_t passed = 0;
  for (const auto& [name, run] : tests) {
    try {
      run();
      ++passed;
      std::cout << "PASS " << name << '\n';
    } catch (const std::exception& exception) {
      std::cerr << "FAIL " << name << ": " << exception.what() << '\n';
    }
  }
  std::cout << passed << '/' << tests.size() << " core tests passed\n";
  return passed == tests.size() ? 0 : 1;
}

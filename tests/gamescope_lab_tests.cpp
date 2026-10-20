#include "experiments/gamescope/docksr_lab.hpp"

#include <iostream>
#include <limits>
#include <string>
#include <vector>

using namespace docksr::lab;

namespace {
unsigned checks{}, failures{};
std::vector<std::string> observations;

void check(bool condition, const char* description) {
    ++checks;
    if (!condition) { ++failures; std::cerr << "FAIL: " << description << '\n'; }
}

Identity identity() {
    // Explicit contract evidence: these callbacks do not exercise a renderer.
    return {std::string(40, 'a'), std::string(40, 'b'), "contract-session",
            "unit_test", Evidence::ContractTest, "none"};
}

LabState attached() {
    LabState state(identity());
    state.set_attached(true);
    return state;
}

void observe(const LabState& state) { observations.push_back(state.json()); }

void pending_and_status() {
    auto state = attached();
    observe(state);
    check(state.command("ON 1").accepted, "ON accepted without a frame");
    const auto& s = state.snapshot();
    check(s.mode_requested == Mode::Active && s.mode_effective == Mode::Unavailable,
          "no-frame request changes requested state only");
    check(s.configuration_generation == 0 && s.requested_configuration_generation == 1,
          "pending generation is distinct from effective generation");
    check(s.frame_seen_count == 0 && s.frame_processed_count == 0 && s.frame_presented_count == 0,
          "requests alone do not count frames");
    check(s.control_ack_state == "PENDING" && !s.filter_selected && !s.filter_dispatched,
          "no false selection or acknowledgement without a frame");
    check(state.command("STATUS 2").ack == "STATUS", "STATUS reply accepted");
    check(s.last_request_id == 2 && s.last_control_request_id == 1 && s.control_ack_state == "PENDING",
          "STATUS cannot consume a mode acknowledgement");
    observe(state);
    auto frame = state.begin_frame(1, {1280, 720}, {3840, 2160});
    check(frame == FrameToken{1, 1} && s.control_ack_state == "APPLIED", "safe boundary applies pending mode");
    check(s.filter_selected && !s.filter_dispatched && !s.filter_output_presented,
          "selection is separate from dispatch and presentation");
    check(!state.mark_presented(frame), "custom output cannot present before dispatch");
    check(s.frame_presented_count == 0, "rejected early present leaves counter unchanged");
    check(state.mark_dispatched(frame), "dispatch accepted for current selected frame");
    check(!state.mark_dispatched(frame) && s.frame_processed_count == 1, "duplicate dispatch is rejected");
    check(state.mark_presented(frame), "presentation accepted after dispatch");
    check(s.control_ack_state == "PRESENTED" && s.frame_presented_count == 1 && s.filter_frame_presented_count == 1,
          "presented acknowledgement comes from presentation callback");
    check(!state.mark_presented(frame) && s.frame_presented_count == 1, "duplicate presentation is rejected");
    observe(state);
}

void live_sequence_and_stale_events() {
    auto state = attached();
    check(state.command("ON 10").accepted, "sequence ON accepted");
    auto first = state.begin_frame(100, {1280, 720}, {3840, 2160});
    check(state.mark_dispatched(first) && state.mark_presented(first), "first ON frame observed");
    observe(state);
    check(state.command("BYPASS 11\n").accepted, "BYPASS with one LF accepted");
    check(state.snapshot().mode_effective == Mode::Active && state.snapshot().control_ack_state == "PENDING",
          "BYPASS remains pending before next boundary");
    auto second = state.begin_frame(101, {1280, 720}, {3840, 2160});
    check(second.generation == 2 && state.snapshot().mode_effective == Mode::Bypass, "BYPASS applied next frame");
    check(!state.mark_dispatched(first) && !state.mark_presented(first), "old-generation events rejected");
    check(!state.mark_dispatched(second), "BYPASS never claims custom dispatch");
    check(state.mark_presented(second) && !state.snapshot().filter_output_presented, "BYPASS presentation is separate");
    observe(state);
    check(state.command("ON 12").accepted, "second ON accepted");
    auto third = state.begin_frame(102, {1280, 720}, {3840, 2160});
    check(!state.mark_dispatched({third.id, first.generation}), "forged stale generation rejected");
    check(state.mark_dispatched(third) && state.mark_presented(third), "second ON frame observed");
    const auto& s = state.snapshot();
    check(s.configuration_generation == 3 && s.requested_configuration_generation == 3,
          "ON BYPASS ON has three applied generations");
    check(s.frame_seen_count == 3 && s.frame_processed_count == 2 && s.frame_presented_count == 3 &&
          s.filter_frame_presented_count == 2, "custom processing and all presentation counts differ correctly");
    check(state.identity().session_id == "contract-session", "live sequence retains one session identity");
    observe(state);

    check(state.command("BYPASS 13").accepted, "new pending request accepted after completed frame");
    auto fourth = state.begin_frame(103, {1280, 720}, {3840, 2160});
    check(state.command("ON 14").accepted, "mid-frame next request remains pending");
    check(state.mark_presented(fourth) && state.snapshot().control_ack_state == "PENDING",
          "old effective generation cannot acknowledge newer request");
    observe(state);
    check(state.begin_frame(103, {1280, 720}, {3840, 2160}).id == 0, "duplicate frame ID rejected");
    check(state.begin_frame(0, {1280, 720}, {3840, 2160}).id == 0, "zero frame ID rejected");
    check(state.snapshot().frame_seen_count == 4, "invalid IDs leave seen count unchanged");
}

void malformed_control() {
    auto state = attached();
    state.command("ON 100");
    std::vector<std::string> invalid = {
        "", "ON", "ON ", "ON 0", "ON -1", "ON +1", "ON 1x", "ON 18446744073709551616",
        "ON 100", "STATUS 99", "on 101", "REAL_NPU 101", "ON  101", " ON 101", "ON 101 ",
        "ON\t101", "ON 101\r\n", "ON 101\n\n", std::string(65, 'A'), std::string("ON 101\0", 7),
        std::string("ON 101") + char(0x80)
    };
    for (const auto& command : invalid) {
        check(!state.command(command).accepted, "malformed or stale command rejected");
        check(state.snapshot().last_request_id == 100 && state.snapshot().requested_configuration_generation == 1 &&
              state.snapshot().control_ack_state == "PENDING", "rejection preserves accepted control state");
    }
    check(state.command("STATUS 18446744073709551615").accepted, "maximum uint64 request ID accepted");
    check(!state.command("ON 18446744073709551615").accepted, "maximum ID cannot be reused");
    observe(state);
}

void fallback_cases() {
    struct Case { Extent input, output; bool sdr, resources; const char* reason; };
    const Case cases[] = {
        {{1279, 720}, {3840, 2160}, true, true, "INVALID_GEOMETRY"},
        {{1280, 720}, {3840, 2159}, true, true, "INVALID_GEOMETRY"},
        {{0, 0}, {0, 0}, true, true, "INVALID_GEOMETRY"},
        {{1280, 720}, {3840, 2160}, false, true, "UNSUPPORTED_COLORSPACE"},
        {{1280, 720}, {3840, 2160}, true, false, "RESOURCE_UNAVAILABLE"}
    };
    for (const auto& c : cases) {
        auto state = attached(); state.command("ON 1");
        auto frame = state.begin_frame(1, c.input, c.output, c.sdr, c.resources);
        const auto& s = state.snapshot();
        check(s.mode_effective == Mode::Fallback && s.fallback_reason == c.reason && s.fallback_count == 1,
              "unsupported input selects explicit fallback");
        check(s.filter_selected && !state.mark_dispatched(frame) && s.frame_processed_count == 0,
              "fallback does not claim custom processing");
        check(state.mark_presented(frame) && !s.filter_output_presented && s.filter_frame_presented_count == 0,
              "linear fallback presentation does not claim custom pixels");
        check(s.control_ack_state == "FALLBACK_PRESENTED", "fallback presentation acknowledges fallback explicitly");
        observe(state);
    }
    auto state = attached(); state.command("ON 1");
    auto frame = state.begin_frame(1, {1280, 720}, {3840, 2160});
    check(state.mark_dispatched(frame), "dispatch before resource failure recorded");
    check(state.fail_frame(frame, "BLIT_INIT_FAILED") && state.fail_frame(frame, "BLIT_INIT_FAILED"),
          "initialization error takes fallback");
    check(state.snapshot().fallback_count == 1 && state.snapshot().frame_processed_count == 1 &&
          !state.snapshot().filter_output_presented, "one fallback per frame retains authentic prior dispatch");
    check(!state.fail_frame(frame, "unsanitized message"), "failure reason bounds reject arbitrary text");
    check(state.mark_presented(frame) && !state.snapshot().filter_output_presented, "failed custom frame can present linear fallback");
    check(!state.fail_frame(frame, "LATE_FAILURE"), "presented frame cannot be retroactively failed");
    observe(state);

    LabState detached(identity()); detached.command("ON 1");
    auto unattached_frame = detached.begin_frame(1, {1280, 720}, {3840, 2160});
    check(detached.snapshot().mode_effective == Mode::Unavailable &&
          detached.snapshot().fallback_reason == "BACKEND_NOT_ATTACHED", "unattached backend unavailable");
    check(!detached.mark_dispatched(unattached_frame), "unattached backend cannot dispatch");
    observe(detached);
    detached.set_attached(true);
    auto attached_frame = detached.begin_frame(2, {1280, 720}, {3840, 2160});
    detached.set_attached(false);
    check(!detached.mark_dispatched(attached_frame), "detaching invalidates pending frame token");
    observe(detached);
}

void evidence_and_serialization() {
    const Evidence no_execution[] = {Evidence::SourceInspected, Evidence::BuildVerified, Evidence::NotRun,
                                     Evidence::Blocked, Evidence::Failed};
    for (auto evidence : no_execution) {
        auto ident = identity(); ident.evidence = evidence; ident.environment = "cloud";
        LabState state(ident); state.set_attached(true); state.command("ON 1");
        check(state.begin_frame(1, {1280, 720}, {3840, 2160}).id == 0 && state.snapshot().frame_seen_count == 0,
              "nonexecution evidence cannot acquire fake frame counts");
        observe(state);
    }
    auto ident = identity(); ident.environment = "cloud";
    LabState invalid_environment(ident);
    check(!invalid_environment.valid(), "contract evidence requires explicit unit_test environment");
    ident = identity(); ident.upstream_commit = "short";
    LabState invalid_sha(ident);
    check(!invalid_sha.valid() && !invalid_sha.command("ON 1").accepted &&
          invalid_sha.begin_frame(1, {1280, 720}, {3840, 2160}).id == 0, "invalid identity cannot execute");
    ident = identity(); ident.session_id = std::string(129, 's');
    check(!LabState(ident).valid(), "identity string bounds enforced");
    auto state = attached();
    check(state.set_execution_context(Evidence::ContractTest, "unit_test", "none"), "valid preframe context accepted");
    state.command("ON 1"); state.begin_frame(1, {1280, 720}, {3840, 2160});
    check(!state.set_execution_context(Evidence::PhysicalGpu, "physical", "screenshot"),
          "observations cannot be upgraded to hardware evidence retrospectively");
    const auto json = state.json();
    check(json == state.json(), "serialization is deterministic");
    for (const auto* field : {"npu_device_detected", "npu_runtime_ready", "npu_inference_verified", "npu_game_frames_consumed"})
        check(json.find(std::string("\"") + field + "\":false") != std::string::npos, "NPU status is forced false");
    check(json.find("REAL_NPU") == std::string::npos, "contract never claims real NPU evidence");
    check(json_string(std::string("\"\\\n\0", 4)) == "\"\\\"\\\\\\u000a\\u0000\"", "JSON escapes quotes, slash and controls");
    observe(state);
}
} // namespace

int main(int argc, char** argv) {
    pending_and_status(); live_sequence_and_stale_events(); malformed_control(); fallback_cases(); evidence_and_serialization();
    if (failures) { std::cerr << failures << " of " << checks << " contract checks failed\n"; return 1; }
    if (argc == 2 && (std::string_view(argv[1]) == "--json" || std::string_view(argv[1]) == "--emit-json"))
        for (const auto& json : observations) std::cout << json << '\n';
    else std::cout << "PASS: " << checks << " Gamescope-lab contract checks; callback tests only, no rendering or hardware proof\n";
}

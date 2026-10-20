#pragma once

// DockSR-owned R006-M1 control/observation contract. Single trusted owner thread.
// Calling an observation method is not proof that rendering occurred: the
// Gamescope adapter must call it only after the corresponding actual operation.
// This is neither a renderer, frame scheduler, nor a public Gamescope ABI.

#include <charconv>
#include <cstdint>
#include <limits>
#include <optional>
#include <sstream>
#include <string>
#include <string_view>
#include <utility>

namespace docksr::lab {

enum class Mode { Active, Bypass, Fallback, Unavailable };
enum class Evidence {
    SourceInspected, BuildVerified, SoftwareVulkan, VirtualWindow,
    NestedLiveGame, PhysicalGpu, NotRun, Blocked, Failed, ContractTest
};

inline std::string_view name(Mode mode) {
    switch (mode) {
        case Mode::Active: return "DOCKSR_ACTIVE";
        case Mode::Bypass: return "BYPASS";
        case Mode::Fallback: return "FALLBACK";
        case Mode::Unavailable: return "UNAVAILABLE";
    }
    return "INVALID";
}

inline std::string_view name(Evidence evidence) {
    switch (evidence) {
        case Evidence::SourceInspected: return "SOURCE_INSPECTED";
        case Evidence::BuildVerified: return "BUILD_VERIFIED";
        case Evidence::SoftwareVulkan: return "SOFTWARE_VULKAN";
        case Evidence::VirtualWindow: return "VIRTUAL_WINDOW";
        case Evidence::NestedLiveGame: return "NESTED_LIVE_GAME";
        case Evidence::PhysicalGpu: return "PHYSICAL_GPU";
        case Evidence::NotRun: return "NOT_RUN";
        case Evidence::Blocked: return "BLOCKED";
        case Evidence::Failed: return "FAILED";
        case Evidence::ContractTest: return "CONTRACT_TEST";
    }
    return "INVALID";
}

inline bool execution_evidence(Evidence evidence) {
    return evidence == Evidence::SoftwareVulkan || evidence == Evidence::VirtualWindow ||
           evidence == Evidence::NestedLiveGame || evidence == Evidence::PhysicalGpu ||
           evidence == Evidence::ContractTest;
}

struct Extent {
    std::uint32_t width{}, height{};
    bool operator==(const Extent&) const = default;
};

struct Identity {
    std::string upstream_commit;
    std::string docksr_commit;
    std::string session_id;
    std::string environment{"unspecified"};
    Evidence evidence{Evidence::NotRun};
    std::string capture_method{"none"};
};

struct FrameToken {
    std::uint64_t id{}, generation{};
    bool operator==(const FrameToken&) const = default;
};

struct CommandReply {
    bool accepted{};
    std::uint64_t request_id{};
    std::string_view ack{"REJECTED"};
    std::string_view error;
};

struct Snapshot {
    bool backend_present{true}, backend_attached{};
    Mode mode_requested{Mode::Bypass}, mode_effective{Mode::Unavailable};
    std::uint64_t requested_configuration_generation{}, configuration_generation{};
    bool filter_selected{}, filter_dispatched{}, filter_output_presented{};
    std::optional<Extent> input_extent, output_extent;
    std::uint64_t frame_seen_count{}, frame_processed_count{}, frame_presented_count{};
    // frame_presented_count counts all reported presentations, including linear
    // bypass/fallback. This additional count includes only the custom output.
    std::uint64_t filter_frame_presented_count{}, fallback_count{};
    std::optional<std::uint64_t> last_frame_id, last_frame_generation;
    std::string fallback_reason, last_error;
    std::string control_ack_state{"NONE"};
    // Last mutating request is separate from any later STATUS request.
    std::uint64_t last_control_request_id{}, last_request_id{};
};

inline std::string json_string(std::string_view value) {
    constexpr char hex[] = "0123456789abcdef";
    std::string result{"\""};
    for (unsigned char c : value) {
        if (c == '"' || c == '\\') { result += '\\'; result += static_cast<char>(c); }
        else if (c < 0x20 || c >= 0x7f) {
            result += "\\u00"; result += hex[c >> 4]; result += hex[c & 15];
        } else result += static_cast<char>(c);
    }
    return result + '"';
}

class LabState {
public:
    explicit LabState(Identity identity) : identity_(std::move(identity)) {
        valid_ = sha(identity_.upstream_commit) && sha(identity_.docksr_commit) &&
            identifier(identity_.session_id, 128) && identifier(identity_.environment, 128) &&
            identifier(identity_.capture_method, 128) && name(identity_.evidence) != "INVALID" &&
            (identity_.evidence != Evidence::ContractTest || identity_.environment == "unit_test");
        if (!valid_) state_.last_error = "INVALID_IDENTITY";
    }

    bool valid() const { return valid_; }
    const Snapshot& snapshot() const { return state_; }
    const Identity& identity() const { return identity_; }

    // Set observed execution classification before the first actual frame.
    // Once callbacks exist, their evidence cannot be relabeled retroactively.
    bool set_execution_context(Evidence evidence, std::string environment, std::string capture_method) {
        if (!valid_ || state_.frame_seen_count || name(evidence) == "INVALID" ||
            !identifier(environment, 128) || !identifier(capture_method, 128) ||
            (evidence == Evidence::ContractTest && environment != "unit_test")) {
            state_.last_error = "INVALID_EXECUTION_CONTEXT";
            return false;
        }
        identity_.evidence = evidence;
        identity_.environment = std::move(environment);
        identity_.capture_method = std::move(capture_method);
        return true;
    }

    void set_attached(bool attached) {
        if (state_.backend_attached == attached) return;
        state_.backend_attached = attached;
        current_.reset();
        state_.filter_dispatched = state_.filter_output_presented = false;
        if (!attached) {
            state_.mode_effective = Mode::Unavailable;
            state_.fallback_reason = "BACKEND_NOT_ATTACHED";
        }
    }

    // Protocol v1: exact ASCII ON <id>, BYPASS <id>, STATUS <id>, optionally
    // ending in one LF. IDs are strictly increasing across accepted commands.
    // STATUS consumes its ID but does not acknowledge a pending mode change.
    CommandReply command(std::string_view input) {
        if (!valid_) return reject("INVALID_IDENTITY");
        if (!input.empty() && input.back() == '\n') input.remove_suffix(1);
        if (input.empty() || input.size() > 64) return reject("CONTROL_BOUNDS");
        for (unsigned char c : input) if (c < 0x20 || c > 0x7e) return reject("CONTROL_ENCODING");
        const auto space = input.find(' ');
        if (space == std::string_view::npos || input.find(' ', space + 1) != std::string_view::npos)
            return reject("CONTROL_SYNTAX");
        const auto operation = input.substr(0, space), number = input.substr(space + 1);
        if (operation != "ON" && operation != "BYPASS" && operation != "STATUS")
            return reject("CONTROL_OPERATION");
        std::uint64_t id{};
        const auto parsed = std::from_chars(number.data(), number.data() + number.size(), id);
        if (number.empty() || parsed.ec != std::errc{} || parsed.ptr != number.data() + number.size() || !id)
            return reject("CONTROL_REQUEST_ID");
        if (id <= state_.last_request_id) return reject("CONTROL_STALE_REQUEST");
        if (operation == "STATUS") {
            state_.last_request_id = id;
            return {true, id, "STATUS", {}};
        }
        if (!increment(state_.requested_configuration_generation)) return reject("COUNTER_EXHAUSTED");
        state_.last_request_id = state_.last_control_request_id = id;
        state_.mode_requested = operation == "ON" ? Mode::Active : Mode::Bypass;
        state_.control_ack_state = "PENDING";
        state_.last_error.clear();
        return {true, id, "PENDING", {}};
    }

    // Called at an actual safe compositor frame boundary, never for a timer or
    // CLI-only selection. Only the latest frame is observed; no work is queued.
    FrameToken begin_frame(std::uint64_t id, Extent input, Extent output,
                           bool sdr = true, bool resources_available = true) {
        if (!valid_) return frame_rejected("INVALID_IDENTITY");
        if (!execution_evidence(identity_.evidence)) return frame_rejected("EXECUTION_EVIDENCE_REQUIRED");
        if (!id || (state_.last_frame_id && id <= *state_.last_frame_id))
            return frame_rejected("STALE_OR_INVALID_FRAME_ID");
        if (!increment(state_.frame_seen_count)) return frame_rejected("COUNTER_EXHAUSTED");
        state_.configuration_generation = state_.requested_configuration_generation;
        state_.filter_selected = state_.mode_requested == Mode::Active;
        state_.filter_dispatched = state_.filter_output_presented = false;
        state_.input_extent = input; state_.output_extent = output;
        state_.last_frame_id = id; state_.last_frame_generation = state_.configuration_generation;
        state_.fallback_reason.clear(); state_.last_error.clear();
        if (state_.last_control_request_id) state_.control_ack_state = "APPLIED";
        current_ = Current{FrameToken{id, state_.configuration_generation}};
        state_.mode_effective = state_.mode_requested;
        if (!state_.backend_attached) fallback("BACKEND_NOT_ATTACHED", Mode::Unavailable);
        else if (state_.mode_requested == Mode::Active) {
            if (input != Extent{1280, 720} || output != Extent{3840, 2160}) fallback("INVALID_GEOMETRY");
            else if (!sdr) fallback("UNSUPPORTED_COLORSPACE");
            else if (!resources_available) fallback("RESOURCE_UNAVAILABLE");
        }
        return current_->token;
    }

    bool mark_dispatched(FrameToken frame) {
        if (!matches(frame) || state_.mode_effective != Mode::Active || current_->dispatched || current_->presented)
            return event_rejected();
        if (!increment(state_.frame_processed_count)) return event_rejected("COUNTER_EXHAUSTED");
        current_->dispatched = true; state_.filter_dispatched = true;
        return true;
    }

    // The adapter must call after a real backend presentation operation. A
    // successful compute dispatch/composition alone must not call this method.
    bool mark_presented(FrameToken frame) {
        if (!matches(frame) || current_->presented ||
            (state_.mode_effective == Mode::Active && !current_->dispatched)) return event_rejected();
        const bool custom = state_.mode_effective == Mode::Active && current_->dispatched;
        if (state_.frame_presented_count == std::numeric_limits<std::uint64_t>::max() ||
            (custom && state_.filter_frame_presented_count == std::numeric_limits<std::uint64_t>::max()))
            return event_rejected("COUNTER_EXHAUSTED");
        current_->presented = true;
        state_.filter_output_presented = custom;
        increment(state_.frame_presented_count);
        if (custom) increment(state_.filter_frame_presented_count);
        if (state_.last_control_request_id && frame.generation == state_.requested_configuration_generation)
            state_.control_ack_state = current_->fallback_recorded ? "FALLBACK_PRESENTED" : "PRESENTED";
        return true;
    }

    bool fail_frame(FrameToken frame, std::string_view reason) {
        if (!identifier(reason, 128)) return event_rejected("INVALID_FAILURE_REASON");
        if (!matches(frame) || current_->presented) return event_rejected();
        fallback(reason);
        state_.last_error = reason;
        state_.filter_output_presented = false;
        return true;
    }

    std::string json() const {
        auto nullable_string = [](std::string_view value) { return value.empty() ? std::string("null") : json_string(value); };
        auto extent = [](const std::optional<Extent>& value) {
            return value ? "{\"width\":" + std::to_string(value->width) + ",\"height\":" + std::to_string(value->height) + "}" : "null";
        };
        auto optional_number = [](std::optional<std::uint64_t> value) { return value ? std::to_string(*value) : "null"; };
        std::ostringstream out;
        out << std::boolalpha << "{\"schema_version\":\"1.0.0\",\"document_type\":\"docksr_gamescope_lab\","
            << "\"experiment_id\":\"R006-M1\",\"control_protocol_version\":1,"
            << "\"upstream_gamescope_commit\":" << json_string(identity_.upstream_commit)
            << ",\"docksr_commit\":" << json_string(identity_.docksr_commit)
            << ",\"session_id\":" << json_string(identity_.session_id)
            << ",\"configuration_generation\":" << state_.configuration_generation
            << ",\"requested_configuration_generation\":" << state_.requested_configuration_generation
            << ",\"backend_present\":" << state_.backend_present << ",\"backend_attached\":" << state_.backend_attached
            << ",\"mode_requested\":" << json_string(name(state_.mode_requested))
            << ",\"mode_effective\":" << json_string(name(state_.mode_effective))
            << ",\"filter_selected\":" << state_.filter_selected << ",\"filter_dispatched\":" << state_.filter_dispatched
            << ",\"filter_output_presented\":" << state_.filter_output_presented
            << ",\"input_extent\":" << extent(state_.input_extent) << ",\"output_extent\":" << extent(state_.output_extent)
            << ",\"frame_seen_count\":" << state_.frame_seen_count << ",\"frame_processed_count\":" << state_.frame_processed_count
            << ",\"frame_presented_count\":" << state_.frame_presented_count
            << ",\"filter_frame_presented_count\":" << state_.filter_frame_presented_count
            << ",\"last_frame_id\":" << optional_number(state_.last_frame_id)
            << ",\"last_frame_generation\":" << optional_number(state_.last_frame_generation)
            << ",\"fallback_count\":" << state_.fallback_count << ",\"fallback_reason\":" << nullable_string(state_.fallback_reason)
            << ",\"last_error\":" << nullable_string(state_.last_error)
            << ",\"control_ack_state\":" << json_string(state_.control_ack_state)
            << ",\"last_control_request_id\":" << state_.last_control_request_id
            << ",\"last_request_id\":" << state_.last_request_id
            << ",\"evidence_class\":" << json_string(name(identity_.evidence))
            << ",\"capture_method\":" << json_string(identity_.capture_method)
            << ",\"environment\":" << json_string(identity_.environment)
            << ",\"npu_device_detected\":false,\"npu_runtime_ready\":false,"
               "\"npu_inference_verified\":false,\"npu_game_frames_consumed\":false}";
        return out.str();
    }

private:
    struct Current { FrameToken token; bool dispatched{}, presented{}, fallback_recorded{}; };
    Identity identity_;
    bool valid_{};
    Snapshot state_;
    std::optional<Current> current_;

    static bool sha(std::string_view value) {
        if (value.size() != 40) return false;
        for (char c : value) if (!((c >= '0' && c <= '9') || (c >= 'a' && c <= 'f'))) return false;
        return true;
    }
    static bool identifier(std::string_view value, std::size_t maximum) {
        if (value.empty() || value.size() > maximum) return false;
        for (char c : value)
            if (!((c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') || (c >= '0' && c <= '9') ||
                  c == '_' || c == '-' || c == '.' || c == ':')) return false;
        return true;
    }
    static bool increment(std::uint64_t& count) {
        if (count == std::numeric_limits<std::uint64_t>::max()) return false;
        ++count;
        return true;
    }
    CommandReply reject(std::string_view code) {
        state_.last_error = code;
        return {false, 0, "REJECTED", code};
    }
    bool matches(FrameToken frame) const { return current_ && current_->token == frame; }
    FrameToken frame_rejected(std::string_view code) {
        state_.last_error = code;
        return {};
    }
    bool event_rejected(std::string_view code = "STALE_OR_INVALID_FRAME_EVENT") {
        state_.last_error = code;
        return false;
    }
    void fallback(std::string_view reason, Mode effective = Mode::Fallback) {
        state_.mode_effective = effective;
        state_.fallback_reason = reason;
        state_.filter_output_presented = false;
        if (!current_->fallback_recorded) {
            if (!increment(state_.fallback_count)) state_.last_error = "COUNTER_EXHAUSTED";
            current_->fallback_recorded = true;
        }
        if (state_.last_control_request_id) state_.control_ack_state = "FALLBACK";
    }
};

} // namespace docksr::lab

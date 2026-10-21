#include "docksr/core/inference_worker.hpp"
#include "docksr/core/json.hpp"

#include <algorithm>
#include <cmath>
#include <cstring>
#include <limits>
#include <sstream>
#include <stdexcept>
#include <utility>

namespace docksr::inference {
namespace {
constexpr std::uint64_t kMaximumTensorBytes = 64u * 1024u * 1024u;

bool add(std::uint64_t a, std::uint64_t b, std::uint64_t& out) {
  if (b > std::numeric_limits<std::uint64_t>::max() - a) return false;
  out = a + b;
  return true;
}
bool multiply(std::uint64_t a, std::uint64_t b, std::uint64_t& out) {
  if (a && b > std::numeric_limits<std::uint64_t>::max() / a) return false;
  out = a * b;
  return true;
}
std::uint64_t element_bytes(std::string_view dtype) {
  return dtype == "float32" ? 4 : (dtype == "int8" || dtype == "uint8" ? 1 : 0);
}
bool identifier(std::string_view value) {
  if (value.empty() || value.size() > 128) return false;
  return std::all_of(value.begin(), value.end(), [](unsigned char c) {
    return (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') ||
           (c >= '0' && c <= '9') || c == '_' || c == '-' || c == '.' || c == ':';
  });
}
bool sha(std::string_view value) {
  return value.size() == 64 && std::all_of(value.begin(), value.end(), [](char c) {
    return (c >= '0' && c <= '9') || (c >= 'a' && c <= 'f');
  });
}
bool extent_valid(Extent value) {
  return value.width && value.height && value.width <= 8192 && value.height <= 8192;
}
std::uint64_t channels(std::string_view format) {
  if (format == "RGB8" || format == "RGB_INT8" || format == "RGB_FLOAT32") return 3;
  if (format == "RGBA8" || format == "RGBA_INT8" || format == "RGBA_FLOAT32") return 4;
  return 0;
}
std::string_view format_dtype(std::string_view format) {
  if (format == "RGB8" || format == "RGBA8") return "uint8";
  if (format == "RGB_INT8" || format == "RGBA_INT8") return "int8";
  if (format == "RGB_FLOAT32" || format == "RGBA_FLOAT32") return "float32";
  return {};
}
bool shape_matches(std::span<const std::uint64_t> shape, std::string_view layout,
                   Extent extent, std::uint64_t count) {
  if (shape.size() != 4 || shape[0] != 1) return false;
  if (layout == "NHWC") return shape[1] == extent.height && shape[2] == extent.width && shape[3] == count;
  if (layout == "NCHW") return shape[1] == count && shape[2] == extent.height && shape[3] == extent.width;
  return false;
}
Extent input_extent(const Request& request) {
  if (request.tensor_shape.size() != 4) return {};
  if (request.tensor_layout == "NHWC") return {std::uint32_t(request.tensor_shape[2]), std::uint32_t(request.tensor_shape[1])};
  if (request.tensor_layout == "NCHW") return {std::uint32_t(request.tensor_shape[3]), std::uint32_t(request.tensor_shape[2])};
  return {};
}
bool identity_matches(const Request& request, const Result& result) {
  return request.schema_version == result.schema_version && request.session_id == result.session_id &&
    request.frame_id == result.frame_id && request.configuration_generation == result.configuration_generation &&
    request.model_id == result.model_id && request.model_sha256 == result.model_sha256 && request.trace_id == result.trace_id;
}
bool evidence_matches(const Result& result) {
  if (result.backend_kind == "CPU_REFERENCE")
    return result.evidence_class == "REAL_CPU" || (!result.valid && result.evidence_class == "NOT_RUN");
  if (result.backend_kind == "DETERMINISTIC_MOCK") return result.evidence_class == "SIMULATED";
  if (result.backend_kind == "UNAVAILABLE") return !result.valid && result.evidence_class == "NOT_RUN";
  return false;
}
bool finite_buffer(std::span<const std::uint8_t> bytes, std::string_view dtype) {
  if (dtype != "float32") return true;
  if (bytes.size() % sizeof(float)) return false;
  for (std::size_t i = 0; i < bytes.size(); i += sizeof(float)) {
    float value;
    std::memcpy(&value, bytes.data() + i, sizeof(value));
    if (!std::isfinite(value)) return false;
  }
  return true;
}
bool ledger_matches(const Request& request, const Result& result) {
  const auto output = tensor_bytes(request.expected_output_shape, request.expected_output_dtype);
  if (!output || result.copy_count != result.ledger.host_copy_count ||
      result.logical_bytes != request.buffer_size + *output || !result.inference_duration ||
      result.ledger.inference_input_logical_bytes < request.buffer_size ||
      result.ledger.inference_output_logical_bytes < *output ||
      result.ledger.gpu_upload_bytes.has_value() ||
      result.ledger.crop_bytes > result.ledger.inference_output_logical_bytes ||
      !identifier(result.ledger.host_copy_direction) || !identifier(result.ledger.host_copy_scope) ||
      (result.ledger.host_copy_count == 0) != (result.ledger.host_copy_bytes == 0) ||
      result.ledger.runtime_internal_allocation_status != "UNKNOWN" ||
      result.ledger.runtime_internal_copy_status != "UNKNOWN") return false;
  return (result.backend_kind == "CPU_REFERENCE" && result.ledger.timing_class == "OBSERVED_HOST_CPU") ||
         (result.backend_kind == "DETERMINISTIC_MOCK" && result.ledger.timing_class == "SIMULATED");
}
std::string extent_json(Extent extent) {
  return "{\"width\":" + std::to_string(extent.width) + ",\"height\":" + std::to_string(extent.height) + "}";
}
std::string numbers(std::span<const std::uint64_t> values) {
  std::string result{"["};
  for (std::size_t i = 0; i < values.size(); ++i) {
    if (i) result += ',';
    result += std::to_string(values[i]);
  }
  return result + ']';
}
std::string optional_number(std::optional<std::uint64_t> value) {
  return value ? std::to_string(*value) : "null";
}
void initialize_logical_ledger(const Request& request, Result& result) {
  const auto in = tensor_bytes(request.tensor_shape, request.tensor_dtype);
  const auto out = tensor_bytes(request.expected_output_shape, request.expected_output_dtype);
  result.ledger.source_logical_bytes = std::uint64_t(request.source_extent.width) * request.source_extent.height *
    channels(request.source_format) * element_bytes(format_dtype(request.source_format));
  result.ledger.inference_input_logical_bytes = in.value_or(0);
  result.ledger.inference_output_logical_bytes = out.value_or(0);
  result.ledger.tile_count = request.tile ? 1 : 0;
}
}  // namespace

std::optional<std::uint64_t> tensor_bytes(std::span<const std::uint64_t> shape, std::string_view dtype) {
  std::uint64_t result = element_bytes(dtype);
  if (!result || shape.empty() || shape.size() > 8) return {};
  for (auto value : shape) {
    if (!value || value > 8192 || !multiply(result, value, result)) return {};
  }
  return result;
}

std::vector<std::uint64_t> contiguous_strides(std::span<const std::uint64_t> shape, std::string_view dtype) {
  if (!tensor_bytes(shape, dtype)) return {};
  std::vector<std::uint64_t> strides(shape.size());
  std::uint64_t stride = element_bytes(dtype);
  for (std::size_t i = shape.size(); i-- > 0;) {
    strides[i] = stride;
    if (!multiply(stride, shape[i], stride)) return {};
  }
  return strides;
}

std::string validate_request(const Request& request, std::uint64_t maximum) {
  if (request.schema_version != "1.0.0") return "SCHEMA_VERSION";
  if (!identifier(request.session_id) || !identifier(request.model_id) || !identifier(request.trace_id)) return "IDENTIFIER";
  if (!request.frame_id || !request.configuration_generation) return "FRAME_IDENTITY";
  if (!sha(request.model_sha256)) return "MODEL_SHA256";
  if (!extent_valid(request.source_extent) || !extent_valid(request.expected_output_extent)) return "EXTENT";
  const auto channel_count = channels(request.source_format);
  if (!channel_count || !channels(request.expected_output_format)) return "PIXEL_FORMAT";
  const auto in = tensor_bytes(request.tensor_shape, request.tensor_dtype);
  const auto out = tensor_bytes(request.expected_output_shape, request.expected_output_dtype);
  if (!in || !out || *in > maximum || *out > maximum || *in != request.buffer_size) return "TENSOR_SIZE";
  if (request.buffer_ownership != "TRANSFERRED_HOST") return "BUFFER_OWNERSHIP";
  if (request.buffer_stride != contiguous_strides(request.tensor_shape, request.tensor_dtype)) return "BUFFER_STRIDE";
  if (format_dtype(request.expected_output_format) != request.expected_output_dtype ||
      !shape_matches(request.expected_output_shape, request.expected_output_layout, request.expected_output_extent,
                     channels(request.expected_output_format))) return "OUTPUT_SIGNATURE";
  const auto input = input_extent(request);
  if (!shape_matches(request.tensor_shape, request.tensor_layout, input, channel_count)) return "INPUT_SIGNATURE";
  if (request.deadline <= request.submit_timestamp) return "DEADLINE";
  if (request.tile) {
    const auto& t = *request.tile;
    if (!t.core_width || !t.core_height || !t.output_width || !t.output_height ||
        std::uint64_t(t.source_x) + t.core_width > request.source_extent.width ||
        std::uint64_t(t.source_y) + t.core_height > request.source_extent.height ||
        std::uint64_t(t.core_width) + t.halo_left + t.halo_right > input.width ||
        std::uint64_t(t.core_height) + t.halo_top + t.halo_bottom > input.height ||
        t.output_width > request.expected_output_extent.width || t.output_height > request.expected_output_extent.height ||
        std::uint64_t(t.output_x) + t.output_width > 8192 || std::uint64_t(t.output_y) + t.output_height > 8192)
      return "TILE_PLACEMENT";
  } else if (input != request.source_extent) return "SOURCE_TENSOR_EXTENT";
  return {};
}

Result failure(const Request& request, std::string_view backend, std::string_view evidence,
               std::string_view reason, Nanoseconds completed_at) {
  Result result;
  result.schema_version = request.schema_version;
  result.session_id = request.session_id;
  result.frame_id = request.frame_id;
  result.configuration_generation = request.configuration_generation;
  result.model_id = request.model_id;
  result.model_sha256 = request.model_sha256;
  result.trace_id = request.trace_id;
  result.output_extent = request.expected_output_extent;
  result.output_format = request.expected_output_format;
  result.output_dtype = request.expected_output_dtype;
  result.output_layout = request.expected_output_layout;
  result.output_shape = request.expected_output_shape;
  result.backend_kind = backend;
  result.evidence_class = evidence;
  result.completion_timestamp = completed_at;
  result.fallback_reason = reason;
  initialize_logical_ledger(request, result);
  return result;
}

CpuReferenceBackend::CpuReferenceBackend(Executor executor) : executor_(std::move(executor)) {}

Result CpuReferenceBackend::execute(const Request& request, std::span<const std::uint8_t> input) {
  if (!executor_) return failure(request, kind(), "NOT_RUN", "CPU_EXECUTOR_UNAVAILABLE", request.submit_timestamp);
  Result result;
  try { result = executor_(request, input); }
  catch (const std::exception&) { return failure(request, kind(), "NOT_RUN", "CPU_EXECUTOR_FAILED", request.submit_timestamp); }
  catch (...) { return failure(request, kind(), "NOT_RUN", "CPU_EXECUTOR_FAILED", request.submit_timestamp); }
  if (result.backend_kind != kind() || !evidence_matches(result) || !identity_matches(request, result))
    return failure(request, kind(), "NOT_RUN", "CPU_RECEIPT_MISMATCH", result.completion_timestamp);
  return result;
}

Result UnavailableBackend::execute(const Request& request, std::span<const std::uint8_t>) {
  return failure(request, kind(), "NOT_RUN", "BACKEND_UNAVAILABLE", request.submit_timestamp);
}

Result DeterministicMockBackend::execute(const Request& request, std::span<const std::uint8_t> input) {
  auto result = failure(request, kind(), "SIMULATED", {}, request.submit_timestamp);
  const auto bytes = tensor_bytes(request.expected_output_shape, request.expected_output_dtype);
  if (!validate_request(request, kMaximumTensorBytes).empty() || input.size() != request.buffer_size ||
      !bytes || !add(request.submit_timestamp, duration_, result.completion_timestamp)) {
    result.fallback_reason = "MOCK_INVALID_REQUEST";
    return result;
  }
  result.valid = true;
  result.output.resize(*bytes);
  if (request.expected_output_dtype == "float32") {
    for (std::size_t i = 0; i < result.output.size(); i += sizeof(float)) {
      const float value = float(((i / sizeof(float)) % 251 + request.frame_id % 251) % 251) / 256.0f;
      std::memcpy(result.output.data() + i, &value, sizeof(value));
    }
  } else {
    for (std::size_t i = 0; i < result.output.size(); ++i)
      result.output[i] = std::uint8_t((i % 251 + request.frame_id % 251) % 251);
  }
  result.logical_bytes = request.buffer_size + *bytes;
  result.inference_duration = duration_;
  result.ledger.timing_class = "SIMULATED";
  return result;
}

Worker::Worker(std::string session, std::uint64_t generation, Limits limits)
    : session_id_(std::move(session)), generation_(generation), limits_(limits),
      scheduler_(limits.max_in_flight), entries_(limits.max_in_flight) {
  if (!identifier(session_id_) || !generation_ || !limits.max_queue_bytes || !limits.max_result_bytes ||
      !limits.max_tensor_bytes || limits.max_tensor_bytes > kMaximumTensorBytes)
    throw std::invalid_argument("invalid worker identity or byte limits");
}

Worker::Entry* Worker::find(Ticket ticket) {
  if (ticket.slot >= entries_.size() || !entries_[ticket.slot] || entries_[ticket.slot]->ticket != ticket) return nullptr;
  return &*entries_[ticket.slot];
}

void Worker::observe_allocation() {
  high_water_bytes_ = std::max(high_water_bytes_, input_owned_bytes_ + result_owned_bytes_);
}

void Worker::erase(std::size_t slot) {
  auto& entry = *entries_[slot];
  input_owned_bytes_ -= entry.input.capacity();
  reserved_result_bytes_ -= entry.output_reservation;
  if (entry.result) result_owned_bytes_ -= entry.result->output.capacity();
  entries_[slot].reset();
}

void Worker::fallback(Entry& entry, std::string_view reason) {
  if (!entry.fallback_reported) { ++counts_.fallback_count; entry.fallback_reported = true; }
  if (entry.result) {
    entry.result->valid = false;
    entry.result->fallback_reason = reason;
    entry.result->ledger.deadline_missed = now_ >= entry.request.deadline;
  }
  last_error_ = reason;
}

bool Worker::reject_event(std::string_view reason) {
  ++counts_.stale_events;
  last_error_ = reason;
  return false;
}

bool Worker::advance(Nanoseconds now) {
  if (now < now_) return reject_event("CLOCK_REVERSED");
  now_ = now;
  scheduler_.advance_to(now);
  for (std::size_t i = 0; i < entries_.size(); ++i) {
    if (!entries_[i]) continue;
    auto& entry = *entries_[i];
    if (now < entry.request.deadline && !entry.invalidated) continue;
    fallback(entry, entry.invalidated ? "CONFIGURATION_INVALIDATED" : "DEADLINE_MISSED");
    if (entry.phase == Phase::Queued) {
      scheduler_.acknowledge_unstarted_cancel(entry.ticket, now);
      ++counts_.discarded;
      erase(i);
    } else if (entry.phase == Phase::Ready) {
      scheduler_.release_output(entry.ticket, now);
      ++counts_.discarded;
      erase(i);
    }
    // A timeout never releases running or consumer-owned buffers.
  }
  return true;
}

Submission Worker::submit(Request request, std::vector<std::uint8_t> input, Nanoseconds now) {
  auto reject = [&](std::string_view reason) {
    ++counts_.rejected;
    last_error_ = reason;
    return Submission{false, {}, std::string(reason)};
  };
  if (!advance(now)) return reject("CLOCK_REVERSED");
  if (shutting_down_) return reject("WORKER_SHUTTING_DOWN");
  if (const auto reason = validate_request(request, limits_.max_tensor_bytes); !reason.empty()) return reject(reason);
  if (request.session_id != session_id_ || request.configuration_generation != generation_) return reject("SESSION_OR_GENERATION_MISMATCH");
  if (request.frame_id <= last_frame_id_) return reject("FRAME_ID_NOT_INCREASING");
  if (request.submit_timestamp > now || request.deadline <= now) return reject("DEADLINE_OR_SUBMIT_TIME");
  if (input.size() != request.buffer_size || input.capacity() > limits_.max_tensor_bytes) return reject("INPUT_BUFFER_SIZE");
  if (!finite_buffer(input, request.tensor_dtype)) return reject("NONFINITE_INPUT");
  const auto output = *tensor_bytes(request.expected_output_shape, request.expected_output_dtype);
  if (input.capacity() > limits_.max_queue_bytes - std::min(input_owned_bytes_, limits_.max_queue_bytes)) return reject("QUEUE_BYTE_LIMIT");
  if (output > limits_.max_result_bytes - std::min(reserved_result_bytes_, limits_.max_result_bytes)) return reject("RESULT_BYTE_LIMIT");
  const auto submitted = scheduler_.submit(request.frame_id, now, request.deadline);
  if (!submitted.ticket) return reject("IN_FLIGHT_LIMIT");
  const auto ticket = *submitted.ticket;
  input_owned_bytes_ += input.capacity();
  reserved_result_bytes_ += output;
  last_frame_id_ = request.frame_id;
  entries_[ticket.slot] = Entry{std::move(request), std::move(input), {}, ticket, output};
  ++counts_.submitted;
  observe_allocation();
  return {true, ticket, {}};
}

std::optional<WorkItem> Worker::start_next(Nanoseconds now) {
  if (!advance(now) || shutting_down_) return {};
  Entry* next = nullptr;
  for (auto& value : entries_) {
    if (value && value->phase == Phase::Queued && !value->invalidated &&
        (!next || value->ticket.serial < next->ticket.serial)) next = &*value;
  }
  if (!next) return {};
  next->phase = Phase::Running;
  next->started_at = now;
  return WorkItem{next->ticket, &next->request, next->input};
}

bool Worker::complete(Ticket ticket, Result result, Nanoseconds now) {
  if (!advance(now)) return false;
  auto* entry = find(ticket);
  if (!entry || entry->phase != Phase::Running) return reject_event("STALE_OR_DUPLICATE_COMPLETION");
  // This call acknowledges that the producer for this exact trusted ticket has
  // stopped touching its input. Invalid output is discarded, never consumed.
  ++counts_.completed;
  std::string reason;
  if (!identity_matches(entry->request, result)) reason = "RESULT_IDENTITY_MISMATCH";
  else if (!evidence_matches(result)) reason = "BACKEND_EVIDENCE_MISMATCH";
  else if (result.completion_timestamp < entry->request.submit_timestamp || result.completion_timestamp > now) reason = "RESULT_TIMESTAMP";
  else if (!result.valid) reason = identifier(result.fallback_reason) ? result.fallback_reason : "BACKEND_FAILED";
  else if (result.completion_timestamp < entry->started_at) reason = "RESULT_TIMESTAMP";
  else if (!result.fallback_reason.empty()) reason = "VALID_RESULT_HAS_FALLBACK";
  else if (result.output_extent != entry->request.expected_output_extent || result.output_format != entry->request.expected_output_format ||
           result.output_shape != entry->request.expected_output_shape || result.output_dtype != entry->request.expected_output_dtype ||
           result.output_layout != entry->request.expected_output_layout || result.output.size() != entry->output_reservation ||
           result.output.capacity() > entry->output_reservation) reason = "RESULT_SIGNATURE_OR_SIZE";
  else if (!finite_buffer(result.output, result.output_dtype)) reason = "NONFINITE_OUTPUT";
  else if (!ledger_matches(entry->request, result)) reason = "RESULT_LEDGER";
  else if (*result.inference_duration > result.completion_timestamp - entry->started_at) reason = "INFERENCE_DURATION";
  else if (entry->invalidated || entry->request.configuration_generation != generation_) reason = "CONFIGURATION_INVALIDATED";
  else if (now >= entry->request.deadline) reason = "DEADLINE_MISSED";
  const auto completed = scheduler_.complete(ticket, now);
  if (!reason.empty() || completed != core::FrameDecision::OutputReady) {
    fallback(*entry, reason.empty() ? "STALE_RESULT" : reason);
    if (completed == core::FrameDecision::OutputReady) scheduler_.release_output(ticket, now);
    ++counts_.discarded;
    erase(ticket.slot);
    return false;
  }
  result.ledger.submit_to_complete_duration = result.completion_timestamp - entry->request.submit_timestamp;
  result.ledger.complete_to_consume_duration.reset();
  result.ledger.deadline_missed = false;
  result_owned_bytes_ += result.output.capacity();
  observe_allocation();
  result.ledger.allocation_high_water_bytes = std::max(result.ledger.allocation_high_water_bytes, high_water_bytes_);
  entry->result = std::move(result);
  entry->phase = Phase::Ready;
  return true;
}

const Result* Worker::consume(Ticket ticket, std::string_view session, std::uint64_t frame,
                              std::uint64_t generation, Nanoseconds now) {
  if (!advance(now)) return nullptr;
  auto* entry = find(ticket);
  if (!entry || entry->phase != Phase::Ready || session != session_id_ || frame != entry->request.frame_id ||
      generation != generation_ || generation != entry->request.configuration_generation) {
    reject_event("CONSUMER_IDENTITY_OR_STATE");
    return nullptr;
  }
  if (scheduler_.consume_output(ticket, now) != core::FrameDecision::OutputConsumed) {
    reject_event("CONSUMER_STALE_RESULT");
    return nullptr;
  }
  entry->phase = Phase::Consuming;
  ++counts_.consumed;
  entry->result->ledger.complete_to_consume_duration = now - entry->result->completion_timestamp;
  return &*entry->result;
}

bool Worker::release(Ticket ticket, Nanoseconds now) {
  if (!advance(now)) return false;
  auto* entry = find(ticket);
  if (!entry || (entry->phase != Phase::Ready && entry->phase != Phase::Consuming))
    return reject_event("RELEASE_WITHOUT_COMPLETION");
  if (scheduler_.release_output(ticket, now) != core::FrameDecision::OutputReleased)
    return reject_event("RELEASE_REJECTED");
  ++counts_.released;
  erase(ticket.slot);
  return true;
}

bool Worker::invalidate(std::uint64_t generation, Nanoseconds now) {
  if (!advance(now) || shutting_down_ || generation <= generation_) return reject_event("INVALID_CONFIGURATION_GENERATION");
  generation_ = generation;
  scheduler_.resize(now);
  for (auto& entry : entries_) if (entry) entry->invalidated = true;
  return advance(now);
}

bool Worker::shutdown(Nanoseconds now) {
  if (!advance(now)) return false;
  if (!shutting_down_) {
    shutting_down_ = true;
    scheduler_.suspend(now);
    for (auto& entry : entries_) if (entry) entry->invalidated = true;
  }
  return advance(now);
}

bool Worker::acknowledge_quiescence(Nanoseconds now) {
  if (!advance(now) || !shutting_down_) return reject_event("QUIESCENCE_REQUIRES_SHUTDOWN");
  // Trusted caller acknowledgement that EVERY backend and consumer stopped.
  if (!scheduler_.acknowledge_quiescence(now)) return false;
  for (std::size_t i = 0; i < entries_.size(); ++i) if (entries_[i]) erase(i);
  return true;
}

std::string ledger_json(const Ledger& l) {
  std::ostringstream s;
  s << std::boolalpha << "{\"source_logical_bytes\":" << l.source_logical_bytes
    << ",\"tensor_preparation_read_bytes\":" << l.tensor_preparation_read_bytes
    << ",\"tensor_preparation_write_bytes\":" << l.tensor_preparation_write_bytes
    << ",\"host_copy_bytes\":" << l.host_copy_bytes << ",\"host_copy_count\":" << l.host_copy_count
    << ",\"host_copy_direction\":" << core::json_string(l.host_copy_direction)
    << ",\"host_copy_scope\":" << core::json_string(l.host_copy_scope)
    << ",\"inference_input_logical_bytes\":" << l.inference_input_logical_bytes
    << ",\"inference_output_logical_bytes\":" << l.inference_output_logical_bytes
    << ",\"tile_count\":" << l.tile_count << ",\"tile_overlap_pixels\":" << l.tile_overlap_pixels
    << ",\"stitched_output_bytes\":" << l.stitched_output_bytes << ",\"crop_bytes\":" << l.crop_bytes
    << ",\"gpu_upload_bytes\":" << optional_number(l.gpu_upload_bytes)
    << ",\"allocation_high_water_bytes\":" << l.allocation_high_water_bytes
    << ",\"submit_to_complete_duration\":" << optional_number(l.submit_to_complete_duration)
    << ",\"complete_to_consume_duration\":" << optional_number(l.complete_to_consume_duration)
    << ",\"deadline_missed\":" << l.deadline_missed << ",\"duration_unit\":\"nanoseconds\""
    << ",\"timing_class\":" << core::json_string(l.timing_class)
    << ",\"runtime_internal_allocation_status\":" << core::json_string(l.runtime_internal_allocation_status)
    << ",\"runtime_internal_copy_status\":" << core::json_string(l.runtime_internal_copy_status)
    << ",\"physical_ddr_traffic\":null}";
  return s.str();
}

std::string request_json(const Request& r) {
  std::ostringstream s;
  s << "{\"schema_version\":" << core::json_string(r.schema_version) << ",\"document_type\":\"docksr_inference_request\""
    << ",\"session_id\":" << core::json_string(r.session_id) << ",\"frame_id\":" << r.frame_id
    << ",\"configuration_generation\":" << r.configuration_generation
    << ",\"model_id\":" << core::json_string(r.model_id) << ",\"model_sha256\":" << core::json_string(r.model_sha256)
    << ",\"source_extent\":" << extent_json(r.source_extent) << ",\"source_format\":" << core::json_string(r.source_format)
    << ",\"tensor_shape\":" << numbers(r.tensor_shape) << ",\"tensor_dtype\":" << core::json_string(r.tensor_dtype)
    << ",\"tensor_layout\":" << core::json_string(r.tensor_layout) << ",\"buffer_size\":" << r.buffer_size
    << ",\"buffer_stride\":" << numbers(r.buffer_stride) << ",\"buffer_ownership\":" << core::json_string(r.buffer_ownership)
    << ",\"submit_timestamp\":" << r.submit_timestamp << ",\"deadline\":" << r.deadline
    << ",\"clock_domain\":\"shared_monotonic_nanoseconds\",\"trace_id\":" << core::json_string(r.trace_id)
    << ",\"expected_output_extent\":" << extent_json(r.expected_output_extent)
    << ",\"expected_output_format\":" << core::json_string(r.expected_output_format)
    << ",\"expected_output_shape\":" << numbers(r.expected_output_shape)
    << ",\"expected_output_dtype\":" << core::json_string(r.expected_output_dtype)
    << ",\"expected_output_layout\":" << core::json_string(r.expected_output_layout) << ",\"tile\":";
  if (!r.tile) s << "null";
  else {
    const auto& t = *r.tile;
    s << "{\"source_x\":" << t.source_x << ",\"source_y\":" << t.source_y
      << ",\"core_width\":" << t.core_width << ",\"core_height\":" << t.core_height
      << ",\"halo_left\":" << t.halo_left << ",\"halo_top\":" << t.halo_top
      << ",\"halo_right\":" << t.halo_right << ",\"halo_bottom\":" << t.halo_bottom
      << ",\"output_x\":" << t.output_x << ",\"output_y\":" << t.output_y
      << ",\"output_width\":" << t.output_width << ",\"output_height\":" << t.output_height << '}';
  }
  return s.str() + '}';
}

std::string result_json(const Result& r) {
  std::ostringstream s;
  s << std::boolalpha << "{\"schema_version\":" << core::json_string(r.schema_version)
    << ",\"document_type\":\"docksr_inference_result\",\"session_id\":" << core::json_string(r.session_id)
    << ",\"frame_id\":" << r.frame_id << ",\"configuration_generation\":" << r.configuration_generation
    << ",\"model_id\":" << core::json_string(r.model_id) << ",\"model_sha256\":" << core::json_string(r.model_sha256)
    << ",\"trace_id\":" << core::json_string(r.trace_id) << ",\"output_extent\":" << extent_json(r.output_extent)
    << ",\"output_format\":" << core::json_string(r.output_format) << ",\"output_dtype\":" << core::json_string(r.output_dtype)
    << ",\"output_layout\":" << core::json_string(r.output_layout) << ",\"output_shape\":" << numbers(r.output_shape)
    << ",\"backend_kind\":" << core::json_string(r.backend_kind) << ",\"evidence_class\":" << core::json_string(r.evidence_class)
    << ",\"valid\":" << r.valid << ",\"completion_timestamp\":" << r.completion_timestamp
    << ",\"copy_count\":" << r.copy_count << ",\"logical_bytes\":" << r.logical_bytes
    << ",\"inference_duration\":" << optional_number(r.inference_duration) << ",\"duration_unit\":\"nanoseconds\""
    << ",\"output_buffer_size\":" << r.output.size() << ",\"fallback_reason\":";
  if (r.fallback_reason.empty()) s << "null"; else s << core::json_string(r.fallback_reason);
  s << ",\"ledger\":" << ledger_json(r.ledger)
    << ",\"presented\":false,\"npu_device_detected\":false,\"npu_runtime_ready\":false,"
       "\"npu_inference_verified\":false,\"npu_game_frames_consumed\":false}";
  return s.str();
}

std::string future_backends_json() {
  return "{\"schema_version\":\"1.0.0\",\"document_type\":\"docksr_future_backends\","
    "\"backends\":[{\"name\":\"VitisAiNpuBackend\",\"status\":\"NOT_IMPLEMENTED\",\"evidence\":\"NOT_RUN\"},"
    "{\"name\":\"FutureXrtBackend\",\"status\":\"NOT_IMPLEMENTED\",\"evidence\":\"NOT_RUN\"}],"
    "\"npu_inference_verified\":false,\"npu_game_frames_consumed\":false}";
}
}  // namespace docksr::inference

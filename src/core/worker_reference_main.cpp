// One-job POSIX host bridge; no public IPC service, graphics or NPU backend.
#include "docksr/core/inference_worker.hpp"
#include "docksr/core/json.hpp"

#include <algorithm>
#include <charconv>
#include <chrono>
#include <cerrno>
#include <csignal>
#include <cstdint>
#include <fcntl.h>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <limits>
#include <map>
#include <span>
#include <stdexcept>
#include <string>
#include <sys/stat.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <thread>
#include <unistd.h>
#include <vector>

namespace fs = std::filesystem;
namespace inf = docksr::inference;
namespace {
constexpr std::uint64_t kLimit = 64u * 1024u * 1024u;
using Clock = std::chrono::steady_clock;

std::uint64_t now() {
  return static_cast<std::uint64_t>(std::chrono::duration_cast<std::chrono::nanoseconds>(Clock::now().time_since_epoch()).count());
}
std::uint64_t number(std::string_view text) {
  std::uint64_t value{};
  auto [end, error] = std::from_chars(text.data(), text.data() + text.size(), value);
  if (error != std::errc{} || end != text.data() + text.size() || text.empty())
    throw std::runtime_error("invalid unsigned integer");
  return value;
}
bool identifier(std::string_view value) {
  return !value.empty() && value.size() <= 128 && std::all_of(value.begin(), value.end(), [](char c) {
    return (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') ||
           (c >= '0' && c <= '9') || c == '_' || c == '-' || c == '.' || c == ':';
  });
}
bool hex(std::string_view text, std::size_t length) {
  return text.size() == length && std::all_of(text.begin(), text.end(), [](char c) {
    return (c >= '0' && c <= '9') || (c >= 'a' && c <= 'f');
  });
}
std::string join(std::span<const std::uint64_t> shape) {
  std::string result;
  for (auto dimension : shape) { if (!result.empty()) result += ','; result += std::to_string(dimension); }
  return result;
}
std::vector<std::uint64_t> shape(std::string_view text) {
  std::vector<std::uint64_t> result;
  while (true) {
    const auto comma = text.find(',');
    result.push_back(number(text.substr(0, comma)));
    if (result.size() > 4) throw std::runtime_error("rank-four tensors only");
    if (comma == std::string_view::npos) break;
    text.remove_prefix(comma + 1);
  }
  if (result.size() != 4) throw std::runtime_error("rank-four tensors only");
  return result;
}
std::string fingerprint(std::span<const std::uint8_t> data) {
  std::uint64_t value = 14695981039346656037ull;
  for (auto byte : data) { value ^= byte; value *= 1099511628211ull; }
  char result[16];
  constexpr char digits[] = "0123456789abcdef";
  for (int index = 15; index >= 0; --index) { result[index] = digits[value & 15]; value >>= 4; }
  return std::string(result, sizeof result);
}
std::vector<std::uint8_t> read_file(const fs::path& path, std::uint64_t limit) {
  const int descriptor = open(path.c_str(), O_RDONLY | O_NOFOLLOW | O_CLOEXEC | O_NONBLOCK);
  if (descriptor < 0) throw std::runtime_error("cannot open regular bridge file");
  struct stat info{};
  if (fstat(descriptor, &info) || !S_ISREG(info.st_mode) || info.st_size < 0 ||
      static_cast<std::uint64_t>(info.st_size) > limit) {
    close(descriptor); throw std::runtime_error("unsafe or oversized bridge file");
  }
  std::vector<std::uint8_t> bytes(static_cast<std::size_t>(info.st_size));
  std::size_t offset{};
  while (offset < bytes.size()) {
    const auto count = read(descriptor, bytes.data() + offset, bytes.size() - offset);
    if (count <= 0) { close(descriptor); throw std::runtime_error("short bridge read"); }
    offset += static_cast<std::size_t>(count);
  }
  std::uint8_t extra{};
  const auto count = read(descriptor, &extra, 1);
  close(descriptor);
  if (count != 0) throw std::runtime_error("bridge file changed during read");
  return bytes;
}
void write_file(const fs::path& path, std::span<const std::uint8_t> bytes) {
  const int descriptor = open(path.c_str(), O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW | O_CLOEXEC, 0600);
  if (descriptor < 0) throw std::runtime_error("refusing existing bridge output");
  std::size_t offset{};
  while (offset < bytes.size()) {
    const auto count = write(descriptor, bytes.data() + offset, bytes.size() - offset);
    if (count <= 0) { close(descriptor); throw std::runtime_error("bridge write failed"); }
    offset += static_cast<std::size_t>(count);
  }
  close(descriptor);
}
void write_text(const fs::path& path, std::string_view text) {
  write_file(path, {reinterpret_cast<const std::uint8_t*>(text.data()), text.size()});
}
void private_directory(const fs::path& path) {
  if (path.empty() || !path.is_absolute() || !fs::is_directory(path.parent_path()))
    throw std::runtime_error("work directory requires an existing absolute parent");
  for (fs::path ancestor = path; !ancestor.empty();) {
    if (ancestor.filename() == ".git" || fs::is_symlink(fs::symlink_status(ancestor)))
      throw std::runtime_error("symlink or Git work directory refused");
    const auto marker = ancestor / ".git";
    if (fs::is_regular_file(marker) || (fs::is_directory(marker) && !fs::is_empty(marker)))
      throw std::runtime_error("work directory must remain outside every Git checkout");
    if (ancestor == ancestor.root_path()) break;
    ancestor = ancestor.parent_path();
  }
  struct stat parent{};
  if (stat(path.parent_path().c_str(), &parent) || parent.st_uid != getuid() || (parent.st_mode & 0022))
    throw std::runtime_error("work directory parent is not controlled by this user");
  if (mkdir(path.c_str(), 0700)) throw std::runtime_error("work directory must be new");
}
struct ProcessResult { bool started{}, stopped{}, success{}, timed_out{}; };
ProcessResult execute_child(const std::vector<std::string>& arguments, const fs::path& log,
                            std::uint64_t timeout_ms, std::uint64_t request_deadline) {
  const auto deadline = std::min<std::uint64_t>(now() + timeout_ms * 1000000ull, request_deadline);
  if (now() >= deadline) return {false, true, false, true};
  const int descriptor = open(log.c_str(), O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW | O_CLOEXEC, 0600);
  if (descriptor < 0) throw std::runtime_error("cannot create child log");
  const pid_t pid = fork();
  if (pid < 0) { close(descriptor); throw std::runtime_error("fork failed"); }
  if (pid == 0) {
    if (setpgid(0, 0) || dup2(descriptor, STDOUT_FILENO) < 0 || dup2(descriptor, STDERR_FILENO) < 0) _exit(126);
    close(descriptor);
    std::vector<char*> argv;
    for (const auto& argument : arguments) argv.push_back(const_cast<char*>(argument.c_str()));
    argv.push_back(nullptr);
    execv(argv.front(), argv.data());
    _exit(127);
  }
  close(descriptor);
  // Parent and child both request the dedicated process group, closing the
  // normal setup race before any timeout-driven group signal.
  setpgid(pid, pid);
  int status{};
  while (true) {
    const auto waited = waitpid(pid, &status, WNOHANG);
    if (waited == pid) return {true, true, WIFEXITED(status) && WEXITSTATUS(status) == 0, false};
    if (waited < 0 && errno == EINTR) continue;
    if (waited < 0) {
      kill(-pid, SIGKILL);
      pid_t acknowledged;
      do { acknowledged = waitpid(pid, &status, 0); } while (acknowledged < 0 && errno == EINTR);
      return {true, acknowledged == pid || (acknowledged < 0 && errno == ECHILD), false, false};
    }
    if (now() >= deadline) break;
    std::this_thread::sleep_for(std::chrono::milliseconds(5));
  }
  kill(-pid, SIGTERM);
  const auto grace = Clock::now() + std::chrono::milliseconds(100);
  while (Clock::now() < grace) {
    const auto waited = waitpid(pid, &status, WNOHANG);
    if (waited == pid) { kill(-pid, SIGKILL); return {true, true, false, true}; }
    if (waited < 0 && errno == EINTR) continue;
    if (waited < 0) break;
    std::this_thread::sleep_for(std::chrono::milliseconds(5));
  }
  kill(-pid, SIGKILL);
  while (waitpid(pid, &status, 0) < 0) {
    if (errno == ECHILD) return {true, true, false, true};
    if (errno != EINTR) return {true, false, false, true};
  }
  return {true, true, false, true};
}
std::vector<std::string> lines(std::span<const std::uint8_t> bytes) {
  std::vector<std::string> result;
  std::string current;
  for (auto byte : bytes) {
    if (byte == '\n') { result.push_back(current); current.clear(); }
    else if (byte >= 32 && byte <= 126) current += static_cast<char>(byte);
    else throw std::runtime_error("invalid receipt encoding");
  }
  if (!current.empty()) throw std::runtime_error("receipt lacks final newline");
  return result;
}
std::string format(std::string_view dtype, std::uint64_t channels) {
  std::string result = channels == 4 ? "RGBA" : "RGB";
  if (dtype == "uint8") return result + "8";
  if (dtype == "int8") return result + "_INT8";
  if (dtype == "float32") return result + "_FLOAT32";
  throw std::runtime_error("unsupported bridge dtype");
}
}  // namespace

int main(int argc, char** argv) {
  try {
    std::map<std::string, std::string> args;
    const std::vector<std::string> allowed{"--python", "--executor", "--model", "--model-sha256", "--input", "--input-shape", "--output-shape", "--dtype", "--output-dtype", "--layout", "--work-dir", "--timeout-ms", "--deadline-ms", "--session-id", "--frame-id", "--generation", "--trace-id", "--model-id"};
    for (int index = 1; index < argc; index += 2) {
      const std::string name = argv[index];
      if (std::find(allowed.begin(), allowed.end(), name) == allowed.end() || index + 1 >= argc || args.contains(name))
        throw std::runtime_error("unknown, duplicate or incomplete argument");
      args[name] = argv[index + 1];
    }
    auto required = [&](std::string name) {
      if (!args.contains(name) || args[name].empty()) throw std::runtime_error("missing required argument: " + name);
      return args[name];
    };
    auto optional = [&](std::string name, std::string fallback) { return args.contains(name) ? args[name] : fallback; };
    const fs::path python = fs::absolute(required("--python"));
    const fs::path executor = fs::absolute(required("--executor"));
    const fs::path model = fs::absolute(required("--model"));
    const fs::path work = required("--work-dir");
    const auto timeout_ms = number(optional("--timeout-ms", "30000"));
    const auto deadline_ms = number(optional("--deadline-ms", "30000"));
    if (!timeout_ms || timeout_ms > 120000 || !deadline_ms || deadline_ms > 120000)
      throw std::runtime_error("timeout and deadline must be1..120000ms");
    inf::Request request;
    request.session_id = optional("--session-id", "worker-reference");
    request.frame_id = number(optional("--frame-id", "1"));
    request.configuration_generation = number(optional("--generation", "1"));
    request.model_id = optional("--model-id", "owned-host-contract");
    request.model_sha256 = required("--model-sha256");
    request.trace_id = optional("--trace-id", "cpu-bridge-1");
    if (!identifier(request.session_id) || !identifier(request.model_id) || !identifier(request.trace_id) || !hex(request.model_sha256, 64))
      throw std::runtime_error("invalid identity or model SHA256");
    request.tensor_shape = shape(required("--input-shape"));
    request.expected_output_shape = shape(required("--output-shape"));
    request.tensor_dtype = required("--dtype");
    request.expected_output_dtype = optional("--output-dtype", request.tensor_dtype);
    request.tensor_layout = request.expected_output_layout = required("--layout");
    if (request.tensor_layout != "NCHW" && request.tensor_layout != "NHWC") throw std::runtime_error("invalid layout");
    const auto channel_axis = request.tensor_layout == "NCHW" ? 1u : 3u;
    const auto height_axis = request.tensor_layout == "NCHW" ? 2u : 1u;
    const auto width_axis = request.tensor_layout == "NCHW" ? 3u : 2u;
    request.source_format = format(request.tensor_dtype, request.tensor_shape[channel_axis]);
    request.expected_output_format = format(request.expected_output_dtype, request.expected_output_shape[channel_axis]);
    request.source_extent = {static_cast<std::uint32_t>(request.tensor_shape[width_axis]), static_cast<std::uint32_t>(request.tensor_shape[height_axis])};
    request.expected_output_extent = {static_cast<std::uint32_t>(request.expected_output_shape[width_axis]), static_cast<std::uint32_t>(request.expected_output_shape[height_axis])};
    const auto input_bytes = inf::tensor_bytes(request.tensor_shape, request.tensor_dtype);
    const auto output_bytes = inf::tensor_bytes(request.expected_output_shape, request.expected_output_dtype);
    if (!input_bytes || !output_bytes || std::max(*input_bytes, *output_bytes) > kLimit) throw std::runtime_error("tensor bound exceeded");
    request.buffer_size = *input_bytes;
    request.buffer_stride = inf::contiguous_strides(request.tensor_shape, request.tensor_dtype);
    request.submit_timestamp = now();
    request.deadline = request.submit_timestamp + deadline_ms * 1000000ull;
    const auto validation = inf::validate_request(request, kLimit);
    if (!validation.empty()) throw std::runtime_error(validation);
    auto input = read_file(required("--input"), kLimit);
    if (input.size() != *input_bytes) throw std::runtime_error("input file byte count differs from tensor");
    private_directory(work);
    inf::Worker worker(request.session_id, request.configuration_generation);
    auto submission = worker.submit(request, std::move(input), now());
    if (!submission.accepted) throw std::runtime_error("request rejected: " + submission.reason);
    auto item = worker.start_next(now());
    if (!item) throw std::runtime_error("request did not start");
    bool child_started = false, child_stopped = false, child_timed_out = false;
    std::string actual_output_sha, native_error_detail;
    inf::CpuReferenceBackend backend([&](const inf::Request& current, std::span<const std::uint8_t> tensor) {
      std::uint64_t completed_native_transfers{}, completed_native_bytes{};
      auto failed = [&](std::string_view reason) {
        const auto code = identifier(reason) ? reason : std::string_view("CPU_BRIDGE_IO_OR_RECEIPT_ERROR");
        if (code != reason) native_error_detail = std::string(reason.substr(0, 256));
        auto result = inf::failure(current, "CPU_REFERENCE", "NOT_RUN", code, now());
        result.copy_count = completed_native_transfers;
        result.ledger.host_copy_count = completed_native_transfers;
        result.ledger.host_copy_bytes = completed_native_bytes;
        result.ledger.host_copy_direction = completed_native_transfers ? "HOST_FILE_STAGING" : "NONE";
        result.ledger.host_copy_scope = "COMPLETED_NATIVE_FILE_TRANSFERS_ONLY_CHILD_TRANSFERS_UNKNOWN";
        result.ledger.source_logical_bytes = *input_bytes;
        result.ledger.submit_to_complete_duration = result.completion_timestamp - current.submit_timestamp;
        result.ledger.deadline_missed = result.completion_timestamp >= current.deadline;
        return result;
      };
      try {
        const auto input_fingerprint = fingerprint(tensor);
        write_file(work / "input.raw", tensor);
        ++completed_native_transfers;
        completed_native_bytes += tensor.size();
        const std::string metadata = "DOCKSR_CPU_REQUEST_V1\n" + current.session_id + "\n" +
            std::to_string(current.frame_id) + "\n" + std::to_string(current.configuration_generation) + "\n" +
            current.model_id + "\n" + current.model_sha256 + "\n" + current.trace_id + "\n" +
            current.tensor_dtype + "\n" + current.tensor_layout + "\n" + join(current.tensor_shape) + "\n" +
            current.expected_output_dtype + "\n" + join(current.expected_output_shape) + "\n" +
            std::to_string(tensor.size()) + "\n" + input_fingerprint + "\n";
        write_text(work / "request.txt", metadata);
        const auto process = execute_child({python.string(), "-I", executor.string(), "--model", model.string(), "--request", (work / "request.txt").string()}, work / "child.log", timeout_ms, current.deadline);
        child_started = process.started;
        child_stopped = process.stopped;
        child_timed_out = process.timed_out;
        if (!process.success) return failed(process.timed_out ? "CPU_PROCESS_TIMEOUT" : "CPU_PROCESS_FAILED");
        const auto receipt = lines(read_file(work / "receipt.txt", 4096));
        if (receipt.size() != 21 || receipt[0] != "DOCKSR_CPU_RESULT_V1" || receipt[1] != current.session_id ||
            number(receipt[2]) != current.frame_id || number(receipt[3]) != current.configuration_generation ||
            receipt[4] != current.model_id || receipt[5] != current.model_sha256 || receipt[6] != current.trace_id ||
            receipt[7] != current.expected_output_dtype || receipt[8] != current.expected_output_layout ||
            receipt[9] != join(current.expected_output_shape) || number(receipt[10]) != *output_bytes ||
            receipt[11] != input_fingerprint || !hex(receipt[12], 16) || !hex(receipt[13], 64) ||
            number(receipt[14]) != 2 || receipt[19] != "REAL_CPU" || receipt[20] != "CPUExecutionProvider")
          throw std::runtime_error("CPU_RECEIPT_MISMATCH");
        auto output = read_file(work / "output.raw", *output_bytes);
        ++completed_native_transfers;
        completed_native_bytes += output.size();
        if (output.size() != *output_bytes || fingerprint(output) != receipt[12]) throw std::runtime_error("CPU_OUTPUT_MISMATCH");
        const auto initialization = number(receipt[15]);
        const auto inference = number(receipt[16]);
        const auto python_tensor_bytes = number(receipt[17]);
        const auto child_elapsed = number(receipt[18]);
        if (!inference || !initialization || child_elapsed < inference || python_tensor_bytes != *input_bytes + *output_bytes)
          throw std::runtime_error("CPU_TIMING_OR_ALLOCATION_MISMATCH");
        auto result = inf::failure(current, "CPU_REFERENCE", "REAL_CPU", "", now());
        result.output_extent = current.expected_output_extent;
        result.output_format = current.expected_output_format;
        result.output_dtype = current.expected_output_dtype;
        result.output_layout = current.expected_output_layout;
        result.output_shape = current.expected_output_shape;
        result.valid = true;
        result.copy_count = 4;
        result.logical_bytes = *input_bytes + *output_bytes;
        result.inference_duration = inference;
        result.output = std::move(output);
        auto& ledger = result.ledger;
        ledger.source_logical_bytes = *input_bytes;
        ledger.host_copy_count = 4;
        ledger.host_copy_bytes = 2 * (*input_bytes + *output_bytes);
        ledger.host_copy_direction = "HOST_FILE_STAGING";
        ledger.host_copy_scope = "FOUR_RAW_FILE_PAYLOAD_TRANSFERS_ONLY";
        ledger.inference_input_logical_bytes = 2 * *input_bytes;
        ledger.inference_output_logical_bytes = 2 * *output_bytes;
        ledger.tile_count = 1;
        ledger.allocation_high_water_bytes = *input_bytes + python_tensor_bytes;
        ledger.timing_class = "OBSERVED_HOST_CPU";
        actual_output_sha = receipt[13];
        return result;
      } catch (const std::exception& error) {
        return failed(error.what());
      }
    });
    auto result = backend.execute(*item->request, item->input);
    const bool backend_valid = result.valid;
    const auto backend_json = inf::result_json(result);
    const auto backend_evidence = result.evidence_class;
    const auto backend_completed_at = result.completion_timestamp;
    const auto backend_copy_count = result.copy_count;
    const auto backend_logical_bytes = result.logical_bytes;
    const auto backend_inference_duration = result.inference_duration;
    const auto backend_ledger = result.ledger;
    // Completion also acknowledges producer stop. Never issue it if a started
    // child could not be reaped; shutdown then retains the active entry.
    const bool completed = (!child_started || child_stopped) && worker.complete(item->ticket, std::move(result), now());
    const auto* consumed = completed ? worker.consume(item->ticket, request.session_id, request.frame_id, request.configuration_generation, now()) : nullptr;
    const bool consumed_valid = consumed && consumed->valid;
    std::string rejection_reason;
    if (!consumed_valid) {
      rejection_reason = child_started && !child_stopped ? "CPU_PROCESS_STOP_NOT_ACKNOWLEDGED" : worker.last_error();
      if (now() >= request.deadline) rejection_reason = "DEADLINE_MISSED";
      if (!identifier(rejection_reason)) rejection_reason = "WORKER_RESULT_REJECTED";
    }
    std::string result_json = consumed ? inf::result_json(*consumed) : backend_json;
    if (backend_valid && !consumed_valid) {
      // Preserve the actual CPU receipt separately, but report the effective
      // frame transaction as invalid when completion/consumption was rejected.
      auto effective = inf::failure(request, "CPU_REFERENCE", backend_evidence, rejection_reason, backend_completed_at);
      effective.copy_count = backend_copy_count;
      effective.logical_bytes = backend_logical_bytes;
      effective.inference_duration = backend_inference_duration;
      effective.ledger = backend_ledger;
      effective.ledger.submit_to_complete_duration = backend_completed_at - request.submit_timestamp;
      effective.ledger.complete_to_consume_duration.reset();
      effective.ledger.deadline_missed = now() >= request.deadline;
      result_json = inf::result_json(effective);
    }
    const bool released = consumed ? worker.release(item->ticket, now()) : worker.in_flight() == 0;
    worker.shutdown(now());
    const std::string record = "{\"schema_version\":\"1.0.0\",\"document_type\":\"docksr_native_cpu_worker_reference\",\"request\":" +
        inf::request_json(request) + ",\"result\":" + result_json + ",\"backend_result\":" + backend_json +
        ",\"worker_rejection_reason\":" + docksr::core::json_string(rejection_reason) + ",\"backend_valid\":" + (backend_valid ? "true" : "false") +
        ",\"completed\":" + (completed ? "true" : "false") + ",\"consumed\":" + (consumed_valid ? "true" : "false") +
        ",\"released\":" + (released ? "true" : "false") + ",\"child_stop_acknowledged\":" + (child_stopped ? "true" : "false") +
        ",\"child_started\":" + (child_started ? "true" : "false") +
        ",\"child_timed_out\":" + (child_timed_out ? "true" : "false") + ",\"outstanding_requests\":" + std::to_string(worker.in_flight()) +
        ",\"presentation\":\"NOT_RUN\",\"physical_npu\":\"NOT_RUN\",\"output_sha256\":" + docksr::core::json_string(actual_output_sha) +
        ",\"output_sha256_source\":\"TRUSTED_CPU_EXECUTOR_RECEIPT\"" +
        ",\"bridge_error_detail\":" + docksr::core::json_string(native_error_detail) + "}";
    write_text(work / "native-evidence.json", record + "\n");
    std::cout << record << '\n';
    return consumed_valid && released && child_stopped && worker.shutdown_complete() ? 0 : 1;
  } catch (const std::exception& error) {
    std::cout << "{\"status\":\"FAILED\",\"valid\":false,\"physical_npu\":\"NOT_RUN\",\"error\":"
              << docksr::core::json_string(error.what()) << "}\n";
    return 1;
  }
}

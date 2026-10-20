#include "docksr/core/status_snapshot.hpp"

#include <algorithm>
#include <atomic>
#include <filesystem>
#include <fstream>
#include <functional>
#include <iostream>
#include <iterator>
#include <limits>
#include <stdexcept>
#include <string>
#include <thread>
#include <utility>
#include <vector>

#include <sys/stat.h>
#include <unistd.h>

namespace {
using namespace docksr::core;
#define CHECK(expression) do { if (!(expression)) throw std::runtime_error( \
  std::string(__FILE__) + ":" + std::to_string(__LINE__) + ": " #expression); } while (false)

class TemporaryDirectory {
 public:
  TemporaryDirectory() {
    std::string pattern = "/tmp/docksr-status-tests-XXXXXX";
    const auto* result = ::mkdtemp(pattern.data());
    if (!result) throw std::runtime_error("cannot create private test directory");
    path = result;
  }
  ~TemporaryDirectory() {
    std::error_code ignored;
    std::filesystem::remove_all(path, ignored);
  }
  std::filesystem::path path;
};

std::string read(const std::filesystem::path& path) {
  std::ifstream input(path, std::ios::binary);
  return {std::istreambuf_iterator<char>(input), std::istreambuf_iterator<char>()};
}

void write(const std::filesystem::path& path, const std::string& contents, mode_t mode = 0600) {
  std::ofstream output(path, std::ios::binary);
  output << contents;
  output.close();
  CHECK(output.good());
  CHECK(::chmod(path.c_str(), mode) == 0);
}

StatusTracker cpu_tracker() {
  StatusTracker tracker(100);
  CHECK(tracker.begin_cpu_reference("cpu-reference", {2, 2}, {4, 4}, 101));
  return tracker;
}

using Test = std::pair<std::string, std::function<void()>>;
}  // namespace

int main() {
  const std::vector<Test> tests{
    {"fresh status is starting with no claimed evidence or NPU validation", [] {
      StatusTracker tracker(100);
      const auto& value = tracker.snapshot();
      CHECK(value.runtime_state == RuntimeState::Starting);
      CHECK(value.evidence == Evidence::None);
      CHECK(value.npu_device == NpuDeviceStatus::NotTested);
      CHECK(value.npu_model == ModelStatus::Unvalidated);
      CHECK(value.frames_processed == 0);
      CHECK(!value.actual_dimensions && !value.requested_dimensions);
      CHECK(!value.timings_ms.cpu && !value.timings_ms.gpu && !value.timings_ms.npu);
      CHECK(validate_status_snapshot(value));
      CHECK(serialize_status_json(value).find("\"actual\":null") != std::string::npos);
    }},
    {"CPU processing counts output only after explicit successful-writer acknowledgement", [] {
      auto tracker = cpu_tracker();
      CHECK(tracker.snapshot().runtime_state == RuntimeState::CpuReferenceActive);
      CHECK(tracker.snapshot().evidence == Evidence::RealCPU);
      CHECK(tracker.snapshot().frames_processed == 0);
      CHECK(!tracker.snapshot().actual_dimensions);
      CHECK(tracker.acknowledge_cpu_output({2, 2}, {4, 4}, 0.25, 102));
      CHECK(tracker.snapshot().frames_processed == 1);
      CHECK(tracker.snapshot().actual_dimensions == (StatusDimensions{{2, 2}, {4, 4}}));
      CHECK(tracker.snapshot().timings_ms.cpu == 0.25);
      CHECK(!tracker.snapshot().timings_ms.gpu && !tracker.snapshot().timings_ms.npu);
      CHECK(tracker.acknowledge_cpu_output({2, 2}, {4, 4}, {}, 103));
      CHECK(tracker.snapshot().frames_processed == 2);
      CHECK(!tracker.snapshot().timings_ms.cpu);
    }},
    {"failed output never increments actual completed counter", [] {
      auto tracker = cpu_tracker();
      CHECK(tracker.report_failure("OUTPUT_WRITE_FAILED", "Destination could not be written", false, 102));
      CHECK(tracker.snapshot().runtime_state == RuntimeState::Error);
      CHECK(tracker.snapshot().last_error->code == "OUTPUT_WRITE_FAILED");
      CHECK(tracker.snapshot().frames_processed == 0);
      CHECK(!tracker.snapshot().actual_dimensions);
      CHECK(!tracker.acknowledge_cpu_output({2, 2}, {4, 4}, {}, 103));
    }},
    {"physical Vulkan output is counted once per completed scaling operation", [] {
      StatusTracker tracker(100);
      CHECK(tracker.begin_vulkan_reference("vulkan-bilinear", {2, 2}, {4, 4}, Evidence::RealGPU, 101));
      CHECK(tracker.snapshot().runtime_state == RuntimeState::GpuBaselineActive);
      CHECK(tracker.snapshot().evidence == Evidence::RealGPU);
      CHECK(tracker.snapshot().frames_processed == 0);
      CHECK(!tracker.snapshot().actual_dimensions);
      CHECK(tracker.acknowledge_vulkan_output({2, 2}, {4, 4}, 0.125, 102));
      CHECK(tracker.snapshot().frames_processed == 1);
      CHECK(tracker.snapshot().timings_ms.gpu == 0.125);
      CHECK(!tracker.snapshot().timings_ms.cpu && !tracker.snapshot().timings_ms.npu);
      CHECK(!tracker.acknowledge_vulkan_output({2, 2}, {4, 4}, 0.125, 103));
      CHECK(tracker.snapshot().frames_processed == 1);
      CHECK(tracker.snapshot().updated_at_monotonic_ns == 102);
      CHECK(tracker.begin_vulkan_reference("vulkan-bilinear", {2, 2}, {8, 8}, Evidence::RealGPU, 104));
      CHECK(tracker.snapshot().frames_processed == 1);
      CHECK(!tracker.snapshot().timings_ms.gpu);
      CHECK(tracker.acknowledge_vulkan_output({2, 2}, {8, 8}, {}, 105));
      CHECK(tracker.snapshot().frames_processed == 2);
      CHECK(tracker.snapshot().actual_dimensions->output == (Extent{8, 8}));
      CHECK(!tracker.snapshot().timings_ms.gpu);
      CHECK(tracker.snapshot().npu_device == NpuDeviceStatus::NotTested);
      CHECK(tracker.snapshot().npu_model == ModelStatus::Unvalidated);
    }},
    {"software Vulkan completion retains explicit software evidence", [] {
      StatusTracker tracker(100);
      CHECK(tracker.begin_vulkan_reference("vulkan-bilinear", {2, 2}, {4, 4}, Evidence::SoftwareVulkan, 101));
      CHECK(!tracker.acknowledge_cpu_output({2, 2}, {4, 4}, 1.0, 102));
      CHECK(tracker.acknowledge_vulkan_output({2, 2}, {4, 4}, 0.5, 103));
      CHECK(tracker.snapshot().runtime_state == RuntimeState::SoftwareVulkan);
      CHECK(tracker.snapshot().evidence == Evidence::SoftwareVulkan);
      CHECK(tracker.snapshot().frames_processed == 1);
      const auto text = serialize_status_json(tracker.snapshot());
      CHECK(text.find("\"runtime_state\":\"SOFTWARE_VULKAN\"") != std::string::npos);
      CHECK(text.find("\"evidence\":\"SOFTWARE_VULKAN\"") != std::string::npos);
      CHECK(text.find("REAL_GPU") == std::string::npos);
    }},
    {"Vulkan begin refuses CPU simulated unknown and NPU evidence", [] {
      StatusTracker tracker(100);
      for (const auto evidence : {Evidence::None, Evidence::RealCPU, Evidence::Simulated,
                                  Evidence::RealNPU, static_cast<Evidence>(999)}) {
        CHECK(!tracker.begin_vulkan_reference("vulkan-bilinear", {2, 2}, {4, 4}, evidence, 101));
        CHECK(tracker.snapshot().runtime_state == RuntimeState::Starting);
        CHECK(tracker.snapshot().evidence == Evidence::None);
        CHECK(tracker.snapshot().updated_at_monotonic_ns == 100);
      }
      CHECK(!tracker.acknowledge_vulkan_output({2, 2}, {4, 4}, {}, 102));
      CHECK(tracker.snapshot().frames_processed == 0);
    }},
    {"invalid Vulkan dimensions timings and overlap preserve pending operation", [] {
      StatusTracker tracker(100);
      CHECK(!tracker.begin_vulkan_reference("vulkan-bilinear", {0, 2}, {4, 4}, Evidence::RealGPU, 101));
      CHECK(tracker.begin_vulkan_reference("vulkan-bilinear", {2, 2}, {4, 4}, Evidence::RealGPU, 102));
      CHECK(!tracker.begin_vulkan_reference("vulkan-nearest", {2, 2}, {8, 8}, Evidence::RealGPU, 103));
      CHECK(!tracker.acknowledge_vulkan_output({2, 2}, {0, 4}, 0.5, 104));
      CHECK(!tracker.acknowledge_vulkan_output({2, 2}, {4, 4}, -0.5, 104));
      CHECK(!tracker.acknowledge_vulkan_output({2, 2}, {4, 4}, std::numeric_limits<double>::infinity(), 104));
      CHECK(!tracker.acknowledge_vulkan_output({2, 2}, {4, 4}, std::numeric_limits<double>::quiet_NaN(), 104));
      CHECK(tracker.snapshot().frames_processed == 0);
      CHECK(tracker.snapshot().requested_dimensions->output == (Extent{4, 4}));
      CHECK(tracker.snapshot().updated_at_monotonic_ns == 102);
      CHECK(tracker.acknowledge_vulkan_output({2, 2}, {4, 4}, 0.5, 105));
      CHECK(tracker.snapshot().frames_processed == 1);
    }},
    {"CPU fallback completes real CPU output while retaining fallback reason", [] {
      StatusTracker tracker(100);
      CHECK(tracker.begin_vulkan_reference("vulkan-bilinear", {2, 2}, {4, 4}, Evidence::RealGPU, 101));
      CHECK(tracker.report_failure("VULKAN_TIMEOUT", "Vulkan operation timed out", true, 102));
      CHECK(tracker.snapshot().frames_processed == 0);
      CHECK(!tracker.acknowledge_vulkan_output({2, 2}, {4, 4}, 0.5, 103));
      CHECK(!tracker.acknowledge_cpu_output({2, 2}, {4, 4}, 0.5, 103));
      CHECK(tracker.begin_cpu_fallback("cpu-reference-bilinear", {2, 2}, {4, 4},
                                       "VULKAN_TIMEOUT", "Vulkan operation timed out", 104));
      CHECK(tracker.snapshot().frames_processed == 0);
      CHECK(tracker.snapshot().evidence == Evidence::RealCPU);
      CHECK(tracker.acknowledge_cpu_output({2, 2}, {4, 4}, 0.75, 105));
      CHECK(tracker.snapshot().runtime_state == RuntimeState::Fallback);
      CHECK(tracker.snapshot().last_error->code == "VULKAN_TIMEOUT");
      CHECK(tracker.snapshot().last_error->message == "Vulkan operation timed out");
      CHECK(tracker.snapshot().backend_name == "cpu-reference-bilinear");
      CHECK(tracker.snapshot().frames_processed == 1);
      CHECK(tracker.snapshot().timings_ms.cpu == 0.75);
      CHECK(!tracker.snapshot().timings_ms.gpu && !tracker.snapshot().timings_ms.npu);
      CHECK(tracker.acknowledge_cpu_output({2, 2}, {4, 4}, {}, 106));
      CHECK(tracker.snapshot().runtime_state == RuntimeState::Fallback);
      CHECK(tracker.snapshot().last_error->code == "VULKAN_TIMEOUT");
      CHECK(tracker.snapshot().frames_processed == 2);
    }},
    {"backend and dimension changes retain actual completed count without stale timings", [] {
      auto tracker = cpu_tracker();
      CHECK(tracker.acknowledge_cpu_output({2, 2}, {4, 4}, 1.0, 102));
      CHECK(tracker.begin_vulkan_reference("vulkan-bilinear", {3, 3}, {6, 6}, Evidence::SoftwareVulkan, 103));
      CHECK(tracker.snapshot().frames_processed == 1);
      CHECK(!tracker.snapshot().timings_ms.cpu);
      CHECK(tracker.snapshot().requested_dimensions == (StatusDimensions{{3, 3}, {6, 6}}));
      CHECK(tracker.snapshot().actual_dimensions == (StatusDimensions{{2, 2}, {4, 4}}));
      CHECK(tracker.acknowledge_vulkan_output({3, 3}, {6, 6}, {}, 104));
      CHECK(tracker.snapshot().frames_processed == 2);
      CHECK(tracker.begin_cpu_fallback("cpu-reference-nearest", {3, 3}, {9, 9},
                                       "VULKAN_UNAVAILABLE", "Selected Vulkan device is unavailable", 105));
      CHECK(tracker.acknowledge_cpu_output({3, 3}, {9, 9}, {}, 106));
      CHECK(tracker.snapshot().frames_processed == 3);
      CHECK(tracker.snapshot().actual_dimensions->output == (Extent{9, 9}));
      CHECK(tracker.snapshot().runtime_state == RuntimeState::Fallback);
      CHECK(tracker.begin_vulkan_reference("vulkan-nearest", {3, 3}, {6, 6}, Evidence::RealGPU, 107));
      CHECK(!tracker.snapshot().last_error);
      CHECK(tracker.acknowledge_vulkan_output({3, 3}, {6, 6}, {}, 108));
      CHECK(tracker.snapshot().frames_processed == 4);
      CHECK(tracker.snapshot().runtime_state == RuntimeState::GpuBaselineActive);
    }},
    {"failure or CPU switch cancels pending Vulkan acknowledgement", [] {
      StatusTracker tracker(100);
      CHECK(tracker.begin_vulkan_reference("vulkan-bilinear", {2, 2}, {4, 4}, Evidence::RealGPU, 101));
      CHECK(tracker.begin_cpu_reference("cpu-reference-nearest", {2, 2}, {4, 4}, 102));
      CHECK(!tracker.acknowledge_vulkan_output({2, 2}, {4, 4}, {}, 103));
      CHECK(tracker.snapshot().frames_processed == 0);
      CHECK(tracker.acknowledge_cpu_output({2, 2}, {4, 4}, {}, 104));
      CHECK(tracker.begin_vulkan_reference("vulkan-bilinear", {2, 2}, {4, 4}, Evidence::RealGPU, 105));
      CHECK(tracker.report_failure("VULKAN_FAILED", "Backend failed before producing pixels", false, 106));
      CHECK(!tracker.acknowledge_vulkan_output({2, 2}, {4, 4}, {}, 107));
      CHECK(tracker.snapshot().frames_processed == 1);
      CHECK(tracker.snapshot().runtime_state == RuntimeState::Error);
      CHECK(tracker.snapshot().last_error->code == "VULKAN_FAILED");
    }},
    {"new Vulkan and fallback updates remain transactional under invalid input or old time", [] {
      StatusTracker tracker(100);
      CHECK(!tracker.begin_vulkan_reference("vulkan-bilinear", {2, 2}, {4, 4}, Evidence::RealGPU, 99));
      CHECK(tracker.begin_vulkan_reference("vulkan-bilinear", {2, 2}, {4, 4}, Evidence::RealGPU, 101));
      CHECK(!tracker.begin_cpu_fallback("cpu-reference-nearest", {2, 2}, {4, 4}, "FAILED", "old time", 100));
      CHECK(!tracker.begin_cpu_fallback("cpu-reference-nearest", {0, 2}, {4, 4}, "FAILED", "bad dimensions", 102));
      CHECK(!tracker.begin_cpu_fallback("cpu-reference-nearest", {2, 2}, {4, 4}, "FAILED", "", 102));
      CHECK(!tracker.begin_cpu_fallback("cpu-reference-nearest", {2, 2}, {4, 4}, "FAILED", std::string(1025, 'x'), 102));
      CHECK(!tracker.acknowledge_vulkan_output({2, 2}, {4, 4}, {}, 100));
      CHECK(tracker.snapshot().runtime_state == RuntimeState::GpuBaselineActive);
      CHECK(tracker.snapshot().updated_at_monotonic_ns == 101);
      CHECK(tracker.snapshot().frames_processed == 0);
      CHECK(tracker.acknowledge_vulkan_output({2, 2}, {4, 4}, {}, 103));
      CHECK(tracker.snapshot().frames_processed == 1);
    }},
    {"dimension validation is transactional", [] {
      auto tracker = cpu_tracker();
      CHECK(!tracker.begin_cpu_reference("cpu-reference/nearest", {2, 2}, {4, 4}, 102));
      CHECK(!tracker.begin_cpu_reference("cpu-reference", {0, 2}, {4, 4}, 102));
      CHECK(!tracker.begin_cpu_reference("cpu-reference", {2, 2}, {16385, 4}, 102));
      CHECK(!tracker.acknowledge_cpu_output({2, 0}, {4, 4}, 0.5, 102));
      CHECK(!tracker.acknowledge_cpu_output({2, 2}, {4, 0}, 0.5, 102));
      CHECK(tracker.snapshot().updated_at_monotonic_ns == 101);
      CHECK(tracker.snapshot().frames_processed == 0);
      CHECK(tracker.snapshot().requested_dimensions == (StatusDimensions{{2, 2}, {4, 4}}));
    }},
    {"timings reject negative NaN infinity and unavailable NPU measurements", [] {
      auto tracker = cpu_tracker();
      for (const auto value : {-1.0, std::numeric_limits<double>::infinity(),
                                std::numeric_limits<double>::quiet_NaN()})
        CHECK(!tracker.acknowledge_cpu_output({2, 2}, {4, 4}, value, 102));
      CHECK(tracker.snapshot().frames_processed == 0);
      CHECK(tracker.acknowledge_cpu_output({2, 2}, {4, 4}, 0.0, 102));
      auto forged = tracker.snapshot();
      forged.timings_ms.gpu = 1;
      CHECK(!validate_status_snapshot(forged));
      forged.timings_ms.gpu.reset();
      forged.timings_ms.npu = 1;
      CHECK(!validate_status_snapshot(forged));
    }},
    {"device inventory and missing model do not establish NPU readiness", [] {
      auto tracker = cpu_tracker();
      CHECK(tracker.note_npu_device(NpuDeviceStatus::Detected, 102));
      CHECK(tracker.note_model(ModelStatus::Missing, 103));
      CHECK(tracker.snapshot().runtime_state == RuntimeState::CpuReferenceActive);
      CHECK(tracker.snapshot().evidence == Evidence::RealCPU);
      CHECK(tracker.snapshot().npu_model == ModelStatus::Missing);
      CHECK(tracker.snapshot().frames_processed == 0);
    }},
    {"real NPU ready active and evidence are unavailable even on forged snapshots", [] {
      auto tracker = cpu_tracker();
      for (const auto state : {RuntimeState::NpuReady, RuntimeState::NpuActive}) {
        auto forged = tracker.snapshot();
        forged.runtime_state = state;
        forged.npu_device = NpuDeviceStatus::Detected;
        CHECK(!validate_status_snapshot(forged));
        bool threw = false;
        try { static_cast<void>(serialize_status_json(forged)); }
        catch (const std::invalid_argument&) { threw = true; }
        CHECK(threw);
      }
      auto forged = tracker.snapshot();
      forged.evidence = Evidence::RealNPU;
      CHECK(!validate_status_snapshot(forged));
    }},
    {"software Vulkan and simulation cannot masquerade as physical GPU or CPU", [] {
      auto value = cpu_tracker().snapshot();
      value.runtime_state = RuntimeState::GpuBaselineActive;
      value.evidence = Evidence::SoftwareVulkan;
      CHECK(!validate_status_snapshot(value));
      value.runtime_state = RuntimeState::SoftwareVulkan;
      CHECK(validate_status_snapshot(value));
      value.runtime_state = RuntimeState::MockNpuActive;
      CHECK(!validate_status_snapshot(value));
      value.evidence = Evidence::Simulated;
      CHECK(validate_status_snapshot(value));
      value.frames_processed = 1;
      value.actual_dimensions = value.requested_dimensions;
      value.timings_ms.cpu = 1;
      CHECK(!validate_status_snapshot(value));
    }},
    {"failure timeout reasons preserve completed count and allow a later CPU recovery", [] {
      auto tracker = cpu_tracker();
      CHECK(tracker.acknowledge_cpu_output({2, 2}, {4, 4}, 1.0, 102));
      CHECK(tracker.report_failure("CPU_TIMEOUT", "CPU worker exceeded its deadline", true, 103));
      CHECK(tracker.snapshot().runtime_state == RuntimeState::Fallback);
      CHECK(tracker.snapshot().last_error->message == "CPU worker exceeded its deadline");
      CHECK(tracker.snapshot().frames_processed == 1);
      CHECK(!tracker.snapshot().timings_ms.cpu);
      CHECK(tracker.begin_cpu_reference("cpu-reference", {2, 2}, {6, 6}, 104));
      CHECK(tracker.snapshot().frames_processed == 1);
      CHECK(!tracker.snapshot().last_error);
      CHECK(tracker.acknowledge_cpu_output({2, 2}, {6, 6}, 1.25, 105));
      CHECK(tracker.snapshot().frames_processed == 2);
      CHECK(tracker.snapshot().actual_dimensions->output == (Extent{6, 6}));
    }},
    {"monotonic updates reject backwards time without changing state", [] {
      auto tracker = cpu_tracker();
      CHECK(!tracker.report_failure("FAILURE", "old observation", false, 99));
      CHECK(!tracker.acknowledge_cpu_output({2, 2}, {4, 4}, {}, 100));
      CHECK(!tracker.note_model(ModelStatus::Missing, 100));
      CHECK(!tracker.note_npu_device(NpuDeviceStatus::Detected, 100));
      CHECK(tracker.snapshot().updated_at_monotonic_ns == 101);
      CHECK(tracker.snapshot().runtime_state == RuntimeState::CpuReferenceActive);
      CHECK(tracker.snapshot().frames_processed == 0);
    }},
    {"freshness is bounded age in the same monotonic clock domain", [] {
      auto tracker = cpu_tracker();
      CHECK(!status_is_stale(tracker.snapshot(), 110, 9));
      CHECK(status_is_stale(tracker.snapshot(), 111, 9));
      CHECK(status_is_stale(tracker.snapshot(), 100, 9));
      auto invalid = tracker.snapshot();
      invalid.evidence = Evidence::RealNPU;
      CHECK(status_is_stale(invalid, 101, 9));
    }},
    {"serialization escapes reasons and retains null unmeasured values", [] {
      auto tracker = cpu_tracker();
      CHECK(tracker.report_failure("OUTPUT_ERROR", "quote\" newline\nslash\\", false, 102));
      const auto text = serialize_status_json(tracker.snapshot());
      CHECK(text.find("quote\\\" newline\\nslash\\\\") != std::string::npos);
      CHECK(text.find("\"cpu\":null,\"gpu\":null,\"npu\":null") != std::string::npos);
      CHECK(text.find("\"document_type\":\"docksr_status\"") != std::string::npos);
      CHECK(text.find("\"frames_processed\":0") != std::string::npos);
    }},
    {"atomic status publication is owner-only and replaces only known status", [] {
      TemporaryDirectory directory;
      const auto path = directory.path / "status.json";
      auto tracker = cpu_tracker();
      CHECK(publish_status_json(path, tracker.snapshot()));
      CHECK(read(path) == serialize_status_json(tracker.snapshot()) + '\n');
      struct stat info {};
      CHECK(::stat(path.c_str(), &info) == 0);
      CHECK((info.st_mode & 0777) == 0600);
      CHECK(info.st_uid == ::geteuid());
      CHECK(info.st_nlink == 1);
      CHECK(tracker.acknowledge_cpu_output({2, 2}, {4, 4}, 1.5, 102));
      CHECK(publish_status_json(path, tracker.snapshot()));
      CHECK(read(path) == serialize_status_json(tracker.snapshot()) + '\n');
      CHECK(std::distance(std::filesystem::directory_iterator(directory.path),
                          std::filesystem::directory_iterator{}) == 1);
    }},
    {"publisher preserves unrelated files symlink targets hardlinks and unsafe targets", [] {
      TemporaryDirectory directory;
      const auto unrelated = directory.path / "unrelated.txt";
      const auto link = directory.path / "link.json";
      const auto hardlink = directory.path / "hardlink.json";
      const auto public_file = directory.path / "public.json";
      const auto tracker = cpu_tracker();
      write(unrelated, "unrelated user data\n");
      CHECK(!publish_status_json(unrelated, tracker.snapshot()));
      CHECK(read(unrelated) == "unrelated user data\n");
      std::filesystem::create_symlink(unrelated, link);
      CHECK(!publish_status_json(link, tracker.snapshot()));
      CHECK(read(unrelated) == "unrelated user data\n");
      std::filesystem::create_hard_link(unrelated, hardlink);
      CHECK(!publish_status_json(hardlink, tracker.snapshot()));
      write(public_file, serialize_status_json(tracker.snapshot()), 0644);
      CHECK(!publish_status_json(public_file, tracker.snapshot()));
      const auto unsafe = directory.path / "unsafe";
      std::filesystem::create_directory(unsafe);
      CHECK(::chmod(unsafe.c_str(), 0777) == 0);
      CHECK(!publish_status_json(unsafe / "status.json", tracker.snapshot()));
      CHECK(!std::filesystem::exists(unsafe / "status.json"));
      CHECK(::chmod(unsafe.c_str(), 0700) == 0);
    }},
    {"invalid NPU snapshot cannot be published as a status file", [] {
      TemporaryDirectory directory;
      auto forged = cpu_tracker().snapshot();
      forged.runtime_state = RuntimeState::NpuActive;
      forged.evidence = Evidence::RealNPU;
      const auto path = directory.path / "status.json";
      CHECK(!publish_status_json(path, forged));
      CHECK(!std::filesystem::exists(path));
    }},
    {"concurrent readers observe whole old or whole new status documents", [] {
      TemporaryDirectory directory;
      const auto path = directory.path / "status.json";
      auto tracker = cpu_tracker();
      std::vector<StatusSnapshot> snapshots{tracker.snapshot()};
      for (MonotonicNs i = 0; i < 10; ++i) {
        CHECK(tracker.acknowledge_cpu_output({2, 2}, {4, 4}, {}, 102 + i));
        snapshots.push_back(tracker.snapshot());
      }
      std::vector<std::string> whole_documents;
      for (const auto& snapshot : snapshots)
        whole_documents.push_back(serialize_status_json(snapshot) + '\n');
      CHECK(publish_status_json(path, snapshots.front()));
      std::atomic<bool> invalid{false};
      std::atomic<std::uint64_t> reads{0};
      std::jthread reader([&](std::stop_token stop) {
        while (!stop.stop_requested()) {
          const auto contents = read(path);
          if (std::find(whole_documents.begin(), whole_documents.end(), contents) == whole_documents.end())
            invalid.store(true, std::memory_order_relaxed);
          reads.fetch_add(1, std::memory_order_relaxed);
        }
      });
      while (reads.load(std::memory_order_relaxed) == 0) std::this_thread::yield();
      for (std::size_t i = 1; i < snapshots.size(); ++i)
        CHECK(publish_status_json(path, snapshots[i]));
      reader.request_stop();
      reader.join();
      CHECK(!invalid.load());
      CHECK(reads.load() > 0);
      CHECK(read(path) == whole_documents.back());
    }},
  };
  std::size_t passed = 0;
  for (const auto& [name, run] : tests) {
    try {
      run();
      ++passed;
      std::cout << "PASS " << name << '\n';
    } catch (const std::exception& error) {
      std::cerr << "FAIL " << name << ": " << error.what() << '\n';
    }
  }
  std::cout << passed << '/' << tests.size() << " status tests passed\n";
  return passed == tests.size() ? 0 : 1;
}

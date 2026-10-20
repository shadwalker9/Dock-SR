#pragma once

#include <cstdint>
#include <optional>
#include <span>
#include <string>
#include <string_view>
#include <vector>

namespace docksr::core {

struct Extent {
  std::uint32_t width{};
  std::uint32_t height{};
  bool operator==(const Extent&) const = default;
};

struct Profile {
  std::string_view id;
  std::uint32_t revision;
  Extent input;
  Extent output;
  std::string_view mode;
};

enum class ValidationScope { Simulation, Hardware };
enum class ValidationStatus {
  Unknown, Unvalidated, Compiling, Validated, Incompatible, Revoked, Fallback
};

// An identity describes one exact validation tuple, not a device capability claim.
struct ValidationIdentity {
  std::string device_id;
  std::string driver_version;
  std::string runtime_version;
  std::string model_id;
  std::string model_sha256;
  std::string mode;
  std::string quality;
  ValidationScope scope{ValidationScope::Simulation};
  bool operator==(const ValidationIdentity&) const = default;
};

struct ValidationRecord {
  std::string profile_id;
  std::uint32_t profile_revision{};
  ValidationIdentity identity;
  ValidationStatus status{ValidationStatus::Unvalidated};
};

struct RegistryResult {
  bool accepted{};
  std::string reason;
  explicit operator bool() const { return accepted; }
};

// In-memory, single-owner host state. Persistence and RPC are deliberately absent.
// Only trusted backend code may supply validation records. This first increment
// accepts Simulation records only and cannot mark hardware as validated.
class ProfileRegistry {
 public:
  static constexpr std::string_view default_profile = "probe_720_1080";
  static std::span<const Profile> profiles();
  static const Profile* find(std::string_view id);

  RegistryResult request_profile(std::string_view id);
  RegistryResult record_validation(ValidationRecord record);
  RegistryResult activate(const ValidationIdentity& identity);
  void disable();

  bool enabled() const { return enabled_; }
  std::string_view requested_profile() const { return requested_profile_; }
  const std::optional<ValidationRecord>& active() const { return active_; }
  const std::vector<ValidationRecord>& validations() const { return validations_; }
  ValidationStatus validation_status(const ValidationIdentity& identity) const;

 private:
  RegistryResult check_identity(const Profile&, const ValidationIdentity&) const;
  bool enabled_{false};
  std::string requested_profile_{default_profile};
  std::optional<ValidationRecord> active_;
  std::vector<ValidationRecord> validations_;
};

std::string_view to_string(ValidationStatus status);
std::string_view to_string(ValidationScope scope);

}  // namespace docksr::core

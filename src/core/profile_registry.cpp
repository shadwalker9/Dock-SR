#include "docksr/core/profile_registry.hpp"

#include <algorithm>
#include <array>
#include <utility>

namespace docksr::core {
namespace {
constexpr std::array registry{
    Profile{"probe_720_1080", 1, {1280, 720}, {1920, 1080}, "docked"},
    Profile{"portable_720_1080", 1, {1280, 720}, {1920, 1080}, "portable"},
    Profile{"television_720_2160", 1, {1280, 720}, {3840, 2160}, "docked"},
    Profile{"television_1080_2160", 1, {1920, 1080}, {3840, 2160}, "docked"},
    Profile{"television_900_2160", 1, {1600, 900}, {3840, 2160}, "docked"},
    Profile{"television_720_1440", 1, {1280, 720}, {2560, 1440}, "docked"},
};

bool alphanumeric(unsigned char c) {
  return (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') ||
         (c >= '0' && c <= '9');
}

bool token(std::string_view value, bool model = false) {
  return !value.empty() && value.size() <= 128 &&
         std::all_of(value.begin(), value.end(), [model](unsigned char c) {
           return alphanumeric(c) || c == '_' || c == '-' ||
                  (!model && (c == '.' || c == ':' || c == '+'));
         });
}

bool sha256(std::string_view value) {
  return value.size() == 64 &&
         std::all_of(value.begin(), value.end(), [](unsigned char c) {
           return (c >= '0' && c <= '9') || (c >= 'a' && c <= 'f');
         });
}

RegistryResult ok() { return {true, "accepted"}; }
RegistryResult reject(std::string reason) { return {false, std::move(reason)}; }
}  // namespace

std::span<const Profile> ProfileRegistry::profiles() { return registry; }

const Profile* ProfileRegistry::find(std::string_view id) {
  const auto it = std::find_if(registry.begin(), registry.end(),
                               [id](const auto& p) { return p.id == id; });
  return it == registry.end() ? nullptr : &*it;
}

RegistryResult ProfileRegistry::request_profile(std::string_view id) {
  if (!find(id)) return reject("profile_not_allowlisted");
  if (requested_profile_ != id) {
    disable();
    requested_profile_ = id;
  }
  return ok();
}

RegistryResult ProfileRegistry::check_identity(
    const Profile& profile, const ValidationIdentity& identity) const {
  if (identity.scope != ValidationScope::Simulation)
    return reject("hardware_backend_unavailable");
  if (!token(identity.device_id) || !token(identity.driver_version) ||
      !token(identity.runtime_version) || !token(identity.model_id, true) ||
      !sha256(identity.model_sha256))
    return reject("invalid_validation_identity");
  if (identity.mode != profile.mode) return reject("incompatible_output_mode");
  constexpr std::array<std::string_view, 4> qualities{
      "balanced", "performance", "quality", "proof"};
  if (std::find(qualities.begin(), qualities.end(), identity.quality) == qualities.end())
    return reject("quality_not_allowlisted");
  return ok();
}

RegistryResult ProfileRegistry::record_validation(ValidationRecord record) {
  const auto* profile = find(record.profile_id);
  if (!profile) return reject("profile_not_allowlisted");
  if (record.profile_revision != profile->revision)
    return reject("incompatible_profile_revision");
  const auto identity_check = check_identity(*profile, record.identity);
  if (!identity_check) return identity_check;
  if (to_string(record.status) == "unknown_enum")
    return reject("invalid_validation_status");

  const auto it = std::find_if(validations_.begin(), validations_.end(),
      [&](const auto& prior) {
        return prior.profile_id == record.profile_id &&
               prior.profile_revision == record.profile_revision &&
               prior.identity == record.identity;
      });
  // Bound retained validation identities as well as the profile allowlist.
  constexpr std::size_t max_records = 64;
  if (it == validations_.end()) {
    if (validations_.size() == max_records) return reject("validation_registry_full");
    validations_.push_back(record);
  } else {
    *it = record;
  }
  if (active_ && active_->profile_id == record.profile_id &&
      active_->identity == record.identity &&
      record.status != ValidationStatus::Validated)
    disable();
  return ok();
}

RegistryResult ProfileRegistry::activate(const ValidationIdentity& identity) {
  // Failed reconfiguration must not leave an old tuple active.
  disable();
  const auto* profile = find(requested_profile_);
  if (!profile) return reject("profile_not_allowlisted");
  const auto identity_check = check_identity(*profile, identity);
  if (!identity_check) return identity_check;
  const auto it = std::find_if(validations_.begin(), validations_.end(),
      [&](const auto& record) {
        return record.profile_id == requested_profile_ &&
               record.profile_revision == profile->revision &&
               record.identity == identity &&
               record.status == ValidationStatus::Validated;
      });
  if (it == validations_.end()) return reject("tuple_not_validated");
  active_ = *it;
  enabled_ = true;
  return ok();
}

void ProfileRegistry::disable() {
  enabled_ = false;
  active_.reset();
}

ValidationStatus ProfileRegistry::validation_status(
    const ValidationIdentity& identity) const {
  const auto* profile = find(requested_profile_);
  if (!profile || !check_identity(*profile, identity))
    return ValidationStatus::Incompatible;
  const auto it = std::find_if(validations_.begin(), validations_.end(),
      [&](const auto& record) {
        return record.profile_id == requested_profile_ &&
               record.profile_revision == profile->revision && record.identity == identity;
      });
  return it == validations_.end() ? ValidationStatus::Unvalidated : it->status;
}

std::string_view to_string(ValidationStatus status) {
  switch (status) {
    case ValidationStatus::Unknown: return "unknown";
    case ValidationStatus::Unvalidated: return "unvalidated";
    case ValidationStatus::Compiling: return "compiling";
    case ValidationStatus::Validated: return "validated";
    case ValidationStatus::Incompatible: return "incompatible";
    case ValidationStatus::Revoked: return "revoked";
    case ValidationStatus::Fallback: return "fallback";
  }
  return "unknown_enum";
}

std::string_view to_string(ValidationScope scope) {
  switch (scope) {
    case ValidationScope::Simulation: return "simulation";
    case ValidationScope::Hardware: return "hardware";
  }
  return "unknown_enum";
}
}  // namespace docksr::core

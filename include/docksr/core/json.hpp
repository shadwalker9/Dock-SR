#pragma once

#include <string>
#include <string_view>

namespace docksr::core {
// ASCII-safe JSON string encoding, including arbitrary command-line bytes.
std::string json_string(std::string_view value);
}  // namespace docksr::core

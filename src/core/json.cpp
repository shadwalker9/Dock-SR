#include "docksr/core/json.hpp"

namespace docksr::core {
std::string json_string(std::string_view value) {
  constexpr char hex[] = "0123456789abcdef";
  std::string result{"\""};
  for (const unsigned char c : value) {
    switch (c) {
      case '"': result += "\\\""; break;
      case '\\': result += "\\\\"; break;
      case '\b': result += "\\b"; break;
      case '\f': result += "\\f"; break;
      case '\n': result += "\\n"; break;
      case '\r': result += "\\r"; break;
      case '\t': result += "\\t"; break;
      default:
        if (c < 0x20 || c >= 0x7f) {
          result += "\\u00";
          result += hex[c >> 4];
          result += hex[c & 0xf];
        } else {
          result += static_cast<char>(c);
        }
    }
  }
  result += '"';
  return result;
}
}  // namespace docksr::core

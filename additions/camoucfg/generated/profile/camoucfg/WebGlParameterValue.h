/*
 * WebGlParameterValue.h
 *
 * Generated from schemas/camoufox-profile.openapi.yaml.
 * Do not edit by hand.
 */

#ifndef CAMOUFOX_PROFILE_WebGlParameterValue_H_
#define CAMOUFOX_PROFILE_WebGlParameterValue_H_

#include <cstdint>
#include <optional>
#include <string>

#include "json.hpp"

namespace camoucfg {

class WebGlParameterValue {
 public:
  WebGlParameterValue() = default;
  explicit WebGlParameterValue(const nlohmann::json& json) { fromJson(json); }

  bool fromJson(const nlohmann::json& json) {
    if (!json.is_object()) {
      return false;
    }
    m_IsSet = true;
    return true;
  }

  nlohmann::json toJson() const {
    nlohmann::json json = nlohmann::json::object();
    return json;
  }

  bool isSet() const { return m_IsSet; }

 private:
  bool m_IsSet = false;
};

}  // namespace camoucfg

#endif  // CAMOUFOX_PROFILE_WebGlParameterValue_H_


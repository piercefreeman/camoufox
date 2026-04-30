/*
 * WebGlShaderPrecisionFormat.h
 *
 * Generated from schemas/camoufox-profile.openapi.yaml.
 * Do not edit by hand.
 */

#ifndef CAMOUFOX_PROFILE_WebGlShaderPrecisionFormat_H_
#define CAMOUFOX_PROFILE_WebGlShaderPrecisionFormat_H_

#include <cstdint>
#include <optional>
#include <string>

#include "json.hpp"

namespace camoucfg {

class WebGlShaderPrecisionFormat {
 public:
  WebGlShaderPrecisionFormat() = default;
  explicit WebGlShaderPrecisionFormat(const nlohmann::json& json) { fromJson(json); }

  bool fromJson(const nlohmann::json& json) {
    if (!json.is_object()) {
      return false;
    }
    m_IsSet = true;
    if (json.contains("rangeMin") && !json.at("rangeMin").is_null()) {
      try {
        m_rangeMin = json.at("rangeMin").get<int32_t>();
      } catch (...) {
        return false;
      }
    }
    if (json.contains("rangeMax") && !json.at("rangeMax").is_null()) {
      try {
        m_rangeMax = json.at("rangeMax").get<int32_t>();
      } catch (...) {
        return false;
      }
    }
    if (json.contains("precision") && !json.at("precision").is_null()) {
      try {
        m_precision = json.at("precision").get<int32_t>();
      } catch (...) {
        return false;
      }
    }
    return true;
  }

  nlohmann::json toJson() const {
    nlohmann::json json = nlohmann::json::object();
    if (m_rangeMin.has_value()) {
      json["rangeMin"] = *m_rangeMin;
    }
    if (m_rangeMax.has_value()) {
      json["rangeMax"] = *m_rangeMax;
    }
    if (m_precision.has_value()) {
      json["precision"] = *m_precision;
    }
    return json;
  }

  bool isSet() const { return m_IsSet; }

  bool rangeMinIsSet() const { return m_rangeMin.has_value(); }
  std::optional<int32_t> getRangeMin() const {
    return m_rangeMin;
  }
  void setRangeMin(const int32_t& value) {
    m_rangeMin = value;
  }

  bool rangeMaxIsSet() const { return m_rangeMax.has_value(); }
  std::optional<int32_t> getRangeMax() const {
    return m_rangeMax;
  }
  void setRangeMax(const int32_t& value) {
    m_rangeMax = value;
  }

  bool precisionIsSet() const { return m_precision.has_value(); }
  std::optional<int32_t> getPrecision() const {
    return m_precision;
  }
  void setPrecision(const int32_t& value) {
    m_precision = value;
  }

 private:
  bool m_IsSet = false;
  std::optional<int32_t> m_rangeMin;
  std::optional<int32_t> m_rangeMax;
  std::optional<int32_t> m_precision;
};

}  // namespace camoucfg

#endif  // CAMOUFOX_PROFILE_WebGlShaderPrecisionFormat_H_


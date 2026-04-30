/*
 * HumanizeProfile.h
 *
 * Generated from schemas/camoufox-profile.openapi.yaml.
 * Do not edit by hand.
 */

#ifndef CAMOUFOX_PROFILE_HumanizeProfile_H_
#define CAMOUFOX_PROFILE_HumanizeProfile_H_

#include <cstdint>
#include <optional>
#include <string>

#include "json.hpp"

namespace camoucfg {

class HumanizeProfile {
 public:
  HumanizeProfile() = default;
  explicit HumanizeProfile(const nlohmann::json& json) { fromJson(json); }

  bool fromJson(const nlohmann::json& json) {
    if (!json.is_object()) {
      return false;
    }
    m_IsSet = true;
    if (json.contains("enabled") && !json.at("enabled").is_null()) {
      try {
        m_enabled = json.at("enabled").get<bool>();
      } catch (...) {
        return false;
      }
    }
    if (json.contains("maxTime") && !json.at("maxTime").is_null()) {
      try {
        m_maxTime = json.at("maxTime").get<double>();
      } catch (...) {
        return false;
      }
    }
    if (json.contains("minTime") && !json.at("minTime").is_null()) {
      try {
        m_minTime = json.at("minTime").get<double>();
      } catch (...) {
        return false;
      }
    }
    return true;
  }

  nlohmann::json toJson() const {
    nlohmann::json json = nlohmann::json::object();
    if (m_enabled.has_value()) {
      json["enabled"] = *m_enabled;
    }
    if (m_maxTime.has_value()) {
      json["maxTime"] = *m_maxTime;
    }
    if (m_minTime.has_value()) {
      json["minTime"] = *m_minTime;
    }
    return json;
  }

  bool isSet() const { return m_IsSet; }

  bool enabledIsSet() const { return m_enabled.has_value(); }
  std::optional<bool> isEnabled() const {
    return m_enabled;
  }
  void setEnabled(const bool& value) {
    m_enabled = value;
  }

  bool maxTimeIsSet() const { return m_maxTime.has_value(); }
  std::optional<double> getMaxTime() const {
    return m_maxTime;
  }
  void setMaxTime(const double& value) {
    m_maxTime = value;
  }

  bool minTimeIsSet() const { return m_minTime.has_value(); }
  std::optional<double> getMinTime() const {
    return m_minTime;
  }
  void setMinTime(const double& value) {
    m_minTime = value;
  }

 private:
  bool m_IsSet = false;
  std::optional<bool> m_enabled;
  std::optional<double> m_maxTime;
  std::optional<double> m_minTime;
};

}  // namespace camoucfg

#endif  // CAMOUFOX_PROFILE_HumanizeProfile_H_


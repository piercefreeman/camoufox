/*
 * CanvasProfile.h
 *
 * Generated from schemas/camoufox-profile.openapi.yaml.
 * Do not edit by hand.
 */

#ifndef CAMOUFOX_PROFILE_CanvasProfile_H_
#define CAMOUFOX_PROFILE_CanvasProfile_H_

#include <cstdint>
#include <optional>
#include <string>

#include "json.hpp"

namespace camoucfg {

class CanvasProfile {
 public:
  CanvasProfile() = default;
  explicit CanvasProfile(const nlohmann::json& json) { fromJson(json); }

  bool fromJson(const nlohmann::json& json) {
    if (!json.is_object()) {
      return false;
    }
    m_IsSet = true;
    if (json.contains("seed") && !json.at("seed").is_null()) {
      try {
        m_seed = json.at("seed").get<int32_t>();
      } catch (...) {
        return false;
      }
    }
    if (json.contains("aaOffset") && !json.at("aaOffset").is_null()) {
      try {
        m_aaOffset = json.at("aaOffset").get<int32_t>();
      } catch (...) {
        return false;
      }
    }
    if (json.contains("aaCapOffset") && !json.at("aaCapOffset").is_null()) {
      try {
        m_aaCapOffset = json.at("aaCapOffset").get<bool>();
      } catch (...) {
        return false;
      }
    }
    return true;
  }

  nlohmann::json toJson() const {
    nlohmann::json json = nlohmann::json::object();
    if (m_seed.has_value()) {
      json["seed"] = *m_seed;
    }
    if (m_aaOffset.has_value()) {
      json["aaOffset"] = *m_aaOffset;
    }
    if (m_aaCapOffset.has_value()) {
      json["aaCapOffset"] = *m_aaCapOffset;
    }
    return json;
  }

  bool isSet() const { return m_IsSet; }

  bool seedIsSet() const { return m_seed.has_value(); }
  std::optional<int32_t> getSeed() const {
    return m_seed;
  }
  void setSeed(const int32_t& value) {
    m_seed = value;
  }

  bool aaOffsetIsSet() const { return m_aaOffset.has_value(); }
  std::optional<int32_t> getAaOffset() const {
    return m_aaOffset;
  }
  void setAaOffset(const int32_t& value) {
    m_aaOffset = value;
  }

  bool aaCapOffsetIsSet() const { return m_aaCapOffset.has_value(); }
  std::optional<bool> isAaCapOffset() const {
    return m_aaCapOffset;
  }
  void setAaCapOffset(const bool& value) {
    m_aaCapOffset = value;
  }

 private:
  bool m_IsSet = false;
  std::optional<int32_t> m_seed;
  std::optional<int32_t> m_aaOffset;
  std::optional<bool> m_aaCapOffset;
};

}  // namespace camoucfg

#endif  // CAMOUFOX_PROFILE_CanvasProfile_H_


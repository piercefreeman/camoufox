/*
 * DocumentBodyProfile.h
 *
 * Generated from schemas/camoufox-profile.openapi.yaml.
 * Do not edit by hand.
 */

#ifndef CAMOUFOX_PROFILE_DocumentBodyProfile_H_
#define CAMOUFOX_PROFILE_DocumentBodyProfile_H_

#include <cstdint>
#include <optional>
#include <string>

#include "json.hpp"

namespace camoucfg {

class DocumentBodyProfile {
 public:
  DocumentBodyProfile() = default;
  explicit DocumentBodyProfile(const nlohmann::json& json) { fromJson(json); }

  bool fromJson(const nlohmann::json& json) {
    if (!json.is_object()) {
      return false;
    }
    m_IsSet = true;
    if (json.contains("clientWidth") && !json.at("clientWidth").is_null()) {
      try {
        m_clientWidth = json.at("clientWidth").get<int32_t>();
      } catch (...) {
        return false;
      }
    }
    if (json.contains("clientHeight") && !json.at("clientHeight").is_null()) {
      try {
        m_clientHeight = json.at("clientHeight").get<int32_t>();
      } catch (...) {
        return false;
      }
    }
    if (json.contains("clientTop") && !json.at("clientTop").is_null()) {
      try {
        m_clientTop = json.at("clientTop").get<int32_t>();
      } catch (...) {
        return false;
      }
    }
    if (json.contains("clientLeft") && !json.at("clientLeft").is_null()) {
      try {
        m_clientLeft = json.at("clientLeft").get<int32_t>();
      } catch (...) {
        return false;
      }
    }
    return true;
  }

  nlohmann::json toJson() const {
    nlohmann::json json = nlohmann::json::object();
    if (m_clientWidth.has_value()) {
      json["clientWidth"] = *m_clientWidth;
    }
    if (m_clientHeight.has_value()) {
      json["clientHeight"] = *m_clientHeight;
    }
    if (m_clientTop.has_value()) {
      json["clientTop"] = *m_clientTop;
    }
    if (m_clientLeft.has_value()) {
      json["clientLeft"] = *m_clientLeft;
    }
    return json;
  }

  bool isSet() const { return m_IsSet; }

  bool clientWidthIsSet() const { return m_clientWidth.has_value(); }
  std::optional<int32_t> getClientWidth() const {
    return m_clientWidth;
  }
  void setClientWidth(const int32_t& value) {
    m_clientWidth = value;
  }

  bool clientHeightIsSet() const { return m_clientHeight.has_value(); }
  std::optional<int32_t> getClientHeight() const {
    return m_clientHeight;
  }
  void setClientHeight(const int32_t& value) {
    m_clientHeight = value;
  }

  bool clientTopIsSet() const { return m_clientTop.has_value(); }
  std::optional<int32_t> getClientTop() const {
    return m_clientTop;
  }
  void setClientTop(const int32_t& value) {
    m_clientTop = value;
  }

  bool clientLeftIsSet() const { return m_clientLeft.has_value(); }
  std::optional<int32_t> getClientLeft() const {
    return m_clientLeft;
  }
  void setClientLeft(const int32_t& value) {
    m_clientLeft = value;
  }

 private:
  bool m_IsSet = false;
  std::optional<int32_t> m_clientWidth;
  std::optional<int32_t> m_clientHeight;
  std::optional<int32_t> m_clientTop;
  std::optional<int32_t> m_clientLeft;
};

}  // namespace camoucfg

#endif  // CAMOUFOX_PROFILE_DocumentBodyProfile_H_


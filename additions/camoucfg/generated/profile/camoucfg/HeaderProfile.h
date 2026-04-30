/*
 * HeaderProfile.h
 *
 * Generated from schemas/camoufox-profile.openapi.yaml.
 * Do not edit by hand.
 */

#ifndef CAMOUFOX_PROFILE_HeaderProfile_H_
#define CAMOUFOX_PROFILE_HeaderProfile_H_

#include <cstdint>
#include <optional>
#include <string>

#include "json.hpp"

namespace camoucfg {

class HeaderProfile {
 public:
  HeaderProfile() = default;
  explicit HeaderProfile(const nlohmann::json& json) { fromJson(json); }

  bool fromJson(const nlohmann::json& json) {
    if (!json.is_object()) {
      return false;
    }
    m_IsSet = true;
    if (json.contains("User-Agent") && !json.at("User-Agent").is_null()) {
      try {
        m_userAgent = json.at("User-Agent").get<std::string>();
      } catch (...) {
        return false;
      }
    }
    if (json.contains("Accept-Language") && !json.at("Accept-Language").is_null()) {
      try {
        m_acceptLanguage = json.at("Accept-Language").get<std::string>();
      } catch (...) {
        return false;
      }
    }
    if (json.contains("Accept-Encoding") && !json.at("Accept-Encoding").is_null()) {
      try {
        m_acceptEncoding = json.at("Accept-Encoding").get<std::string>();
      } catch (...) {
        return false;
      }
    }
    return true;
  }

  nlohmann::json toJson() const {
    nlohmann::json json = nlohmann::json::object();
    if (m_userAgent.has_value()) {
      json["User-Agent"] = *m_userAgent;
    }
    if (m_acceptLanguage.has_value()) {
      json["Accept-Language"] = *m_acceptLanguage;
    }
    if (m_acceptEncoding.has_value()) {
      json["Accept-Encoding"] = *m_acceptEncoding;
    }
    return json;
  }

  bool isSet() const { return m_IsSet; }

  bool userAgentIsSet() const { return m_userAgent.has_value(); }
  std::optional<std::string> getUserAgent() const {
    return m_userAgent;
  }
  void setUserAgent(const std::string& value) {
    m_userAgent = value;
  }

  bool acceptLanguageIsSet() const { return m_acceptLanguage.has_value(); }
  std::optional<std::string> getAcceptLanguage() const {
    return m_acceptLanguage;
  }
  void setAcceptLanguage(const std::string& value) {
    m_acceptLanguage = value;
  }

  bool acceptEncodingIsSet() const { return m_acceptEncoding.has_value(); }
  std::optional<std::string> getAcceptEncoding() const {
    return m_acceptEncoding;
  }
  void setAcceptEncoding(const std::string& value) {
    m_acceptEncoding = value;
  }

 private:
  bool m_IsSet = false;
  std::optional<std::string> m_userAgent;
  std::optional<std::string> m_acceptLanguage;
  std::optional<std::string> m_acceptEncoding;
};

}  // namespace camoucfg

#endif  // CAMOUFOX_PROFILE_HeaderProfile_H_


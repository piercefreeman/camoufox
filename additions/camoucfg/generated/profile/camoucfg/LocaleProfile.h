/*
 * LocaleProfile.h
 *
 * Generated from schemas/camoufox-profile.openapi.yaml.
 * Do not edit by hand.
 */

#ifndef CAMOUFOX_PROFILE_LocaleProfile_H_
#define CAMOUFOX_PROFILE_LocaleProfile_H_

#include <cstdint>
#include <optional>
#include <string>

#include "json.hpp"

namespace camoucfg {

class LocaleProfile {
 public:
  LocaleProfile() = default;
  explicit LocaleProfile(const nlohmann::json& json) { fromJson(json); }

  bool fromJson(const nlohmann::json& json) {
    if (!json.is_object()) {
      return false;
    }
    m_IsSet = true;
    if (json.contains("language") && !json.at("language").is_null()) {
      try {
        m_language = json.at("language").get<std::string>();
      } catch (...) {
        return false;
      }
    }
    if (json.contains("region") && !json.at("region").is_null()) {
      try {
        m_region = json.at("region").get<std::string>();
      } catch (...) {
        return false;
      }
    }
    if (json.contains("script") && !json.at("script").is_null()) {
      try {
        m_script = json.at("script").get<std::string>();
      } catch (...) {
        return false;
      }
    }
    if (json.contains("all") && !json.at("all").is_null()) {
      try {
        m_all = json.at("all").get<std::string>();
      } catch (...) {
        return false;
      }
    }
    return true;
  }

  nlohmann::json toJson() const {
    nlohmann::json json = nlohmann::json::object();
    if (m_language.has_value()) {
      json["language"] = *m_language;
    }
    if (m_region.has_value()) {
      json["region"] = *m_region;
    }
    if (m_script.has_value()) {
      json["script"] = *m_script;
    }
    if (m_all.has_value()) {
      json["all"] = *m_all;
    }
    return json;
  }

  bool isSet() const { return m_IsSet; }

  bool languageIsSet() const { return m_language.has_value(); }
  std::optional<std::string> getLanguage() const {
    return m_language;
  }
  void setLanguage(const std::string& value) {
    m_language = value;
  }

  bool regionIsSet() const { return m_region.has_value(); }
  std::optional<std::string> getRegion() const {
    return m_region;
  }
  void setRegion(const std::string& value) {
    m_region = value;
  }

  bool scriptIsSet() const { return m_script.has_value(); }
  std::optional<std::string> getScript() const {
    return m_script;
  }
  void setScript(const std::string& value) {
    m_script = value;
  }

  bool allIsSet() const { return m_all.has_value(); }
  std::optional<std::string> getAll() const {
    return m_all;
  }
  void setAll(const std::string& value) {
    m_all = value;
  }

 private:
  bool m_IsSet = false;
  std::optional<std::string> m_language;
  std::optional<std::string> m_region;
  std::optional<std::string> m_script;
  std::optional<std::string> m_all;
};

}  // namespace camoucfg

#endif  // CAMOUFOX_PROFILE_LocaleProfile_H_


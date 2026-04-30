/*
 * NavigatorProfile.h
 *
 * Generated from schemas/camoufox-profile.openapi.yaml.
 * Do not edit by hand.
 */

#ifndef CAMOUFOX_PROFILE_NavigatorProfile_H_
#define CAMOUFOX_PROFILE_NavigatorProfile_H_

#include <cstdint>
#include <optional>
#include <string>

#include "json.hpp"

namespace camoucfg {

class NavigatorProfile {
 public:
  NavigatorProfile() = default;
  explicit NavigatorProfile(const nlohmann::json& json) { fromJson(json); }

  bool fromJson(const nlohmann::json& json) {
    if (!json.is_object()) {
      return false;
    }
    m_IsSet = true;
    if (json.contains("userAgent") && !json.at("userAgent").is_null()) {
      try {
        m_userAgent = json.at("userAgent").get<std::string>();
      } catch (...) {
        return false;
      }
    }
    if (json.contains("doNotTrack") && !json.at("doNotTrack").is_null()) {
      try {
        m_doNotTrack = json.at("doNotTrack").get<std::string>();
      } catch (...) {
        return false;
      }
    }
    if (json.contains("appCodeName") && !json.at("appCodeName").is_null()) {
      try {
        m_appCodeName = json.at("appCodeName").get<std::string>();
      } catch (...) {
        return false;
      }
    }
    if (json.contains("appName") && !json.at("appName").is_null()) {
      try {
        m_appName = json.at("appName").get<std::string>();
      } catch (...) {
        return false;
      }
    }
    if (json.contains("appVersion") && !json.at("appVersion").is_null()) {
      try {
        m_appVersion = json.at("appVersion").get<std::string>();
      } catch (...) {
        return false;
      }
    }
    if (json.contains("oscpu") && !json.at("oscpu").is_null()) {
      try {
        m_oscpu = json.at("oscpu").get<std::string>();
      } catch (...) {
        return false;
      }
    }
    if (json.contains("language") && !json.at("language").is_null()) {
      try {
        m_language = json.at("language").get<std::string>();
      } catch (...) {
        return false;
      }
    }
    if (json.contains("languages") && !json.at("languages").is_null()) {
      m_languages = json.at("languages");
    }
    if (json.contains("platform") && !json.at("platform").is_null()) {
      try {
        m_platform = json.at("platform").get<std::string>();
      } catch (...) {
        return false;
      }
    }
    if (json.contains("hardwareConcurrency") && !json.at("hardwareConcurrency").is_null()) {
      try {
        m_hardwareConcurrency = json.at("hardwareConcurrency").get<int32_t>();
      } catch (...) {
        return false;
      }
    }
    if (json.contains("product") && !json.at("product").is_null()) {
      try {
        m_product = json.at("product").get<std::string>();
      } catch (...) {
        return false;
      }
    }
    if (json.contains("productSub") && !json.at("productSub").is_null()) {
      try {
        m_productSub = json.at("productSub").get<std::string>();
      } catch (...) {
        return false;
      }
    }
    if (json.contains("maxTouchPoints") && !json.at("maxTouchPoints").is_null()) {
      try {
        m_maxTouchPoints = json.at("maxTouchPoints").get<int32_t>();
      } catch (...) {
        return false;
      }
    }
    if (json.contains("cookieEnabled") && !json.at("cookieEnabled").is_null()) {
      try {
        m_cookieEnabled = json.at("cookieEnabled").get<bool>();
      } catch (...) {
        return false;
      }
    }
    if (json.contains("globalPrivacyControl") && !json.at("globalPrivacyControl").is_null()) {
      try {
        m_globalPrivacyControl = json.at("globalPrivacyControl").get<bool>();
      } catch (...) {
        return false;
      }
    }
    if (json.contains("buildID") && !json.at("buildID").is_null()) {
      try {
        m_buildID = json.at("buildID").get<std::string>();
      } catch (...) {
        return false;
      }
    }
    if (json.contains("onLine") && !json.at("onLine").is_null()) {
      try {
        m_onLine = json.at("onLine").get<bool>();
      } catch (...) {
        return false;
      }
    }
    return true;
  }

  nlohmann::json toJson() const {
    nlohmann::json json = nlohmann::json::object();
    if (m_userAgent.has_value()) {
      json["userAgent"] = *m_userAgent;
    }
    if (m_doNotTrack.has_value()) {
      json["doNotTrack"] = *m_doNotTrack;
    }
    if (m_appCodeName.has_value()) {
      json["appCodeName"] = *m_appCodeName;
    }
    if (m_appName.has_value()) {
      json["appName"] = *m_appName;
    }
    if (m_appVersion.has_value()) {
      json["appVersion"] = *m_appVersion;
    }
    if (m_oscpu.has_value()) {
      json["oscpu"] = *m_oscpu;
    }
    if (m_language.has_value()) {
      json["language"] = *m_language;
    }
    if (m_languages.has_value()) {
      json["languages"] = *m_languages;
    }
    if (m_platform.has_value()) {
      json["platform"] = *m_platform;
    }
    if (m_hardwareConcurrency.has_value()) {
      json["hardwareConcurrency"] = *m_hardwareConcurrency;
    }
    if (m_product.has_value()) {
      json["product"] = *m_product;
    }
    if (m_productSub.has_value()) {
      json["productSub"] = *m_productSub;
    }
    if (m_maxTouchPoints.has_value()) {
      json["maxTouchPoints"] = *m_maxTouchPoints;
    }
    if (m_cookieEnabled.has_value()) {
      json["cookieEnabled"] = *m_cookieEnabled;
    }
    if (m_globalPrivacyControl.has_value()) {
      json["globalPrivacyControl"] = *m_globalPrivacyControl;
    }
    if (m_buildID.has_value()) {
      json["buildID"] = *m_buildID;
    }
    if (m_onLine.has_value()) {
      json["onLine"] = *m_onLine;
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

  bool doNotTrackIsSet() const { return m_doNotTrack.has_value(); }
  std::optional<std::string> getDoNotTrack() const {
    return m_doNotTrack;
  }
  void setDoNotTrack(const std::string& value) {
    m_doNotTrack = value;
  }

  bool appCodeNameIsSet() const { return m_appCodeName.has_value(); }
  std::optional<std::string> getAppCodeName() const {
    return m_appCodeName;
  }
  void setAppCodeName(const std::string& value) {
    m_appCodeName = value;
  }

  bool appNameIsSet() const { return m_appName.has_value(); }
  std::optional<std::string> getAppName() const {
    return m_appName;
  }
  void setAppName(const std::string& value) {
    m_appName = value;
  }

  bool appVersionIsSet() const { return m_appVersion.has_value(); }
  std::optional<std::string> getAppVersion() const {
    return m_appVersion;
  }
  void setAppVersion(const std::string& value) {
    m_appVersion = value;
  }

  bool oscpuIsSet() const { return m_oscpu.has_value(); }
  std::optional<std::string> getOscpu() const {
    return m_oscpu;
  }
  void setOscpu(const std::string& value) {
    m_oscpu = value;
  }

  bool languageIsSet() const { return m_language.has_value(); }
  std::optional<std::string> getLanguage() const {
    return m_language;
  }
  void setLanguage(const std::string& value) {
    m_language = value;
  }

  bool languagesIsSet() const { return m_languages.has_value(); }
  std::optional<nlohmann::json> getLanguages() const {
    return m_languages;
  }
  void setLanguages(const nlohmann::json& value) {
    m_languages = value;
  }

  bool platformIsSet() const { return m_platform.has_value(); }
  std::optional<std::string> getPlatform() const {
    return m_platform;
  }
  void setPlatform(const std::string& value) {
    m_platform = value;
  }

  bool hardwareConcurrencyIsSet() const { return m_hardwareConcurrency.has_value(); }
  std::optional<int32_t> getHardwareConcurrency() const {
    return m_hardwareConcurrency;
  }
  void setHardwareConcurrency(const int32_t& value) {
    m_hardwareConcurrency = value;
  }

  bool productIsSet() const { return m_product.has_value(); }
  std::optional<std::string> getProduct() const {
    return m_product;
  }
  void setProduct(const std::string& value) {
    m_product = value;
  }

  bool productSubIsSet() const { return m_productSub.has_value(); }
  std::optional<std::string> getProductSub() const {
    return m_productSub;
  }
  void setProductSub(const std::string& value) {
    m_productSub = value;
  }

  bool maxTouchPointsIsSet() const { return m_maxTouchPoints.has_value(); }
  std::optional<int32_t> getMaxTouchPoints() const {
    return m_maxTouchPoints;
  }
  void setMaxTouchPoints(const int32_t& value) {
    m_maxTouchPoints = value;
  }

  bool cookieEnabledIsSet() const { return m_cookieEnabled.has_value(); }
  std::optional<bool> isCookieEnabled() const {
    return m_cookieEnabled;
  }
  void setCookieEnabled(const bool& value) {
    m_cookieEnabled = value;
  }

  bool globalPrivacyControlIsSet() const { return m_globalPrivacyControl.has_value(); }
  std::optional<bool> isGlobalPrivacyControl() const {
    return m_globalPrivacyControl;
  }
  void setGlobalPrivacyControl(const bool& value) {
    m_globalPrivacyControl = value;
  }

  bool buildIDIsSet() const { return m_buildID.has_value(); }
  std::optional<std::string> getBuildID() const {
    return m_buildID;
  }
  void setBuildID(const std::string& value) {
    m_buildID = value;
  }

  bool onLineIsSet() const { return m_onLine.has_value(); }
  std::optional<bool> isOnLine() const {
    return m_onLine;
  }
  void setOnLine(const bool& value) {
    m_onLine = value;
  }

 private:
  bool m_IsSet = false;
  std::optional<std::string> m_userAgent;
  std::optional<std::string> m_doNotTrack;
  std::optional<std::string> m_appCodeName;
  std::optional<std::string> m_appName;
  std::optional<std::string> m_appVersion;
  std::optional<std::string> m_oscpu;
  std::optional<std::string> m_language;
  std::optional<nlohmann::json> m_languages;
  std::optional<std::string> m_platform;
  std::optional<int32_t> m_hardwareConcurrency;
  std::optional<std::string> m_product;
  std::optional<std::string> m_productSub;
  std::optional<int32_t> m_maxTouchPoints;
  std::optional<bool> m_cookieEnabled;
  std::optional<bool> m_globalPrivacyControl;
  std::optional<std::string> m_buildID;
  std::optional<bool> m_onLine;
};

}  // namespace camoucfg

#endif  // CAMOUFOX_PROFILE_NavigatorProfile_H_


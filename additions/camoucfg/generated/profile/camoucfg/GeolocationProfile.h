/*
 * GeolocationProfile.h
 *
 * Generated from schemas/camoufox-profile.openapi.yaml.
 * Do not edit by hand.
 */

#ifndef CAMOUFOX_PROFILE_GeolocationProfile_H_
#define CAMOUFOX_PROFILE_GeolocationProfile_H_

#include <cstdint>
#include <optional>
#include <string>

#include "json.hpp"

namespace camoucfg {

class GeolocationProfile {
 public:
  GeolocationProfile() = default;
  explicit GeolocationProfile(const nlohmann::json& json) { fromJson(json); }

  bool fromJson(const nlohmann::json& json) {
    if (!json.is_object()) {
      return false;
    }
    m_IsSet = true;
    if (json.contains("latitude") && !json.at("latitude").is_null()) {
      try {
        m_latitude = json.at("latitude").get<double>();
      } catch (...) {
        return false;
      }
    }
    if (json.contains("longitude") && !json.at("longitude").is_null()) {
      try {
        m_longitude = json.at("longitude").get<double>();
      } catch (...) {
        return false;
      }
    }
    if (json.contains("accuracy") && !json.at("accuracy").is_null()) {
      try {
        m_accuracy = json.at("accuracy").get<double>();
      } catch (...) {
        return false;
      }
    }
    return true;
  }

  nlohmann::json toJson() const {
    nlohmann::json json = nlohmann::json::object();
    if (m_latitude.has_value()) {
      json["latitude"] = *m_latitude;
    }
    if (m_longitude.has_value()) {
      json["longitude"] = *m_longitude;
    }
    if (m_accuracy.has_value()) {
      json["accuracy"] = *m_accuracy;
    }
    return json;
  }

  bool isSet() const { return m_IsSet; }

  bool latitudeIsSet() const { return m_latitude.has_value(); }
  std::optional<double> getLatitude() const {
    return m_latitude;
  }
  void setLatitude(const double& value) {
    m_latitude = value;
  }

  bool longitudeIsSet() const { return m_longitude.has_value(); }
  std::optional<double> getLongitude() const {
    return m_longitude;
  }
  void setLongitude(const double& value) {
    m_longitude = value;
  }

  bool accuracyIsSet() const { return m_accuracy.has_value(); }
  std::optional<double> getAccuracy() const {
    return m_accuracy;
  }
  void setAccuracy(const double& value) {
    m_accuracy = value;
  }

 private:
  bool m_IsSet = false;
  std::optional<double> m_latitude;
  std::optional<double> m_longitude;
  std::optional<double> m_accuracy;
};

}  // namespace camoucfg

#endif  // CAMOUFOX_PROFILE_GeolocationProfile_H_


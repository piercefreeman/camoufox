/*
 * AudioProfile.h
 *
 * Generated from schemas/camoufox-profile.openapi.yaml.
 * Do not edit by hand.
 */

#ifndef CAMOUFOX_PROFILE_AudioProfile_H_
#define CAMOUFOX_PROFILE_AudioProfile_H_

#include <cstdint>
#include <optional>
#include <string>

#include "json.hpp"

namespace camoucfg {

class AudioProfile {
 public:
  AudioProfile() = default;
  explicit AudioProfile(const nlohmann::json& json) { fromJson(json); }

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
    return true;
  }

  nlohmann::json toJson() const {
    nlohmann::json json = nlohmann::json::object();
    if (m_seed.has_value()) {
      json["seed"] = *m_seed;
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

 private:
  bool m_IsSet = false;
  std::optional<int32_t> m_seed;
};

}  // namespace camoucfg

#endif  // CAMOUFOX_PROFILE_AudioProfile_H_


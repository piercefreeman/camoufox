/*
 * WebGlContextAttributes.h
 *
 * Generated from schemas/camoufox-profile.openapi.yaml.
 * Do not edit by hand.
 */

#ifndef CAMOUFOX_PROFILE_WebGlContextAttributes_H_
#define CAMOUFOX_PROFILE_WebGlContextAttributes_H_

#include <cstdint>
#include <optional>
#include <string>

#include "json.hpp"

namespace camoucfg {

class WebGlContextAttributes {
 public:
  WebGlContextAttributes() = default;
  explicit WebGlContextAttributes(const nlohmann::json& json) { fromJson(json); }

  bool fromJson(const nlohmann::json& json) {
    if (!json.is_object()) {
      return false;
    }
    m_IsSet = true;
    if (json.contains("alpha") && !json.at("alpha").is_null()) {
      const auto& value = json.at("alpha");
      if (!value.is_boolean()) {
        return false;
      }
      m_alpha = value.get<bool>();
    }
    if (json.contains("antialias") && !json.at("antialias").is_null()) {
      const auto& value = json.at("antialias");
      if (!value.is_boolean()) {
        return false;
      }
      m_antialias = value.get<bool>();
    }
    if (json.contains("depth") && !json.at("depth").is_null()) {
      const auto& value = json.at("depth");
      if (!value.is_boolean()) {
        return false;
      }
      m_depth = value.get<bool>();
    }
    if (json.contains("failIfMajorPerformanceCaveat") && !json.at("failIfMajorPerformanceCaveat").is_null()) {
      const auto& value = json.at("failIfMajorPerformanceCaveat");
      if (!value.is_boolean()) {
        return false;
      }
      m_failIfMajorPerformanceCaveat = value.get<bool>();
    }
    if (json.contains("powerPreference") && !json.at("powerPreference").is_null()) {
      const auto& value = json.at("powerPreference");
      if (!value.is_string()) {
        return false;
      }
      m_powerPreference = value.get<std::string>();
    }
    if (json.contains("premultipliedAlpha") && !json.at("premultipliedAlpha").is_null()) {
      const auto& value = json.at("premultipliedAlpha");
      if (!value.is_boolean()) {
        return false;
      }
      m_premultipliedAlpha = value.get<bool>();
    }
    if (json.contains("preserveDrawingBuffer") && !json.at("preserveDrawingBuffer").is_null()) {
      const auto& value = json.at("preserveDrawingBuffer");
      if (!value.is_boolean()) {
        return false;
      }
      m_preserveDrawingBuffer = value.get<bool>();
    }
    if (json.contains("stencil") && !json.at("stencil").is_null()) {
      const auto& value = json.at("stencil");
      if (!value.is_boolean()) {
        return false;
      }
      m_stencil = value.get<bool>();
    }
    return true;
  }

  nlohmann::json toJson() const {
    nlohmann::json json = nlohmann::json::object();
    if (m_alpha.has_value()) {
      json["alpha"] = *m_alpha;
    }
    if (m_antialias.has_value()) {
      json["antialias"] = *m_antialias;
    }
    if (m_depth.has_value()) {
      json["depth"] = *m_depth;
    }
    if (m_failIfMajorPerformanceCaveat.has_value()) {
      json["failIfMajorPerformanceCaveat"] = *m_failIfMajorPerformanceCaveat;
    }
    if (m_powerPreference.has_value()) {
      json["powerPreference"] = *m_powerPreference;
    }
    if (m_premultipliedAlpha.has_value()) {
      json["premultipliedAlpha"] = *m_premultipliedAlpha;
    }
    if (m_preserveDrawingBuffer.has_value()) {
      json["preserveDrawingBuffer"] = *m_preserveDrawingBuffer;
    }
    if (m_stencil.has_value()) {
      json["stencil"] = *m_stencil;
    }
    return json;
  }

  bool isSet() const { return m_IsSet; }

  bool alphaIsSet() const { return m_alpha.has_value(); }
  std::optional<bool> isAlpha() const {
    return m_alpha;
  }
  void setAlpha(const bool& value) {
    m_alpha = value;
  }

  bool antialiasIsSet() const { return m_antialias.has_value(); }
  std::optional<bool> isAntialias() const {
    return m_antialias;
  }
  void setAntialias(const bool& value) {
    m_antialias = value;
  }

  bool depthIsSet() const { return m_depth.has_value(); }
  std::optional<bool> isDepth() const {
    return m_depth;
  }
  void setDepth(const bool& value) {
    m_depth = value;
  }

  bool failIfMajorPerformanceCaveatIsSet() const { return m_failIfMajorPerformanceCaveat.has_value(); }
  std::optional<bool> isFailIfMajorPerformanceCaveat() const {
    return m_failIfMajorPerformanceCaveat;
  }
  void setFailIfMajorPerformanceCaveat(const bool& value) {
    m_failIfMajorPerformanceCaveat = value;
  }

  bool powerPreferenceIsSet() const { return m_powerPreference.has_value(); }
  std::optional<std::string> getPowerPreference() const {
    return m_powerPreference;
  }
  void setPowerPreference(const std::string& value) {
    m_powerPreference = value;
  }

  bool premultipliedAlphaIsSet() const { return m_premultipliedAlpha.has_value(); }
  std::optional<bool> isPremultipliedAlpha() const {
    return m_premultipliedAlpha;
  }
  void setPremultipliedAlpha(const bool& value) {
    m_premultipliedAlpha = value;
  }

  bool preserveDrawingBufferIsSet() const { return m_preserveDrawingBuffer.has_value(); }
  std::optional<bool> isPreserveDrawingBuffer() const {
    return m_preserveDrawingBuffer;
  }
  void setPreserveDrawingBuffer(const bool& value) {
    m_preserveDrawingBuffer = value;
  }

  bool stencilIsSet() const { return m_stencil.has_value(); }
  std::optional<bool> isStencil() const {
    return m_stencil;
  }
  void setStencil(const bool& value) {
    m_stencil = value;
  }

 private:
  bool m_IsSet = false;
  std::optional<bool> m_alpha;
  std::optional<bool> m_antialias;
  std::optional<bool> m_depth;
  std::optional<bool> m_failIfMajorPerformanceCaveat;
  std::optional<std::string> m_powerPreference;
  std::optional<bool> m_premultipliedAlpha;
  std::optional<bool> m_preserveDrawingBuffer;
  std::optional<bool> m_stencil;
};

}  // namespace camoucfg

#endif  // CAMOUFOX_PROFILE_WebGlContextAttributes_H_


/*
 * WebGlProfile.h
 *
 * Generated from schemas/camoufox-profile.openapi.yaml.
 * Do not edit by hand.
 */

#ifndef CAMOUFOX_PROFILE_WebGlProfile_H_
#define CAMOUFOX_PROFILE_WebGlProfile_H_

#include <cstdint>
#include <optional>
#include <string>

#include "json.hpp"
#include "WebGlContextAttributes.h"

namespace camoucfg {

class WebGlProfile {
 public:
  WebGlProfile() = default;
  explicit WebGlProfile(const nlohmann::json& json) { fromJson(json); }

  bool fromJson(const nlohmann::json& json) {
    if (!json.is_object()) {
      return false;
    }
    m_IsSet = true;
    if (json.contains("renderer") && !json.at("renderer").is_null()) {
      const auto& value = json.at("renderer");
      if (!value.is_string()) {
        return false;
      }
      m_renderer = value.get<std::string>();
    }
    if (json.contains("vendor") && !json.at("vendor").is_null()) {
      const auto& value = json.at("vendor");
      if (!value.is_string()) {
        return false;
      }
      m_vendor = value.get<std::string>();
    }
    if (json.contains("supportedExtensions") && !json.at("supportedExtensions").is_null()) {
      m_supportedExtensions = json.at("supportedExtensions");
    }
    if (json.contains("parameters") && !json.at("parameters").is_null()) {
      m_parameters = json.at("parameters");
    }
    if (json.contains("parametersBlockIfNotDefined") && !json.at("parametersBlockIfNotDefined").is_null()) {
      const auto& value = json.at("parametersBlockIfNotDefined");
      if (!value.is_boolean()) {
        return false;
      }
      m_parametersBlockIfNotDefined = value.get<bool>();
    }
    if (json.contains("shaderPrecisionFormats") && !json.at("shaderPrecisionFormats").is_null()) {
      m_shaderPrecisionFormats = json.at("shaderPrecisionFormats");
    }
    if (json.contains("shaderPrecisionFormatsBlockIfNotDefined") && !json.at("shaderPrecisionFormatsBlockIfNotDefined").is_null()) {
      const auto& value = json.at("shaderPrecisionFormatsBlockIfNotDefined");
      if (!value.is_boolean()) {
        return false;
      }
      m_shaderPrecisionFormatsBlockIfNotDefined = value.get<bool>();
    }
    if (json.contains("contextAttributes") && !json.at("contextAttributes").is_null()) {
      WebGlContextAttributes value;
      if (!value.fromJson(json.at("contextAttributes"))) {
        return false;
      }
      m_contextAttributes = value;
    }
    return true;
  }

  nlohmann::json toJson() const {
    nlohmann::json json = nlohmann::json::object();
    if (m_renderer.has_value()) {
      json["renderer"] = *m_renderer;
    }
    if (m_vendor.has_value()) {
      json["vendor"] = *m_vendor;
    }
    if (m_supportedExtensions.has_value()) {
      json["supportedExtensions"] = *m_supportedExtensions;
    }
    if (m_parameters.has_value()) {
      json["parameters"] = *m_parameters;
    }
    if (m_parametersBlockIfNotDefined.has_value()) {
      json["parametersBlockIfNotDefined"] = *m_parametersBlockIfNotDefined;
    }
    if (m_shaderPrecisionFormats.has_value()) {
      json["shaderPrecisionFormats"] = *m_shaderPrecisionFormats;
    }
    if (m_shaderPrecisionFormatsBlockIfNotDefined.has_value()) {
      json["shaderPrecisionFormatsBlockIfNotDefined"] = *m_shaderPrecisionFormatsBlockIfNotDefined;
    }
    if (m_contextAttributes.has_value()) {
      json["contextAttributes"] = m_contextAttributes->toJson();
    }
    return json;
  }

  bool isSet() const { return m_IsSet; }

  bool rendererIsSet() const { return m_renderer.has_value(); }
  std::optional<std::string> getRenderer() const {
    return m_renderer;
  }
  void setRenderer(const std::string& value) {
    m_renderer = value;
  }

  bool vendorIsSet() const { return m_vendor.has_value(); }
  std::optional<std::string> getVendor() const {
    return m_vendor;
  }
  void setVendor(const std::string& value) {
    m_vendor = value;
  }

  bool supportedExtensionsIsSet() const { return m_supportedExtensions.has_value(); }
  std::optional<nlohmann::json> getSupportedExtensions() const {
    return m_supportedExtensions;
  }
  void setSupportedExtensions(const nlohmann::json& value) {
    m_supportedExtensions = value;
  }

  bool parametersIsSet() const { return m_parameters.has_value(); }
  std::optional<nlohmann::json> getParameters() const {
    return m_parameters;
  }
  void setParameters(const nlohmann::json& value) {
    m_parameters = value;
  }

  bool parametersBlockIfNotDefinedIsSet() const { return m_parametersBlockIfNotDefined.has_value(); }
  std::optional<bool> isParametersBlockIfNotDefined() const {
    return m_parametersBlockIfNotDefined;
  }
  void setParametersBlockIfNotDefined(const bool& value) {
    m_parametersBlockIfNotDefined = value;
  }

  bool shaderPrecisionFormatsIsSet() const { return m_shaderPrecisionFormats.has_value(); }
  std::optional<nlohmann::json> getShaderPrecisionFormats() const {
    return m_shaderPrecisionFormats;
  }
  void setShaderPrecisionFormats(const nlohmann::json& value) {
    m_shaderPrecisionFormats = value;
  }

  bool shaderPrecisionFormatsBlockIfNotDefinedIsSet() const { return m_shaderPrecisionFormatsBlockIfNotDefined.has_value(); }
  std::optional<bool> isShaderPrecisionFormatsBlockIfNotDefined() const {
    return m_shaderPrecisionFormatsBlockIfNotDefined;
  }
  void setShaderPrecisionFormatsBlockIfNotDefined(const bool& value) {
    m_shaderPrecisionFormatsBlockIfNotDefined = value;
  }

  bool contextAttributesIsSet() const { return m_contextAttributes.has_value(); }
  std::optional<WebGlContextAttributes> getContextAttributes() const {
    return m_contextAttributes;
  }
  void setContextAttributes(const WebGlContextAttributes& value) {
    m_contextAttributes = value;
  }

 private:
  bool m_IsSet = false;
  std::optional<std::string> m_renderer;
  std::optional<std::string> m_vendor;
  std::optional<nlohmann::json> m_supportedExtensions;
  std::optional<nlohmann::json> m_parameters;
  std::optional<bool> m_parametersBlockIfNotDefined;
  std::optional<nlohmann::json> m_shaderPrecisionFormats;
  std::optional<bool> m_shaderPrecisionFormatsBlockIfNotDefined;
  std::optional<WebGlContextAttributes> m_contextAttributes;
};

}  // namespace camoucfg

#endif  // CAMOUFOX_PROFILE_WebGlProfile_H_


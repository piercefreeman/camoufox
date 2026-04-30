/*
 * ScreenProfile.h
 *
 * Generated from schemas/camoufox-profile.openapi.yaml.
 * Do not edit by hand.
 */

#ifndef CAMOUFOX_PROFILE_ScreenProfile_H_
#define CAMOUFOX_PROFILE_ScreenProfile_H_

#include <cstdint>
#include <optional>
#include <string>

#include "json.hpp"

namespace camoucfg {

class ScreenProfile {
 public:
  ScreenProfile() = default;
  explicit ScreenProfile(const nlohmann::json& json) { fromJson(json); }

  bool fromJson(const nlohmann::json& json) {
    if (!json.is_object()) {
      return false;
    }
    m_IsSet = true;
    if (json.contains("availHeight") && !json.at("availHeight").is_null()) {
      try {
        m_availHeight = json.at("availHeight").get<int32_t>();
      } catch (...) {
        return false;
      }
    }
    if (json.contains("availWidth") && !json.at("availWidth").is_null()) {
      try {
        m_availWidth = json.at("availWidth").get<int32_t>();
      } catch (...) {
        return false;
      }
    }
    if (json.contains("availTop") && !json.at("availTop").is_null()) {
      try {
        m_availTop = json.at("availTop").get<int32_t>();
      } catch (...) {
        return false;
      }
    }
    if (json.contains("availLeft") && !json.at("availLeft").is_null()) {
      try {
        m_availLeft = json.at("availLeft").get<int32_t>();
      } catch (...) {
        return false;
      }
    }
    if (json.contains("height") && !json.at("height").is_null()) {
      try {
        m_height = json.at("height").get<int32_t>();
      } catch (...) {
        return false;
      }
    }
    if (json.contains("width") && !json.at("width").is_null()) {
      try {
        m_width = json.at("width").get<int32_t>();
      } catch (...) {
        return false;
      }
    }
    if (json.contains("colorDepth") && !json.at("colorDepth").is_null()) {
      try {
        m_colorDepth = json.at("colorDepth").get<int32_t>();
      } catch (...) {
        return false;
      }
    }
    if (json.contains("pixelDepth") && !json.at("pixelDepth").is_null()) {
      try {
        m_pixelDepth = json.at("pixelDepth").get<int32_t>();
      } catch (...) {
        return false;
      }
    }
    if (json.contains("pageXOffset") && !json.at("pageXOffset").is_null()) {
      try {
        m_pageXOffset = json.at("pageXOffset").get<double>();
      } catch (...) {
        return false;
      }
    }
    if (json.contains("pageYOffset") && !json.at("pageYOffset").is_null()) {
      try {
        m_pageYOffset = json.at("pageYOffset").get<double>();
      } catch (...) {
        return false;
      }
    }
    return true;
  }

  nlohmann::json toJson() const {
    nlohmann::json json = nlohmann::json::object();
    if (m_availHeight.has_value()) {
      json["availHeight"] = *m_availHeight;
    }
    if (m_availWidth.has_value()) {
      json["availWidth"] = *m_availWidth;
    }
    if (m_availTop.has_value()) {
      json["availTop"] = *m_availTop;
    }
    if (m_availLeft.has_value()) {
      json["availLeft"] = *m_availLeft;
    }
    if (m_height.has_value()) {
      json["height"] = *m_height;
    }
    if (m_width.has_value()) {
      json["width"] = *m_width;
    }
    if (m_colorDepth.has_value()) {
      json["colorDepth"] = *m_colorDepth;
    }
    if (m_pixelDepth.has_value()) {
      json["pixelDepth"] = *m_pixelDepth;
    }
    if (m_pageXOffset.has_value()) {
      json["pageXOffset"] = *m_pageXOffset;
    }
    if (m_pageYOffset.has_value()) {
      json["pageYOffset"] = *m_pageYOffset;
    }
    return json;
  }

  bool isSet() const { return m_IsSet; }

  bool availHeightIsSet() const { return m_availHeight.has_value(); }
  std::optional<int32_t> getAvailHeight() const {
    return m_availHeight;
  }
  void setAvailHeight(const int32_t& value) {
    m_availHeight = value;
  }

  bool availWidthIsSet() const { return m_availWidth.has_value(); }
  std::optional<int32_t> getAvailWidth() const {
    return m_availWidth;
  }
  void setAvailWidth(const int32_t& value) {
    m_availWidth = value;
  }

  bool availTopIsSet() const { return m_availTop.has_value(); }
  std::optional<int32_t> getAvailTop() const {
    return m_availTop;
  }
  void setAvailTop(const int32_t& value) {
    m_availTop = value;
  }

  bool availLeftIsSet() const { return m_availLeft.has_value(); }
  std::optional<int32_t> getAvailLeft() const {
    return m_availLeft;
  }
  void setAvailLeft(const int32_t& value) {
    m_availLeft = value;
  }

  bool heightIsSet() const { return m_height.has_value(); }
  std::optional<int32_t> getHeight() const {
    return m_height;
  }
  void setHeight(const int32_t& value) {
    m_height = value;
  }

  bool widthIsSet() const { return m_width.has_value(); }
  std::optional<int32_t> getWidth() const {
    return m_width;
  }
  void setWidth(const int32_t& value) {
    m_width = value;
  }

  bool colorDepthIsSet() const { return m_colorDepth.has_value(); }
  std::optional<int32_t> getColorDepth() const {
    return m_colorDepth;
  }
  void setColorDepth(const int32_t& value) {
    m_colorDepth = value;
  }

  bool pixelDepthIsSet() const { return m_pixelDepth.has_value(); }
  std::optional<int32_t> getPixelDepth() const {
    return m_pixelDepth;
  }
  void setPixelDepth(const int32_t& value) {
    m_pixelDepth = value;
  }

  bool pageXOffsetIsSet() const { return m_pageXOffset.has_value(); }
  std::optional<double> getPageXOffset() const {
    return m_pageXOffset;
  }
  void setPageXOffset(const double& value) {
    m_pageXOffset = value;
  }

  bool pageYOffsetIsSet() const { return m_pageYOffset.has_value(); }
  std::optional<double> getPageYOffset() const {
    return m_pageYOffset;
  }
  void setPageYOffset(const double& value) {
    m_pageYOffset = value;
  }

 private:
  bool m_IsSet = false;
  std::optional<int32_t> m_availHeight;
  std::optional<int32_t> m_availWidth;
  std::optional<int32_t> m_availTop;
  std::optional<int32_t> m_availLeft;
  std::optional<int32_t> m_height;
  std::optional<int32_t> m_width;
  std::optional<int32_t> m_colorDepth;
  std::optional<int32_t> m_pixelDepth;
  std::optional<double> m_pageXOffset;
  std::optional<double> m_pageYOffset;
};

}  // namespace camoucfg

#endif  // CAMOUFOX_PROFILE_ScreenProfile_H_


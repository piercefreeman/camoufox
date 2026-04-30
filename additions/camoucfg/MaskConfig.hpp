/*
Helper to extract values from the CAMOU_CONFIG_PATH runtime profile.
Written by daijro.
*/

#pragma once

#include "generated/profile/camoucfg/CamoufoxProfile.h"
#include "json.hpp"
#include "mozilla/glue/Debug.h"

#include <algorithm>
#include <array>
#include <cctype>
#include <codecvt>
#include <cstddef>
#include <cstdio>
#include <cstdlib>
#include <fstream>
#include <memory>
#include <mutex>
#include <optional>
#include <sstream>
#include <string>
#include <tuple>
#include <unordered_map>
#include <variant>
#include <vector>

#ifdef _WIN32
#  include <windows.h>
#endif

namespace MaskConfig {

inline std::optional<std::string> get_env_utf8(const std::string& name) {
#ifdef _WIN32
  std::wstring wName(name.begin(), name.end());
  DWORD size = GetEnvironmentVariableW(wName.c_str(), nullptr, 0);
  if (size == 0) return std::nullopt;

  std::vector<wchar_t> buffer(size);
  GetEnvironmentVariableW(wName.c_str(), buffer.data(), size);
  std::wstring wValue(buffer.data());

  std::wstring_convert<std::codecvt_utf8_utf16<wchar_t>> converter;
  return converter.to_bytes(wValue);
#else
  const char* value = std::getenv(name.c_str());
  if (!value) return std::nullopt;
  return std::string(value);
#endif
}

inline const nlohmann::json& GetJson() {
  static std::once_flag initFlag;
  static nlohmann::json jsonConfig;

  std::call_once(initFlag, []() {
    auto configPath = get_env_utf8("CAMOU_CONFIG_PATH");
    if (!configPath || configPath->empty()) {
      jsonConfig = nlohmann::json{};
      return;
    }

    std::ifstream configFile(*configPath, std::ios::in | std::ios::binary);
    if (!configFile) {
      printf_stderr("ERROR: Could not open CAMOU_CONFIG_PATH: %s\n",
                    configPath->c_str());
      jsonConfig = nlohmann::json{};
      return;
    }

    std::ostringstream buffer;
    buffer << configFile.rdbuf();
    std::string jsonString = buffer.str();

    if (!nlohmann::json::accept(jsonString)) {
      printf_stderr("ERROR: Invalid JSON passed to CAMOU_CONFIG_PATH: %s\n",
                    configPath->c_str());
      jsonConfig = nlohmann::json{};
      return;
    }

    jsonConfig = nlohmann::json::parse(jsonString);
  });

  return jsonConfig;
}

inline const camoucfg::CamoufoxProfile& Profile() {
  static std::once_flag initFlag;
  static camoucfg::CamoufoxProfile profile;

  std::call_once(initFlag, []() {
    if (!profile.fromJson(GetJson())) {
      printf_stderr("ERROR: CAMOU_CONFIG_PATH does not match CamoufoxProfile\n");
      profile = camoucfg::CamoufoxProfile();
    }
  });

  return profile;
}

inline std::vector<std::string> JsonStringList(
    const std::optional<nlohmann::json>& value) {
  std::vector<std::string> result;
  if (!value || !value->is_array()) return result;
  for (const auto& item : *value) {
    result.push_back(item.get<std::string>());
  }
  return result;
}

inline std::vector<std::string> JsonStringListLower(
    const std::optional<nlohmann::json>& value) {
  std::vector<std::string> result = JsonStringList(value);
  for (auto& str : result) {
    std::transform(str.begin(), str.end(), str.begin(),
                   [](unsigned char c) { return std::tolower(c); });
  }
  return result;
}

inline std::optional<std::string> Timezone() { return Profile().getTimezone(); }
inline std::optional<bool> Debug() { return Profile().isDebug(); }
inline std::optional<bool> DisableTheming() {
  return Profile().isDisableTheming();
}
inline std::optional<bool> ShowCursor() { return Profile().isShowcursor(); }

inline std::optional<std::string> NavigatorUserAgent() {
  auto value = Profile().getNavigator();
  return value ? value->getUserAgent() : std::nullopt;
}
inline std::optional<std::string> NavigatorAppVersion() {
  auto value = Profile().getNavigator();
  return value ? value->getAppVersion() : std::nullopt;
}
inline std::optional<std::string> NavigatorPlatform() {
  auto value = Profile().getNavigator();
  return value ? value->getPlatform() : std::nullopt;
}
inline std::optional<std::string> NavigatorOscpu() {
  auto value = Profile().getNavigator();
  return value ? value->getOscpu() : std::nullopt;
}
inline std::optional<std::string> NavigatorLanguage() {
  auto value = Profile().getNavigator();
  return value ? value->getLanguage() : std::nullopt;
}
inline std::optional<uint64_t> NavigatorHardwareConcurrency() {
  auto value = Profile().getNavigator();
  auto hardware = value ? value->getHardwareConcurrency() : std::nullopt;
  return hardware ? std::optional<uint64_t>(static_cast<uint64_t>(*hardware))
                  : std::nullopt;
}
inline std::optional<bool> NavigatorGlobalPrivacyControl() {
  auto value = Profile().getNavigator();
  return value ? value->isGlobalPrivacyControl() : std::nullopt;
}

inline std::optional<std::string> HeaderUserAgent() {
  auto value = Profile().getHeaders();
  return value ? value->getUserAgent() : std::nullopt;
}
inline std::optional<std::string> HeaderAcceptLanguage() {
  auto value = Profile().getHeaders();
  return value ? value->getAcceptLanguage() : std::nullopt;
}
inline std::optional<std::string> HeaderAcceptEncoding() {
  auto value = Profile().getHeaders();
  return value ? value->getAcceptEncoding() : std::nullopt;
}

inline std::optional<int32_t> ScreenHeight() {
  auto value = Profile().getScreen();
  return value ? value->getHeight() : std::nullopt;
}
inline std::optional<int32_t> ScreenWidth() {
  auto value = Profile().getScreen();
  return value ? value->getWidth() : std::nullopt;
}
inline std::optional<int32_t> ScreenAvailTop() {
  auto value = Profile().getScreen();
  return value ? value->getAvailTop() : std::nullopt;
}
inline std::optional<uint32_t> ScreenColorDepth() {
  auto value = Profile().getScreen();
  auto depth = value ? value->getColorDepth() : std::nullopt;
  return depth ? std::optional<uint32_t>(static_cast<uint32_t>(*depth))
               : std::nullopt;
}
inline std::optional<uint32_t> ScreenPixelDepth() {
  auto value = Profile().getScreen();
  auto depth = value ? value->getPixelDepth() : std::nullopt;
  return depth ? std::optional<uint32_t>(static_cast<uint32_t>(*depth))
               : std::nullopt;
}
inline std::optional<double> ScreenPageXOffset() {
  auto value = Profile().getScreen();
  return value ? value->getPageXOffset() : std::nullopt;
}
inline std::optional<double> ScreenPageYOffset() {
  auto value = Profile().getScreen();
  return value ? value->getPageYOffset() : std::nullopt;
}
inline std::optional<std::array<uint32_t, 4>> ScreenAvailRect() {
  auto screen = Profile().getScreen();
  if (!screen) return std::nullopt;
  auto width = screen->getAvailWidth();
  auto height = screen->getAvailHeight();
  if (!width || !height) return std::nullopt;
  return std::array<uint32_t, 4>{
      static_cast<uint32_t>(screen->getAvailLeft().value_or(0)),
      static_cast<uint32_t>(screen->getAvailTop().value_or(0)),
      static_cast<uint32_t>(*width),
      static_cast<uint32_t>(*height),
  };
}
inline std::optional<std::array<int32_t, 4>> ScreenInt32Rect() {
  auto screen = Profile().getScreen();
  if (!screen) return std::nullopt;
  auto width = screen->getWidth();
  auto height = screen->getHeight();
  if (!width || !height) return std::nullopt;
  return std::array<int32_t, 4>{0, 0, *width, *height};
}

inline std::optional<double> WindowInnerWidth() {
  auto value = Profile().getWindow();
  return value ? value->getInnerWidth() : std::nullopt;
}
inline std::optional<double> WindowInnerHeight() {
  auto value = Profile().getWindow();
  return value ? value->getInnerHeight() : std::nullopt;
}
inline std::optional<int32_t> WindowOuterWidth() {
  auto value = Profile().getWindow();
  return value ? value->getOuterWidth() : std::nullopt;
}
inline std::optional<int32_t> WindowOuterHeight() {
  auto value = Profile().getWindow();
  return value ? value->getOuterHeight() : std::nullopt;
}
inline std::optional<int32_t> WindowScreenX() {
  auto value = Profile().getWindow();
  return value ? value->getScreenX() : std::nullopt;
}
inline std::optional<int32_t> WindowScreenY() {
  auto value = Profile().getWindow();
  return value ? value->getScreenY() : std::nullopt;
}
inline std::optional<int32_t> WindowScrollMinX() {
  auto value = Profile().getWindow();
  return value ? value->getScrollMinX() : std::nullopt;
}
inline std::optional<int32_t> WindowScrollMinY() {
  auto value = Profile().getWindow();
  return value ? value->getScrollMinY() : std::nullopt;
}
inline std::optional<int32_t> WindowScrollMaxX() {
  auto value = Profile().getWindow();
  return value ? value->getScrollMaxX() : std::nullopt;
}
inline std::optional<int32_t> WindowScrollMaxY() {
  auto value = Profile().getWindow();
  return value ? value->getScrollMaxY() : std::nullopt;
}
inline std::optional<double> WindowDevicePixelRatio() {
  auto value = Profile().getWindow();
  return value ? value->getDevicePixelRatio() : std::nullopt;
}
inline std::optional<uint32_t> WindowHistoryLength() {
  auto window = Profile().getWindow();
  if (!window) return std::nullopt;
  auto history = window->getHistory();
  if (!history) return std::nullopt;
  auto length = history->getLength();
  return length ? std::optional<uint32_t>(static_cast<uint32_t>(*length))
                : std::nullopt;
}

inline std::optional<bool> BatteryCharging() {
  auto value = Profile().getBattery();
  return value ? value->isCharging() : std::nullopt;
}
inline std::optional<double> BatteryChargingTime() {
  auto value = Profile().getBattery();
  return value ? value->getChargingTime() : std::nullopt;
}
inline std::optional<double> BatteryDischargingTime() {
  auto value = Profile().getBattery();
  return value ? value->getDischargingTime() : std::nullopt;
}
inline std::optional<double> BatteryLevel() {
  auto value = Profile().getBattery();
  return value ? value->getLevel() : std::nullopt;
}

inline std::vector<std::string> FontsFamilies() {
  auto value = Profile().getFonts();
  return value ? JsonStringList(value->getFamilies()) : std::vector<std::string>{};
}
inline std::vector<std::string> FontsFamiliesLower() {
  auto value = Profile().getFonts();
  return value ? JsonStringListLower(value->getFamilies())
               : std::vector<std::string>{};
}
inline std::optional<uint32_t> FontsSpacingSeed() {
  auto value = Profile().getFonts();
  auto seed = value ? value->getSpacingSeed() : std::nullopt;
  return seed ? std::optional<uint32_t>(static_cast<uint32_t>(*seed))
              : std::nullopt;
}

inline std::optional<uint32_t> AudioSeed() {
  auto value = Profile().getAudio();
  auto seed = value ? value->getSeed() : std::nullopt;
  return seed ? std::optional<uint32_t>(static_cast<uint32_t>(*seed))
              : std::nullopt;
}
inline std::optional<uint32_t> CanvasSeed() {
  auto value = Profile().getCanvas();
  auto seed = value ? value->getSeed() : std::nullopt;
  return seed ? std::optional<uint32_t>(static_cast<uint32_t>(*seed))
              : std::nullopt;
}

inline std::optional<double> GeolocationLatitude() {
  auto value = Profile().getGeolocation();
  return value ? value->getLatitude() : std::nullopt;
}
inline std::optional<double> GeolocationLongitude() {
  auto value = Profile().getGeolocation();
  return value ? value->getLongitude() : std::nullopt;
}
inline std::optional<double> GeolocationAccuracy() {
  auto value = Profile().getGeolocation();
  return value ? value->getAccuracy() : std::nullopt;
}

inline std::optional<std::string> LocaleLanguage() {
  auto value = Profile().getLocale();
  return value ? value->getLanguage() : std::nullopt;
}
inline std::optional<std::string> LocaleRegion() {
  auto value = Profile().getLocale();
  return value ? value->getRegion() : std::nullopt;
}
inline std::optional<std::string> LocaleScript() {
  auto value = Profile().getLocale();
  return value ? value->getScript() : std::nullopt;
}
inline std::optional<std::string> LocaleAll() {
  auto value = Profile().getLocale();
  return value ? value->getAll() : std::nullopt;
}

inline std::optional<double> HumanizeMaxTime() {
  auto value = Profile().getHumanize();
  return value ? value->getMaxTime() : std::nullopt;
}
inline std::optional<double> HumanizeMinTime() {
  auto value = Profile().getHumanize();
  return value ? value->getMinTime() : std::nullopt;
}

inline std::optional<uint32_t> AudioContextSampleRate() {
  auto value = Profile().getAudioContext();
  auto sampleRate = value ? value->getSampleRate() : std::nullopt;
  return sampleRate
             ? std::optional<uint32_t>(static_cast<uint32_t>(*sampleRate))
             : std::nullopt;
}
inline std::optional<double> AudioContextOutputLatency() {
  auto value = Profile().getAudioContext();
  return value ? value->getOutputLatency() : std::nullopt;
}
inline std::optional<uint32_t> AudioContextMaxChannelCount() {
  auto value = Profile().getAudioContext();
  auto count = value ? value->getMaxChannelCount() : std::nullopt;
  return count ? std::optional<uint32_t>(static_cast<uint32_t>(*count))
               : std::nullopt;
}

inline std::optional<std::string> WebGlRenderer() {
  auto value = Profile().getWebGl();
  return value ? value->getRenderer() : std::nullopt;
}
inline std::optional<std::string> WebGlVendor() {
  auto value = Profile().getWebGl();
  return value ? value->getVendor() : std::nullopt;
}
inline std::vector<std::string> WebGlSupportedExtensions(bool isWebGL2) {
  auto value = isWebGL2 ? Profile().getWebGl2() : Profile().getWebGl();
  return value ? JsonStringList(value->getSupportedExtensions())
               : std::vector<std::string>{};
}

inline std::optional<bool> VoicesBlockIfNotDefined() {
  auto value = Profile().getVoices();
  return value ? value->isBlockIfNotDefined() : std::nullopt;
}
inline std::optional<bool> VoicesFakeCompletion() {
  auto value = Profile().getVoices();
  return value ? value->isFakeCompletion() : std::nullopt;
}
inline std::optional<double> VoicesFakeCompletionCharsPerSecond() {
  auto value = Profile().getVoices();
  return value ? value->getFakeCompletionCharsPerSecond() : std::nullopt;
}

inline std::optional<bool> MediaDevicesEnabled() {
  auto value = Profile().getMediaDevices();
  return value ? value->isEnabled() : std::nullopt;
}
inline std::optional<uint32_t> MediaDevicesMicros() {
  auto value = Profile().getMediaDevices();
  auto count = value ? value->getMicros() : std::nullopt;
  return count ? std::optional<uint32_t>(static_cast<uint32_t>(*count))
               : std::nullopt;
}
inline std::optional<uint32_t> MediaDevicesWebcams() {
  auto value = Profile().getMediaDevices();
  auto count = value ? value->getWebcams() : std::nullopt;
  return count ? std::optional<uint32_t>(static_cast<uint32_t>(*count))
               : std::nullopt;
}
inline std::optional<uint32_t> MediaDevicesSpeakers() {
  auto value = Profile().getMediaDevices();
  auto count = value ? value->getSpeakers() : std::nullopt;
  return count ? std::optional<uint32_t>(static_cast<uint32_t>(*count))
               : std::nullopt;
}

inline const std::unordered_map<std::string, std::vector<std::string>>&
KeyPaths() {
  static const std::unordered_map<std::string, std::vector<std::string>> paths = {
      {"navigator.userAgent", {"navigator", "userAgent"}},
      {"navigator.doNotTrack", {"navigator", "doNotTrack"}},
      {"navigator.appCodeName", {"navigator", "appCodeName"}},
      {"navigator.appName", {"navigator", "appName"}},
      {"navigator.appVersion", {"navigator", "appVersion"}},
      {"navigator.oscpu", {"navigator", "oscpu"}},
      {"navigator.language", {"navigator", "language"}},
      {"navigator.languages", {"navigator", "languages"}},
      {"navigator.platform", {"navigator", "platform"}},
      {"navigator.hardwareConcurrency", {"navigator", "hardwareConcurrency"}},
      {"navigator.product", {"navigator", "product"}},
      {"navigator.productSub", {"navigator", "productSub"}},
      {"navigator.maxTouchPoints", {"navigator", "maxTouchPoints"}},
      {"navigator.cookieEnabled", {"navigator", "cookieEnabled"}},
      {"navigator.globalPrivacyControl", {"navigator", "globalPrivacyControl"}},
      {"navigator.buildID", {"navigator", "buildID"}},
      {"navigator.onLine", {"navigator", "onLine"}},
      {"screen.availHeight", {"screen", "availHeight"}},
      {"screen.availWidth", {"screen", "availWidth"}},
      {"screen.availTop", {"screen", "availTop"}},
      {"screen.availLeft", {"screen", "availLeft"}},
      {"screen.height", {"screen", "height"}},
      {"screen.width", {"screen", "width"}},
      {"screen.colorDepth", {"screen", "colorDepth"}},
      {"screen.pixelDepth", {"screen", "pixelDepth"}},
      {"screen.pageXOffset", {"screen", "pageXOffset"}},
      {"screen.pageYOffset", {"screen", "pageYOffset"}},
      {"window.scrollMinX", {"window", "scrollMinX"}},
      {"window.scrollMinY", {"window", "scrollMinY"}},
      {"window.scrollMaxX", {"window", "scrollMaxX"}},
      {"window.scrollMaxY", {"window", "scrollMaxY"}},
      {"window.outerHeight", {"window", "outerHeight"}},
      {"window.outerWidth", {"window", "outerWidth"}},
      {"window.innerHeight", {"window", "innerHeight"}},
      {"window.innerWidth", {"window", "innerWidth"}},
      {"window.screenX", {"window", "screenX"}},
      {"window.screenY", {"window", "screenY"}},
      {"window.history.length", {"window", "history", "length"}},
      {"window.devicePixelRatio", {"window", "devicePixelRatio"}},
      {"document.body.clientWidth", {"document", "body", "clientWidth"}},
      {"document.body.clientHeight", {"document", "body", "clientHeight"}},
      {"document.body.clientTop", {"document", "body", "clientTop"}},
      {"document.body.clientLeft", {"document", "body", "clientLeft"}},
      {"headers.User-Agent", {"headers", "User-Agent"}},
      {"headers.Accept-Language", {"headers", "Accept-Language"}},
      {"headers.Accept-Encoding", {"headers", "Accept-Encoding"}},
      {"webrtc:ipv4", {"webrtc", "ipv4"}},
      {"webrtc:ipv6", {"webrtc", "ipv6"}},
      {"webrtc:localipv4", {"webrtc", "localipv4"}},
      {"webrtc:localipv6", {"webrtc", "localipv6"}},
      {"battery:charging", {"battery", "charging"}},
      {"battery:chargingTime", {"battery", "chargingTime"}},
      {"battery:dischargingTime", {"battery", "dischargingTime"}},
      {"battery:level", {"battery", "level"}},
      {"fonts", {"fonts", "families"}},
      {"fonts:spacing_seed", {"fonts", "spacingSeed"}},
      {"audio:seed", {"audio", "seed"}},
      {"canvas:seed", {"canvas", "seed"}},
      {"canvas:aaOffset", {"canvas", "aaOffset"}},
      {"canvas:aaCapOffset", {"canvas", "aaCapOffset"}},
      {"geolocation:latitude", {"geolocation", "latitude"}},
      {"geolocation:longitude", {"geolocation", "longitude"}},
      {"geolocation:accuracy", {"geolocation", "accuracy"}},
      {"locale:language", {"locale", "language"}},
      {"locale:region", {"locale", "region"}},
      {"locale:script", {"locale", "script"}},
      {"locale:all", {"locale", "all"}},
      {"humanize", {"humanize", "enabled"}},
      {"humanize:maxTime", {"humanize", "maxTime"}},
      {"humanize:minTime", {"humanize", "minTime"}},
      {"AudioContext:sampleRate", {"audioContext", "sampleRate"}},
      {"AudioContext:outputLatency", {"audioContext", "outputLatency"}},
      {"AudioContext:maxChannelCount", {"audioContext", "maxChannelCount"}},
      {"webGl:renderer", {"webGl", "renderer"}},
      {"webGl:vendor", {"webGl", "vendor"}},
      {"webGl:supportedExtensions", {"webGl", "supportedExtensions"}},
      {"webGl:parameters", {"webGl", "parameters"}},
      {"webGl:parameters:blockIfNotDefined",
       {"webGl", "parametersBlockIfNotDefined"}},
      {"webGl:shaderPrecisionFormats", {"webGl", "shaderPrecisionFormats"}},
      {"webGl:shaderPrecisionFormats:blockIfNotDefined",
       {"webGl", "shaderPrecisionFormatsBlockIfNotDefined"}},
      {"webGl:contextAttributes", {"webGl", "contextAttributes"}},
      {"webGl2:supportedExtensions", {"webGl2", "supportedExtensions"}},
      {"webGl2:parameters", {"webGl2", "parameters"}},
      {"webGl2:parameters:blockIfNotDefined",
       {"webGl2", "parametersBlockIfNotDefined"}},
      {"webGl2:shaderPrecisionFormats", {"webGl2", "shaderPrecisionFormats"}},
      {"webGl2:shaderPrecisionFormats:blockIfNotDefined",
       {"webGl2", "shaderPrecisionFormatsBlockIfNotDefined"}},
      {"webGl2:contextAttributes", {"webGl2", "contextAttributes"}},
      {"voices", {"voices", "items"}},
      {"voices:blockIfNotDefined", {"voices", "blockIfNotDefined"}},
      {"voices:fakeCompletion", {"voices", "fakeCompletion"}},
      {"voices:fakeCompletion:charsPerSecond",
       {"voices", "fakeCompletionCharsPerSecond"}},
      {"mediaDevices:micros", {"mediaDevices", "micros"}},
      {"mediaDevices:webcams", {"mediaDevices", "webcams"}},
      {"mediaDevices:speakers", {"mediaDevices", "speakers"}},
      {"mediaDevices:enabled", {"mediaDevices", "enabled"}},
  };
  return paths;
}

inline std::optional<nlohmann::json> GetValue(const std::string& key) {
  const auto& data = GetJson();
  auto path = KeyPaths().find(key);
  if (path == KeyPaths().end()) return std::nullopt;

  const nlohmann::json* cursor = &data;
  for (const auto& part : path->second) {
    if (!cursor->is_object() || !cursor->contains(part)) return std::nullopt;
    cursor = &((*cursor)[part]);
  }
  return *cursor;
}

inline std::optional<std::string> GetString(const std::string& key) {
  auto value = GetValue(key);
  if (!value) return std::nullopt;
  return value->get<std::string>();
}

inline std::vector<std::string> GetStringList(const std::string& key) {
  std::vector<std::string> result;
  auto value = GetValue(key);
  if (!value || !value->is_array()) return {};
  for (const auto& item : *value) {
    result.push_back(item.get<std::string>());
  }
  return result;
}

inline std::vector<std::string> GetStringListLower(const std::string& key) {
  std::vector<std::string> result = GetStringList(key);
  for (auto& str : result) {
    std::transform(str.begin(), str.end(), str.begin(),
                   [](unsigned char c) { return std::tolower(c); });
  }
  return result;
}

template <typename T>
inline std::optional<T> GetUintImpl(const std::string& key) {
  auto value = GetValue(key);
  if (!value) return std::nullopt;
  if (value->is_number_unsigned()) return value->get<T>();
  printf_stderr("ERROR: Value for key '%s' is not an unsigned integer\n",
                key.c_str());
  return std::nullopt;
}

inline std::optional<uint64_t> GetUint64(const std::string& key) {
  return GetUintImpl<uint64_t>(key);
}

inline std::optional<uint32_t> GetUint32(const std::string& key) {
  return GetUintImpl<uint32_t>(key);
}

inline std::optional<int32_t> GetInt32(const std::string& key) {
  auto value = GetValue(key);
  if (!value) return std::nullopt;
  if (value->is_number_integer()) return value->get<int32_t>();
  printf_stderr("ERROR: Value for key '%s' is not an integer\n", key.c_str());
  return std::nullopt;
}

inline std::optional<double> GetDouble(const std::string& key) {
  auto value = GetValue(key);
  if (!value) return std::nullopt;
  if (value->is_number_float()) return value->get<double>();
  if (value->is_number_unsigned() || value->is_number_integer())
    return static_cast<double>(value->get<int64_t>());
  printf_stderr("ERROR: Value for key '%s' is not a double\n", key.c_str());
  return std::nullopt;
}

inline std::optional<bool> GetBool(const std::string& key) {
  auto value = GetValue(key);
  if (!value) return std::nullopt;
  if (value->is_boolean()) return value->get<bool>();
  printf_stderr("ERROR: Value for key '%s' is not a boolean\n", key.c_str());
  return std::nullopt;
}

inline bool CheckBool(const std::string& key) {
  return GetBool(key).value_or(false);
}

inline std::optional<std::array<uint32_t, 4>> GetRect(
    const std::string& left, const std::string& top, const std::string& width,
    const std::string& height) {
  std::array<std::optional<uint32_t>, 4> values = {
      GetUint32(left).value_or(0), GetUint32(top).value_or(0), GetUint32(width),
      GetUint32(height)};

  if (!values[2].has_value() || !values[3].has_value()) {
    if (values[2].has_value() ^ values[3].has_value())
      printf_stderr(
          "Both %s and %s must be provided. Using default behavior.\n",
          height.c_str(), width.c_str());
    return std::nullopt;
  }

  std::array<uint32_t, 4> result;
  std::transform(values.begin(), values.end(), result.begin(),
                 [](const auto& value) { return value.value(); });

  return result;
}

inline std::optional<std::array<int32_t, 4>> GetInt32Rect(
    const std::string& left, const std::string& top, const std::string& width,
    const std::string& height) {
  if (auto optValue = GetRect(left, top, width, height)) {
    std::array<int32_t, 4> result;
    std::transform(optValue->begin(), optValue->end(), result.begin(),
                   [](const auto& val) { return static_cast<int32_t>(val); });
    return result;
  }
  return std::nullopt;
}

inline std::optional<nlohmann::json> GetNested(const std::string& domain,
                                               std::string keyStr) {
  auto data = GetValue(domain);
  if (!data || !data->is_object()) return std::nullopt;
  if (!data->contains(keyStr)) return std::nullopt;
  return (*data)[keyStr];
}

template <typename T>
inline std::optional<T> GetAttribute(const std::string attrib, bool isWebGL2) {
  auto webGl = isWebGL2 ? Profile().getWebGl2() : Profile().getWebGl();
  if (!webGl) return std::nullopt;
  auto contextAttributes = webGl->getContextAttributes();
  if (!contextAttributes) return std::nullopt;
  auto json = contextAttributes->toJson();
  if (!json.contains(attrib)) return std::nullopt;
  return json[attrib].get<T>();
}

inline std::optional<
    std::variant<int64_t, bool, double, std::string, std::nullptr_t>>
GLParam(uint32_t pname, bool isWebGL2) {
  auto webGl = isWebGL2 ? Profile().getWebGl2() : Profile().getWebGl();
  if (!webGl) return std::nullopt;
  auto parameters = webGl->getParameters();
  if (!parameters || !parameters->is_object()) return std::nullopt;
  auto key = std::to_string(pname);
  if (!parameters->contains(key)) return std::nullopt;
  auto data = (*parameters)[key];
  if (data.is_null()) return std::nullptr_t();
  if (data.is_number_integer()) return data.get<int64_t>();
  if (data.is_boolean()) return data.get<bool>();
  if (data.is_number_float()) return data.get<double>();
  if (data.is_string()) return data.get<std::string>();
  return std::nullopt;
}

template <typename T>
inline T MParamGL(uint32_t pname, T defaultValue, bool isWebGL2) {
  auto webGl = isWebGL2 ? Profile().getWebGl2() : Profile().getWebGl();
  if (!webGl) return defaultValue;
  auto parameters = webGl->getParameters();
  if (!parameters || !parameters->is_object()) return defaultValue;
  auto key = std::to_string(pname);
  if (!parameters->contains(key)) return defaultValue;
  return (*parameters)[key].get<T>();
}

template <typename T>
inline std::vector<T> MParamGLVector(uint32_t pname,
                                     std::vector<T> defaultValue,
                                     bool isWebGL2) {
  auto webGl = isWebGL2 ? Profile().getWebGl2() : Profile().getWebGl();
  if (!webGl) return defaultValue;
  auto parameters = webGl->getParameters();
  if (!parameters || !parameters->is_object()) return defaultValue;
  auto key = std::to_string(pname);
  if (!parameters->contains(key)) return defaultValue;
  auto value = (*parameters)[key];
  if (!value.is_array()) return defaultValue;
  std::array<T, 4UL> result = value.get<std::array<T, 4UL>>();
  return std::vector<T>(result.begin(), result.end());
}

inline std::optional<std::array<int32_t, 3UL>> MShaderData(
    uint32_t shaderType, uint32_t precisionType, bool isWebGL2) {
  auto webGl = isWebGL2 ? Profile().getWebGl2() : Profile().getWebGl();
  if (!webGl) return std::nullopt;
  auto shaderPrecisionFormats = webGl->getShaderPrecisionFormats();
  if (!shaderPrecisionFormats || !shaderPrecisionFormats->is_object())
    return std::nullopt;

  std::string valueName =
      std::to_string(shaderType) + "," + std::to_string(precisionType);
  if (!shaderPrecisionFormats->contains(valueName)) return std::nullopt;
  auto data = (*shaderPrecisionFormats)[valueName];
  if (!data.contains("rangeMin") || !data.contains("rangeMax") ||
      !data.contains("precision")) {
    return std::nullopt;
  }
  return std::array<int32_t, 3U>{data["rangeMin"].get<int32_t>(),
                                 data["rangeMax"].get<int32_t>(),
                                 data["precision"].get<int32_t>()};
}

inline std::optional<
    std::vector<std::tuple<std::string, std::string, std::string, bool, bool>>>
MVoices() {
  auto voicesProfile = Profile().getVoices();
  if (!voicesProfile) return std::nullopt;
  auto data = voicesProfile->getItems();
  if (!data || !data->is_array()) return std::nullopt;

  std::vector<std::tuple<std::string, std::string, std::string, bool, bool>>
      voices;
  for (const auto& voice : *data) {
    if (!voice.is_object()) continue;
    if (!voice.contains("lang") || !voice.contains("name") ||
        !voice.contains("voiceUri") || !voice.contains("isDefault") ||
        !voice.contains("isLocalService")) {
      continue;
    }

    voices.emplace_back(
        voice["lang"].get<std::string>(), voice["name"].get<std::string>(),
        voice["voiceUri"].get<std::string>(), voice["isDefault"].get<bool>(),
        voice["isLocalService"].get<bool>());
  }
  return voices;
}

}  // namespace MaskConfig

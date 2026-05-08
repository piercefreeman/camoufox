#include "KeyboardRuntime.hpp"
#include "MouseRuntime.hpp"
#include "RuntimeWeights.hpp"
#include "json.hpp"

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cstdlib>
#include <iomanip>
#include <iostream>
#include <limits>
#include <map>
#include <numeric>
#include <optional>
#include <set>
#include <sstream>
#include <string>
#include <utility>
#include <vector>

namespace {

struct Options {
  std::string mouseModel;
  std::string keyboardModel;
  int mouseMaxSteps = 128;
  double mouseClickThreshold = 0.98;
  double mouseMinDtMs = 4.0;
  double mousePathCurveSigma = 0.04;
  std::uint32_t mouseRandomSeed = 13;
  int keyboardMaxSteps = 256;
  int keyboardStructuredExtraSteps = 6;
  double keyboardCanonicalBias = 3.0;
  double keyboardLearnedTypoThreshold = 0.2;
  int keyboardMaxTypos = 2;
  bool keyboardSampleTypos = true;
  double keyboardTimingJitterSigma = 0.22;
  double keyboardTimingTemperature = 0.25;
  double keyboardPauseProbability = 0.0;
  double keyboardPauseMeanMs = 35.0;
  std::uint32_t keyboardRandomSeed = 13;
  bool includeVectors = false;
};

struct MouseCase {
  std::string name;
  double fromX;
  double fromY;
  double toX;
  double toY;
  bool clickAtEnd;
};

struct KeyboardCase {
  std::string name;
  std::string initial;
  std::string final;
};

bool isOption(const std::string& arg, const std::string& name) {
  return arg == name;
}

std::optional<std::string> nextValue(int& index, int argc, char** argv) {
  if (index + 1 >= argc) return std::nullopt;
  ++index;
  return std::string(argv[index]);
}

int usage(const char* binary) {
  std::cerr
      << "usage: " << binary
      << " --mouse-model <mouse.safetensors>"
      << " --keyboard-model <keyboard.safetensors> [options]\n\n"
      << "options:\n"
      << "  --mouse-max-steps <int>                 default 128\n"
      << "  --mouse-click-threshold <float>         default 0.98\n"
      << "  --mouse-min-dt-ms <float>               default 4.0\n"
      << "  --mouse-path-curve-sigma <float>        default 0.04\n"
      << "  --mouse-random-seed <int>               default 13\n"
      << "  --keyboard-max-steps <int>              default 256\n"
      << "  --keyboard-structured-extra-steps <int> default 6\n"
      << "  --keyboard-canonical-bias <float>       default 3.0\n"
      << "  --keyboard-learned-typo-threshold <float> default 0.2\n"
      << "  --keyboard-max-typos <int>              default 2\n"
      << "  --no-keyboard-sample-typos              disable typo sampling\n"
      << "  --keyboard-timing-jitter-sigma <float>  default 0.22\n"
      << "  --keyboard-timing-temperature <float>   default 0.25\n"
      << "  --keyboard-pause-probability <float>    default 0.0\n"
      << "  --keyboard-pause-mean-ms <float>        default 35.0\n"
      << "  --keyboard-random-seed <int>            default 13\n"
      << "  --include-vectors                       include hidden/input vectors\n";
  return 2;
}

std::optional<Options> parseOptions(int argc, char** argv) {
  Options options;
  for (int i = 1; i < argc; ++i) {
    std::string arg(argv[i]);
    auto value = [&]() -> std::optional<std::string> {
      return nextValue(i, argc, argv);
    };

    if (isOption(arg, "--mouse-model")) {
      auto next = value();
      if (!next) return std::nullopt;
      options.mouseModel = *next;
    } else if (isOption(arg, "--keyboard-model")) {
      auto next = value();
      if (!next) return std::nullopt;
      options.keyboardModel = *next;
    } else if (isOption(arg, "--mouse-max-steps")) {
      auto next = value();
      if (!next) return std::nullopt;
      options.mouseMaxSteps = std::stoi(*next);
    } else if (isOption(arg, "--mouse-click-threshold")) {
      auto next = value();
      if (!next) return std::nullopt;
      options.mouseClickThreshold = std::stod(*next);
    } else if (isOption(arg, "--mouse-min-dt-ms")) {
      auto next = value();
      if (!next) return std::nullopt;
      options.mouseMinDtMs = std::stod(*next);
    } else if (isOption(arg, "--mouse-path-curve-sigma")) {
      auto next = value();
      if (!next) return std::nullopt;
      options.mousePathCurveSigma = std::stod(*next);
    } else if (isOption(arg, "--mouse-random-seed")) {
      auto next = value();
      if (!next) return std::nullopt;
      options.mouseRandomSeed =
          static_cast<std::uint32_t>(std::stoul(*next));
    } else if (isOption(arg, "--keyboard-max-steps")) {
      auto next = value();
      if (!next) return std::nullopt;
      options.keyboardMaxSteps = std::stoi(*next);
    } else if (isOption(arg, "--keyboard-structured-extra-steps")) {
      auto next = value();
      if (!next) return std::nullopt;
      options.keyboardStructuredExtraSteps = std::stoi(*next);
    } else if (isOption(arg, "--keyboard-canonical-bias")) {
      auto next = value();
      if (!next) return std::nullopt;
      options.keyboardCanonicalBias = std::stod(*next);
    } else if (isOption(arg, "--keyboard-learned-typo-threshold")) {
      auto next = value();
      if (!next) return std::nullopt;
      options.keyboardLearnedTypoThreshold = std::stod(*next);
    } else if (isOption(arg, "--keyboard-max-typos")) {
      auto next = value();
      if (!next) return std::nullopt;
      options.keyboardMaxTypos = std::stoi(*next);
    } else if (isOption(arg, "--keyboard-sample-typos")) {
      options.keyboardSampleTypos = true;
    } else if (isOption(arg, "--no-keyboard-sample-typos")) {
      options.keyboardSampleTypos = false;
    } else if (isOption(arg, "--keyboard-timing-jitter-sigma")) {
      auto next = value();
      if (!next) return std::nullopt;
      options.keyboardTimingJitterSigma = std::stod(*next);
    } else if (isOption(arg, "--keyboard-timing-temperature")) {
      auto next = value();
      if (!next) return std::nullopt;
      options.keyboardTimingTemperature = std::stod(*next);
    } else if (isOption(arg, "--keyboard-pause-probability")) {
      auto next = value();
      if (!next) return std::nullopt;
      options.keyboardPauseProbability = std::stod(*next);
    } else if (isOption(arg, "--keyboard-pause-mean-ms")) {
      auto next = value();
      if (!next) return std::nullopt;
      options.keyboardPauseMeanMs = std::stod(*next);
    } else if (isOption(arg, "--keyboard-random-seed")) {
      auto next = value();
      if (!next) return std::nullopt;
      options.keyboardRandomSeed =
          static_cast<std::uint32_t>(std::stoul(*next));
    } else if (isOption(arg, "--include-vectors")) {
      options.includeVectors = true;
    } else {
      return std::nullopt;
    }
  }

  if (options.mouseModel.empty() || options.keyboardModel.empty()) {
    return std::nullopt;
  }
  return options;
}

nlohmann::json loadMetadata(const std::string& path) {
  auto weights = rotundacfg::RuntimeWeights::Load(path);
  if (!weights) return nlohmann::json::object();
  auto metadata = weights->rotundaMetadata();
  return metadata ? *metadata : nlohmann::json::object();
}

std::vector<std::string> mouseActionNames(const nlohmann::json& metadata) {
  std::vector<std::string> names;
  if (metadata.contains("actions") && metadata["actions"].is_array()) {
    for (const auto& action : metadata["actions"]) {
      names.push_back(action.get<std::string>());
    }
  }
  return names;
}

std::map<int, std::string> keyboardActionNames(const nlohmann::json& metadata) {
  std::map<int, std::string> names;
  if (metadata.contains("idToAction") && metadata["idToAction"].is_object()) {
    for (auto it = metadata["idToAction"].begin();
         it != metadata["idToAction"].end(); ++it) {
      names[std::stoi(it.key())] = it.value().get<std::string>();
    }
  }
  return names;
}

std::string actionName(int id, const std::vector<std::string>& names) {
  if (id >= 0 && static_cast<size_t>(id) < names.size()) return names[id];
  return "action_" + std::to_string(id);
}

std::string actionName(int id, const std::map<int, std::string>& names) {
  auto it = names.find(id);
  if (it != names.end()) return it->second;
  return id < 0 ? "" : "action_" + std::to_string(id);
}

std::vector<int> topKIndices(const std::vector<double>& values, int k) {
  std::vector<int> indices(values.size());
  std::iota(indices.begin(), indices.end(), 0);
  std::partial_sort(indices.begin(),
                    indices.begin() + std::min<int>(k, indices.size()),
                    indices.end(), [&](int left, int right) {
                      return values[static_cast<size_t>(left)] >
                             values[static_cast<size_t>(right)];
                    });
  if (static_cast<int>(indices.size()) > k) indices.resize(k);
  return indices;
}

nlohmann::json topLogits(const std::vector<double>& values, int k) {
  nlohmann::json output = nlohmann::json::array();
  for (int id : topKIndices(values, k)) {
    output.push_back({{"id", id}, {"logit", values[static_cast<size_t>(id)]}});
  }
  return output;
}

nlohmann::json topLogits(const std::vector<double>& values, int k,
                         const std::vector<std::string>& names) {
  nlohmann::json output = nlohmann::json::array();
  for (int id : topKIndices(values, k)) {
    output.push_back({{"id", id},
                      {"action", actionName(id, names)},
                      {"logit", values[static_cast<size_t>(id)]}});
  }
  return output;
}

nlohmann::json topLogits(const std::vector<double>& values, int k,
                         const std::map<int, std::string>& names) {
  nlohmann::json output = nlohmann::json::array();
  for (int id : topKIndices(values, k)) {
    output.push_back({{"id", id},
                      {"action", actionName(id, names)},
                      {"logit", values[static_cast<size_t>(id)]}});
  }
  return output;
}

nlohmann::json numericSummary(std::vector<double> values) {
  nlohmann::json output;
  output["count"] = values.size();
  if (values.empty()) {
    output["min"] = nullptr;
    output["max"] = nullptr;
    output["mean"] = nullptr;
    output["median"] = nullptr;
    output["stddev"] = nullptr;
    output["cv"] = nullptr;
    return output;
  }

  std::sort(values.begin(), values.end());
  double sum = std::accumulate(values.begin(), values.end(), 0.0);
  double mean = sum / static_cast<double>(values.size());
  double sq = 0.0;
  for (double value : values) sq += (value - mean) * (value - mean);
  double stddev = std::sqrt(sq / static_cast<double>(values.size()));
  auto percentile = [&](double p) {
    if (values.size() == 1) return values.front();
    double index = p * static_cast<double>(values.size() - 1);
    size_t lo = static_cast<size_t>(std::floor(index));
    size_t hi = static_cast<size_t>(std::ceil(index));
    double alpha = index - static_cast<double>(lo);
    return values[lo] * (1.0 - alpha) + values[hi] * alpha;
  };

  output["min"] = values.front();
  output["p10"] = percentile(0.10);
  output["median"] = percentile(0.50);
  output["p90"] = percentile(0.90);
  output["max"] = values.back();
  output["mean"] = mean;
  output["stddev"] = stddev;
  output["cv"] = std::abs(mean) < 1e-9 ? nullptr : nlohmann::json(stddev / std::abs(mean));
  return output;
}

double distance(double ax, double ay, double bx, double by) {
  return std::hypot(bx - ax, by - ay);
}

double angleBetween(double ax, double ay, double bx, double by) {
  double la = std::hypot(ax, ay);
  double lb = std::hypot(bx, by);
  if (la <= 1e-9 || lb <= 1e-9) return 0.0;
  double dot = (ax * bx + ay * by) / (la * lb);
  dot = std::max(-1.0, std::min(1.0, dot));
  return std::acos(dot) * 180.0 / 3.14159265358979323846;
}

nlohmann::json mousePointJson(const rotundacfg::MouseTrajectoryPoint& point,
                              const std::vector<std::string>& actions) {
  return {{"x", point.x},
          {"y", point.y},
          {"dtMs", point.dtMs},
          {"action", point.action},
          {"actionName", actionName(point.action, actions)}};
}

nlohmann::json summarizeMouseCase(
    const MouseCase& testCase, const rotundacfg::MouseRuntimeTrace& trace) {
  std::vector<double> dts;
  std::vector<double> speeds;
  std::vector<double> segments;
  std::vector<double> turns;
  std::set<std::pair<int, int>> uniqueCoords;

  double totalMs = 0.0;
  double pathLength = 0.0;
  double prevX = testCase.fromX;
  double prevY = testCase.fromY;
  double prevDx = 0.0;
  double prevDy = 0.0;
  bool hasPrevSegment = false;
  double maxAbsPerpNorm = 0.0;
  double maxAbsPerpPx = 0.0;
  double directDistance =
      distance(testCase.fromX, testCase.fromY, testCase.toX, testCase.toY);
  int zeroDtCount = 0;
  int sub5MsDtCount = 0;

  for (const auto& point : trace.plan) {
    totalMs += point.dtMs;
    dts.push_back(point.dtMs);
    if (point.dtMs <= 1e-9) ++zeroDtCount;
    if (point.dtMs < 5.0) ++sub5MsDtCount;
    double segment = distance(prevX, prevY, point.x, point.y);
    pathLength += segment;
    segments.push_back(segment);
    speeds.push_back(point.dtMs <= 1e-9 ? 0.0 : segment * 1000.0 / point.dtMs);
    uniqueCoords.insert({static_cast<int>(std::round(point.x * 10.0)),
                         static_cast<int>(std::round(point.y * 10.0))});
    double dx = point.x - prevX;
    double dy = point.y - prevY;
    if (hasPrevSegment) turns.push_back(angleBetween(prevDx, prevDy, dx, dy));
    prevDx = dx;
    prevDy = dy;
    hasPrevSegment = true;
    prevX = point.x;
    prevY = point.y;
  }
  for (const auto& step : trace.steps) {
    maxAbsPerpNorm = std::max(maxAbsPerpNorm, std::abs(step.statePerp));
  }
  maxAbsPerpPx = maxAbsPerpNorm * std::max(1.0, directDistance);

  nlohmann::json output;
  output["pointCount"] = trace.plan.size();
  output["traceStepCount"] = trace.steps.size();
  output["usedFallback"] = trace.usedFallback;
  output["totalMs"] = totalMs;
  output["directDistancePx"] = directDistance;
  output["pathLengthPx"] = pathLength;
  std::optional<double> straightness;
  if (directDistance > 1e-9) straightness = pathLength / directDistance;
  output["straightnessRatio"] =
      straightness ? nlohmann::json(*straightness) : nlohmann::json(nullptr);
  output["averageSpeedPxPerSec"] =
      totalMs <= 1e-9 ? nullptr : nlohmann::json(pathLength * 1000.0 / totalMs);
  output["maxAbsPerpNormalized"] = maxAbsPerpNorm;
  output["maxAbsPerpPx"] = maxAbsPerpPx;
  output["uniqueRoundedCoordCount"] = uniqueCoords.size();
  output["zeroDtCount"] = zeroDtCount;
  output["sub5MsDtCount"] = sub5MsDtCount;
  output["linearPathFlag"] =
      trace.plan.size() >= 4 && straightness &&
      *straightness < 1.05 &&
      maxAbsPerpPx < std::max(8.0, directDistance * 0.08);
  output["slowPathFlag"] =
      totalMs > 0.0 && pathLength * 1000.0 / totalMs < 800.0;
  output["dtMs"] = numericSummary(dts);
  output["segmentPx"] = numericSummary(segments);
  output["speedPxPerSec"] = numericSummary(speeds);
  output["turnDegrees"] = numericSummary(turns);
  if (!trace.plan.empty()) {
    output["terminalAction"] = trace.plan.back().action;
    output["terminalX"] = trace.plan.back().x;
    output["terminalY"] = trace.plan.back().y;
  }
  return output;
}

nlohmann::json mouseCaseJson(
    const MouseCase& testCase, const rotundacfg::MouseRuntimeTrace& trace,
    const std::vector<std::string>& actions, bool includeVectors) {
  nlohmann::json output;
  output["name"] = testCase.name;
  output["input"] = {{"fromX", testCase.fromX},
                     {"fromY", testCase.fromY},
                     {"toX", testCase.toX},
                     {"toY", testCase.toY},
                     {"clickAtEnd", testCase.clickAtEnd}};
  output["summary"] = summarizeMouseCase(testCase, trace);
  output["steps"] = nlohmann::json::array();

  double prevX = testCase.fromX;
  double prevY = testCase.fromY;
  double prevAlong = 0.0;
  double prevPerp = 0.0;
  for (const auto& step : trace.steps) {
    double segment = distance(prevX, prevY, step.x, step.y);
    nlohmann::json row = {
        {"step", step.step},
        {"x", step.x},
        {"y", step.y},
        {"dtMs", step.dtMs},
        {"segmentPx", segment},
        {"speedPxPerSec", step.dtMs <= 1e-9 ? 0.0 : segment * 1000.0 / step.dtMs},
        {"distanceToTargetPx", distance(step.x, step.y, testCase.toX, testCase.toY)},
        {"stateAlong", step.stateAlong},
        {"statePerp", step.statePerp},
        {"deltaAlong", step.stateAlong - prevAlong},
        {"deltaPerp", step.statePerp - prevPerp},
        {"rawAction", step.rawAction},
        {"rawActionName", actionName(step.rawAction, actions)},
        {"action", step.action},
        {"actionName", actionName(step.action, actions)},
        {"terminal", step.terminal},
        {"dtHead", step.dtHead.empty() ? nullptr : nlohmann::json(step.dtHead[0])},
        {"posHead", step.posHead},
        {"topActionLogits", topLogits(step.actionHead, 5, actions)},
    };
    if (includeVectors) {
      row["previous"] = step.previous;
      row["decoderInput"] = step.decoderInput;
      row["hidden"] = step.hidden;
      row["actionHead"] = step.actionHead;
    }
    output["steps"].push_back(std::move(row));
    prevX = step.x;
    prevY = step.y;
    prevAlong = step.stateAlong;
    prevPerp = step.statePerp;
  }

  output["plan"] = nlohmann::json::array();
  for (const auto& point : trace.plan) {
    output["plan"].push_back(mousePointJson(point, actions));
  }
  if (includeVectors) {
    output["condition"] = trace.condition;
    output["embedding"] = trace.embedding;
  }
  return output;
}

nlohmann::json stepKindCounts(
    const std::vector<rotundacfg::KeyboardRuntimeRow>& rows) {
  std::map<std::string, int> counts;
  for (const auto& row : rows) ++counts[row.stepKind];
  nlohmann::json output = nlohmann::json::object();
  for (const auto& [key, value] : counts) output[key] = value;
  return output;
}

nlohmann::json summarizeKeyboardCase(
    const KeyboardCase& testCase,
    const rotundacfg::KeyboardRuntimeTrace& trace) {
  std::vector<double> dts;
  std::vector<double> insertDts;
  std::vector<double> spaceDts;
  std::vector<double> afterSpaceDts;
  std::vector<double> afterNonSpaceInsertDts;
  std::vector<double> nonSpaceInsertDts;
  std::set<int> roundedDtMs;
  int learnedTypos = 0;
  int repairs = 0;
  int backspaces = 0;
  int longestRoundedRun = 0;
  int currentRun = 0;
  int previousRounded = std::numeric_limits<int>::min();
  int zeroDtCount = 0;
  int sub5MsDtCount = 0;
  std::string previousAction;

  for (const auto& row : trace.rows) {
    dts.push_back(row.dtMs);
    if (row.dtMs <= 1e-9) ++zeroDtCount;
    if (row.dtMs < 5.0) ++sub5MsDtCount;
    int rounded = static_cast<int>(std::round(row.dtMs));
    roundedDtMs.insert(rounded);
    if (rounded == previousRounded) {
      ++currentRun;
    } else {
      currentRun = 1;
      previousRounded = rounded;
    }
    longestRoundedRun = std::max(longestRoundedRun, currentRun);

    if (row.stepKind == "learned_typo") ++learnedTypos;
    if (row.stepKind == "model_repair" || row.stepKind == "repair") ++repairs;
    if (row.action == "<BACKSPACE>") {
      ++backspaces;
    } else {
      insertDts.push_back(row.dtMs);
      if (previousAction == " ") {
        afterSpaceDts.push_back(row.dtMs);
      } else if (!previousAction.empty() && previousAction != "<BACKSPACE>" &&
                 previousAction != "\n") {
        afterNonSpaceInsertDts.push_back(row.dtMs);
      }
      if (row.action == " ") {
        spaceDts.push_back(row.dtMs);
      } else {
        nonSpaceInsertDts.push_back(row.dtMs);
      }
    }
    previousAction = row.action;
  }

  double totalMs = trace.rows.empty() ? 0.0 : trace.rows.back().offsetMs;
  nlohmann::json insertStats = numericSummary(insertDts);
  nlohmann::json spaceStats = numericSummary(spaceDts);
  nlohmann::json afterSpaceStats = numericSummary(afterSpaceDts);
  nlohmann::json afterNonSpaceStats = numericSummary(afterNonSpaceInsertDts);
  nlohmann::json nonSpaceStats = numericSummary(nonSpaceInsertDts);
  nlohmann::json output;
  output["rowCount"] = trace.rows.size();
  output["traceStepCount"] = trace.steps.size();
  output["targetLength"] = testCase.final.size();
  output["totalMs"] = totalMs;
  output["charactersPerSecond"] =
      totalMs <= 1e-9 ? nullptr
                      : nlohmann::json(static_cast<double>(testCase.final.size()) *
                                       1000.0 / totalMs);
  output["minimumSteps"] = trace.minimumSteps;
  output["effectiveMaxSteps"] = trace.effectiveMaxSteps;
  output["predictedPressCount"] = trace.predictedPressCount;
  output["usedPredictedPressCount"] = trace.usedPredictedPressCount;
  output["dtMs"] = numericSummary(dts);
  output["insertDtMs"] = insertStats;
  output["spaceDtMs"] = spaceStats;
  output["afterSpaceDtMs"] = afterSpaceStats;
  output["afterNonSpaceInsertDtMs"] = afterNonSpaceStats;
  output["nonSpaceInsertDtMs"] = nonSpaceStats;
  if (!spaceDts.empty() && !nonSpaceInsertDts.empty()) {
    double spaceMean = spaceStats["mean"].get<double>();
    double nonSpaceMean = nonSpaceStats["mean"].get<double>();
    output["spaceToNonSpaceMeanDtRatio"] =
        std::abs(nonSpaceMean) < 1e-9 ? nullptr : nlohmann::json(spaceMean / nonSpaceMean);
  } else {
    output["spaceToNonSpaceMeanDtRatio"] = nullptr;
  }
  if (!afterSpaceDts.empty() && !afterNonSpaceInsertDts.empty()) {
    double afterSpaceMean = afterSpaceStats["mean"].get<double>();
    double afterNonSpaceMean = afterNonSpaceStats["mean"].get<double>();
    output["afterSpaceToAfterNonSpaceMeanDtRatio"] =
        std::abs(afterNonSpaceMean) < 1e-9
            ? nullptr
            : nlohmann::json(afterSpaceMean / afterNonSpaceMean);
  } else {
    output["afterSpaceToAfterNonSpaceMeanDtRatio"] = nullptr;
  }
  output["uniqueRoundedDtMsCount"] = roundedDtMs.size();
  output["longestRepeatedRoundedDtRun"] = longestRoundedRun;
  output["zeroDtCount"] = zeroDtCount;
  output["sub5MsDtCount"] = sub5MsDtCount;
  output["learnedTypoCount"] = learnedTypos;
  output["repairCount"] = repairs;
  output["backspaceCount"] = backspaces;
  output["stepKindCounts"] = stepKindCounts(trace.rows);
  output["spacePauseFlag"] =
      output["spaceToNonSpaceMeanDtRatio"].is_number() &&
      output["spaceToNonSpaceMeanDtRatio"].get<double>() > 1.15;
  output["afterSpacePauseFlag"] =
      output["afterSpaceToAfterNonSpaceMeanDtRatio"].is_number() &&
      output["afterSpaceToAfterNonSpaceMeanDtRatio"].get<double>() > 1.15;
  output["uniformTimingFlag"] =
      output["dtMs"]["cv"].is_number() && output["dtMs"]["cv"].get<double>() < 0.15;
  output["reachedTarget"] =
      trace.rows.empty() ? testCase.initial == testCase.final
                         : trace.rows.back().textAfter == testCase.final;
  return output;
}

nlohmann::json validActionNames(const std::vector<int>& ids,
                                const std::map<int, std::string>& actions) {
  nlohmann::json output = nlohmann::json::array();
  for (int id : ids) {
    output.push_back({{"id", id}, {"action", actionName(id, actions)}});
  }
  return output;
}

double vectorAt(const std::vector<double>& values, int index) {
  if (index < 0 || static_cast<size_t>(index) >= values.size()) {
    return std::numeric_limits<double>::quiet_NaN();
  }
  return values[static_cast<size_t>(index)];
}

std::string tail(const std::string& value, size_t count) {
  if (value.size() <= count) return value;
  return value.substr(value.size() - count);
}

nlohmann::json keyboardCaseJson(
    const KeyboardCase& testCase,
    const rotundacfg::KeyboardRuntimeTrace& trace,
    const std::map<int, std::string>& actions, bool includeVectors) {
  nlohmann::json output;
  output["name"] = testCase.name;
  output["input"] = {{"initial", testCase.initial}, {"final", testCase.final}};
  output["summary"] = summarizeKeyboardCase(testCase, trace);
  output["conditionIds"] = trace.conditionIds;
  output["rows"] = nlohmann::json::array();
  for (const auto& row : trace.rows) {
    output["rows"].push_back({{"offsetMs", row.offsetMs},
                              {"dtMs", row.dtMs},
                              {"action", row.action},
                              {"textAfter", row.textAfter},
                              {"stepKind", row.stepKind}});
  }

  output["steps"] = nlohmann::json::array();
  for (const auto& step : trace.steps) {
    nlohmann::json row = {
        {"step", step.step},
        {"textBeforeLength", step.textBefore.size()},
        {"textBeforeTail", tail(step.textBefore, 48)},
        {"nextChar", step.nextChar},
        {"previousActionId", step.previousActionId},
        {"previousAction", actionName(step.previousActionId, actions)},
        {"selectedActionId", step.selectedActionId},
        {"selectedAction", actionName(step.selectedActionId, actions)},
        {"preferredActionId", step.preferredActionId},
        {"preferredAction", actionName(step.preferredActionId, actions)},
        {"validActions", validActionNames(step.validActionIds, actions)},
        {"selectedRawLogit", vectorAt(step.actionHead, step.selectedActionId)},
        {"preferredRawLogit", vectorAt(step.actionHead, step.preferredActionId)},
        {"topActionLogits", topLogits(step.actionHead, 8, actions)},
        {"learnedTypoProbability", step.learnedTypoProbability},
        {"topTypoActionLogits", topLogits(step.typoActionHead, 8, actions)},
        {"previousDtHead", step.previousDt},
        {"dtHead", step.dtHead.empty() ? nullptr : nlohmann::json(step.dtHead[0])},
        {"dtMs", step.dtMs},
        {"offsetMs", step.offsetMs},
        {"action", step.action},
        {"stepKind", step.stepKind},
        {"textAfterLength", step.textAfter.size()},
        {"textAfterTail", tail(step.textAfter, 48)},
        {"terminal", step.terminal},
    };
    if (includeVectors) {
      row["actionEmbedding"] = step.actionEmbedding;
      row["nextCharEmbedding"] = step.nextCharEmbedding;
      row["decoderInput"] = step.decoderInput;
      row["hidden"] = step.hidden;
      row["actionHead"] = step.actionHead;
      row["typoHead"] = step.typoHead;
      row["typoActionHead"] = step.typoActionHead;
    }
    output["steps"].push_back(std::move(row));
  }
  if (includeVectors) output["condition"] = trace.condition;
  return output;
}

std::vector<MouseCase> defaultMouseCases() {
  return {
      {"short text-field click", 72.0, 96.0, 302.0, 225.0, true},
      {"medium diagonal button click", 316.0, 244.0, 864.0, 184.0, true},
      {"dramatic cross-screen sweep", 86.0, 692.0, 1184.0, 82.0, true},
      {"vertical rail move", 944.0, 628.0, 948.0, 238.0, true},
      {"small correction nudge", 512.0, 384.0, 548.0, 398.0, true},
      {"move without click", 1040.0, 136.0, 764.0, 620.0, false},
  };
}

std::vector<KeyboardCase> defaultKeyboardCases() {
  return {
      {"short demo field", "", "rotunda models ship"},
      {"space-heavy instruction", "", "ship the model then check the mouse path"},
      {"paragraph demo text",
       "",
       "rotunda runtime models should make browser input look continuous. "
       "the pointer plans a path to each target, then the keyboard model types "
       "this longer paragraph as a sequence of timed edits."},
      {"existing typo repair", "rotunda modles", "rotunda models ship"},
      {"punctuation and number", "", "please review the dashboard before 4 pm."},
  };
}

nlohmann::json diagnosticRun(const Options& options) {
  nlohmann::json mouseMetadata = loadMetadata(options.mouseModel);
  nlohmann::json keyboardMetadata = loadMetadata(options.keyboardModel);
  std::vector<std::string> mouseActions = mouseActionNames(mouseMetadata);
  std::map<int, std::string> keyboardActions =
      keyboardActionNames(keyboardMetadata);

  auto mouse = rotundacfg::MouseRuntimeModel::Load(options.mouseModel);
  if (!mouse) {
    throw std::runtime_error("failed to load mouse model: " + options.mouseModel);
  }
  auto keyboard = rotundacfg::KeyboardRuntimeModel::Load(options.keyboardModel);
  if (!keyboard) {
    throw std::runtime_error("failed to load keyboard model: " +
                             options.keyboardModel);
  }

  nlohmann::json output;
  output["config"] = {
      {"mouseModel", options.mouseModel},
      {"keyboardModel", options.keyboardModel},
      {"mouseMaxSteps", options.mouseMaxSteps},
      {"mouseClickThreshold", options.mouseClickThreshold},
      {"mouseMinDtMs", options.mouseMinDtMs},
      {"mousePathCurveSigma", options.mousePathCurveSigma},
      {"mouseRandomSeed", options.mouseRandomSeed},
      {"keyboardMaxSteps", options.keyboardMaxSteps},
      {"keyboardStructuredExtraSteps", options.keyboardStructuredExtraSteps},
      {"keyboardCanonicalBias", options.keyboardCanonicalBias},
      {"keyboardLearnedTypoThreshold", options.keyboardLearnedTypoThreshold},
      {"keyboardMaxTypos", options.keyboardMaxTypos},
      {"keyboardSampleTypos", options.keyboardSampleTypos},
      {"keyboardTimingJitterSigma", options.keyboardTimingJitterSigma},
      {"keyboardTimingTemperature", options.keyboardTimingTemperature},
      {"keyboardPauseProbability", options.keyboardPauseProbability},
      {"keyboardPauseMeanMs", options.keyboardPauseMeanMs},
      {"keyboardRandomSeed", options.keyboardRandomSeed},
      {"includeVectors", options.includeVectors},
  };
  output["metadata"] = {{"mouse", mouseMetadata}, {"keyboard", keyboardMetadata}};
  output["nativeSelection"] = {
      {"mouseAction", "argmax(action_head) with endpoint override"},
      {"mousePath",
       options.mousePathCurveSigma > 0.0
           ? "sampled low-frequency goal-relative curve bias"
           : "deterministic learned perpendicular head"},
      {"keyboardAction",
       "argmax(valid action logits + canonical bias); no multinomial sampling"},
      {"keyboardTypo",
       options.keyboardSampleTypos
           ? "sample sigmoid(typo_head) after threshold, then "
             "argmax(typo_action_head)"
           : "sigmoid(typo_head) >= threshold, then argmax(typo_action_head); "
             "no probabilistic typo sampling"},
      {"keyboardTiming",
       options.keyboardTimingJitterSigma > 0.0 ||
               options.keyboardTimingTemperature > 0.0 ||
               options.keyboardPauseProbability > 0.0
           ? "learned timing temperature or residual timing sampler plus optional random pauses"
           : "deterministic dt_head point estimate"},
  };
  output["mouseCases"] = nlohmann::json::array();
  output["keyboardCases"] = nlohmann::json::array();

  for (const auto& testCase : defaultMouseCases()) {
    auto trace = mouse->traceDecode(
        testCase.fromX, testCase.fromY, testCase.toX, testCase.toY,
        testCase.clickAtEnd, options.mouseMaxSteps,
        options.mouseClickThreshold, options.mouseMinDtMs,
        options.mousePathCurveSigma, options.mouseRandomSeed);
    output["mouseCases"].push_back(
        mouseCaseJson(testCase, trace, mouseActions, options.includeVectors));
  }

  for (const auto& testCase : defaultKeyboardCases()) {
    auto trace = keyboard->traceDecode(
        testCase.initial, testCase.final, options.keyboardMaxSteps,
        "constrained", options.keyboardStructuredExtraSteps,
        options.keyboardCanonicalBias, options.keyboardLearnedTypoThreshold,
        options.keyboardMaxTypos, options.keyboardSampleTypos,
        options.keyboardTimingJitterSigma,
        options.keyboardPauseProbability, options.keyboardPauseMeanMs,
        options.keyboardRandomSeed, options.keyboardTimingTemperature);
    nlohmann::json caseOutput =
        keyboardCaseJson(testCase, trace, keyboardActions, options.includeVectors);
    if (trace.rows.empty() && testCase.initial != testCase.final) {
      caseOutput["decodeFailed"] = true;
      caseOutput["failureHint"] =
          "empty rows can mean unsupported target chars, missing press-count "
          "head, or constrained decode failed to reach the target";
    } else {
      caseOutput["decodeFailed"] = false;
    }
    output["keyboardCases"].push_back(std::move(caseOutput));
  }

  return output;
}

}  // namespace

int main(int argc, char** argv) {
  auto options = parseOptions(argc, argv);
  if (!options) return usage(argv[0]);

  try {
    std::cout << diagnosticRun(*options).dump(2) << "\n";
  } catch (const std::exception& error) {
    std::cerr << "runtime model debug failed: " << error.what() << "\n";
    return 1;
  }
  return 0;
}

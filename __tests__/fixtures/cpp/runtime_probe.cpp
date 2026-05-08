#include "KeyboardRuntime.hpp"
#include "MouseRuntime.hpp"
#include "json.hpp"

#include <cstdlib>
#include <iostream>
#include <string>

namespace {

nlohmann::json mousePointJson(const rotundacfg::MouseTrajectoryPoint& point) {
  return {
      {"x", point.x},
      {"y", point.y},
      {"dtMs", point.dtMs},
      {"action", point.action},
  };
}

nlohmann::json mouseStepJson(const rotundacfg::MouseRuntimeTraceStep& step) {
  return {
      {"step", step.step},
      {"previous", step.previous},
      {"decoderInput", step.decoderInput},
      {"hidden", step.hidden},
      {"dtHead", step.dtHead},
      {"posHead", step.posHead},
      {"actionHead", step.actionHead},
      {"stateAlong", step.stateAlong},
      {"statePerp", step.statePerp},
      {"x", step.x},
      {"y", step.y},
      {"dtMs", step.dtMs},
      {"rawAction", step.rawAction},
      {"action", step.action},
      {"terminal", step.terminal},
  };
}

nlohmann::json keyboardRowJson(const rotundacfg::KeyboardRuntimeRow& row) {
  return {
      {"offsetMs", row.offsetMs},
      {"dtMs", row.dtMs},
      {"action", row.action},
      {"textAfter", row.textAfter},
      {"stepKind", row.stepKind},
  };
}

nlohmann::json keyboardStepJson(
    const rotundacfg::KeyboardRuntimeTraceStep& step) {
  return {
      {"step", step.step},
      {"textBefore", step.textBefore},
      {"nextChar", step.nextChar},
      {"actionEmbedding", step.actionEmbedding},
      {"nextCharEmbedding", step.nextCharEmbedding},
      {"decoderInput", step.decoderInput},
      {"hidden", step.hidden},
      {"dtHead", step.dtHead},
      {"actionHead", step.actionHead},
      {"typoHead", step.typoHead},
      {"typoActionHead", step.typoActionHead},
      {"learnedTypoProbability", step.learnedTypoProbability},
      {"validActionIds", step.validActionIds},
      {"previousActionId", step.previousActionId},
      {"selectedActionId", step.selectedActionId},
      {"preferredActionId", step.preferredActionId},
      {"previousDt", step.previousDt},
      {"offsetMs", step.offsetMs},
      {"dtMs", step.dtMs},
      {"action", step.action},
      {"textAfter", step.textAfter},
      {"stepKind", step.stepKind},
      {"terminal", step.terminal},
  };
}

bool parseBool(const char* value) { return std::string(value) == "1"; }

int usage(const char* binary) {
  std::cerr
      << "usage:\n"
      << "  " << binary
      << " mouse <weights> <fromX> <fromY> <toX> <toY> <clickAtEnd>"
      << " <maxSteps> <clickThreshold> <minDtMs>\n"
      << "  " << binary
      << " keyboard <weights> <initial> <final> <maxSteps> <decodeMode>"
      << " <structuredExtraSteps> <canonicalBias>\n"
      << "  " << binary << " resolve-model <fileName>\n";
  return 2;
}

}  // namespace

int main(int argc, char** argv) {
  if (argc < 2) return usage(argv[0]);

  std::string mode = argv[1];
  if (mode == "mouse") {
    if (argc != 11) return usage(argv[0]);
    auto model = rotundacfg::MouseRuntimeModel::Load(argv[2]);
    if (!model) {
      std::cerr << "failed to load mouse model\n";
      return 1;
    }

    rotundacfg::MouseRuntimeTrace trace = model->traceDecode(
        std::stod(argv[3]), std::stod(argv[4]), std::stod(argv[5]),
        std::stod(argv[6]), parseBool(argv[7]), std::stoi(argv[8]),
        std::stod(argv[9]), std::stod(argv[10]));
    nlohmann::json output;
    output["kind"] = "mouse";
    output["usedFallback"] = trace.usedFallback;
    output["condition"] = trace.condition;
    output["embedding"] = trace.embedding;
    output["steps"] = nlohmann::json::array();
    for (const auto& step : trace.steps) {
      output["steps"].push_back(mouseStepJson(step));
    }
    output["plan"] = nlohmann::json::array();
    for (const auto& point : trace.plan) {
      output["plan"].push_back(mousePointJson(point));
    }
    std::cout << output.dump() << "\n";
    return 0;
  }

  if (mode == "keyboard") {
    if (argc != 9) return usage(argv[0]);
    auto model = rotundacfg::KeyboardRuntimeModel::Load(argv[2]);
    if (!model) {
      std::cerr << "failed to load keyboard model\n";
      return 1;
    }

    rotundacfg::KeyboardRuntimeTrace trace = model->traceDecode(
        argv[3], argv[4], std::stoi(argv[5]), argv[6], std::stoi(argv[7]),
        std::stod(argv[8]));
    nlohmann::json output;
    output["kind"] = "keyboard";
    output["minimumSteps"] = trace.minimumSteps;
    output["effectiveMaxSteps"] = trace.effectiveMaxSteps;
    output["predictedPressCount"] = trace.predictedPressCount;
    output["usedPredictedPressCount"] = trace.usedPredictedPressCount;
    output["conditionIds"] = trace.conditionIds;
    output["condition"] = trace.condition;
    output["steps"] = nlohmann::json::array();
    for (const auto& step : trace.steps) {
      output["steps"].push_back(keyboardStepJson(step));
    }
    output["rows"] = nlohmann::json::array();
    for (const auto& row : trace.rows) {
      output["rows"].push_back(keyboardRowJson(row));
    }
    std::cout << output.dump() << "\n";
    return 0;
  }

  if (mode == "resolve-model") {
    if (argc != 3) return usage(argv[0]);
    auto path = rotundacfg::RuntimeWeights::ResolveBundledModelPath(argv[2]);
    if (!path) return 1;
    std::cout << *path << "\n";
    return 0;
  }

  return usage(argv[0]);
}

#pragma once

#include <optional>
#include <string>
#include <unordered_map>
#include <vector>

#include "RuntimeWeights.hpp"

namespace rotundacfg {

struct KeyboardRuntimeRow {
  double offsetMs = 0.0;
  double dtMs = 0.0;
  std::string action;
  std::string textAfter;
  std::string stepKind;
};

struct KeyboardRuntimeTraceStep {
  int step = 0;
  std::string textBefore;
  std::string nextChar;
  std::vector<double> actionEmbedding;
  std::vector<double> nextCharEmbedding;
  std::vector<double> decoderInput;
  std::vector<double> hidden;
  std::vector<double> dtHead;
  std::vector<double> actionHead;
  std::vector<double> typoHead;
  std::vector<double> typoActionHead;
  std::vector<int> validActionIds;
  int previousActionId = 0;
  int selectedActionId = -1;
  int preferredActionId = -1;
  double learnedTypoProbability = 0.0;
  double previousDt = 0.0;
  double offsetMs = 0.0;
  double dtMs = 0.0;
  std::string action;
  std::string textAfter;
  std::string stepKind;
  bool terminal = false;
};

struct KeyboardRuntimeTrace {
  std::vector<int> conditionIds;
  std::vector<double> condition;
  std::vector<KeyboardRuntimeTraceStep> steps;
  std::vector<KeyboardRuntimeRow> rows;
};

class KeyboardRuntimeModel {
 public:
  static std::optional<KeyboardRuntimeModel> Load(const std::string& path);
  static std::vector<KeyboardRuntimeRow> GenerateFromConfig(
      const std::string& initialString, const std::string& finalString);

  std::vector<KeyboardRuntimeRow> decode(
      const std::string& initialString, const std::string& finalString,
      int maxSteps = 256, const std::string& decodeMode = "constrained",
      int structuredExtraSteps = 6, double canonicalBias = 3.0,
      double learnedTypoThreshold = 0.2, int maxLearnedTypos = 2) const;
  KeyboardRuntimeTrace traceDecode(
      const std::string& initialString, const std::string& finalString,
      int maxSteps = 256, const std::string& decodeMode = "constrained",
      int structuredExtraSteps = 6, double canonicalBias = 3.0,
      double learnedTypoThreshold = 0.2, int maxLearnedTypos = 2) const;

  const nlohmann::json& metadata() const { return m_metadata; }
  bool isLoaded() const { return m_loaded; }

 private:
  explicit KeyboardRuntimeModel(RuntimeWeights weights);

  int charId(const std::string& token) const;
  int actionId(const std::string& action) const;
  std::string actionForId(int actionId) const;
  std::vector<int> encodeCondition(const std::string& initialString,
                                   const std::string& finalString) const;
  std::vector<double> embeddingRow(const std::string& tensorName,
                                   int rowId) const;
  std::vector<double> linear(const std::vector<double>& input,
                             const std::string& weightName,
                             const std::string& biasName) const;
  std::vector<double> gruCell(const std::string& prefix,
                              const std::vector<double>& input,
                              const std::vector<double>& hidden,
                              int layer) const;
  std::vector<double> encode(const std::string& initialString,
                             const std::string& finalString) const;
  std::string nextChar(const std::string& finalString,
                       const std::string& text) const;
  std::string constrainedAction(const std::string& finalString,
                                const std::string& text) const;
  std::vector<int> structuredActionIds(
      const std::string& finalString, const std::string& text,
      int remainingStepsAfterAction) const;
  bool targetSupported(const std::string& initialString,
                       const std::string& finalString) const;
  int minimumTerminalEditSteps(const std::string& finalString,
                               const std::string& text) const;
  std::string applyActionCopy(const std::string& text,
                              const std::string& action) const;
  KeyboardRuntimeTrace decodeInternal(
      const std::string& initialString, const std::string& finalString,
      int maxSteps, const std::string& decodeMode, int structuredExtraSteps,
      double canonicalBias, double learnedTypoThreshold,
      int maxLearnedTypos, bool collectTrace) const;

  RuntimeWeights m_weights;
  nlohmann::json m_metadata;
  std::unordered_map<std::string, int> m_charToId;
  std::unordered_map<int, std::string> m_idToAction;
  std::unordered_map<std::string, int> m_actionToId;
  int m_hiddenSize = 0;
  int m_layers = 1;
  int m_actionCount = 0;
  bool m_loaded = false;
  bool m_hasLearnedTypoHead = false;
};

}  // namespace rotundacfg

#include "KeyboardRuntime.hpp"

#include "MaskConfig.hpp"

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <limits>
#include <memory>
#include <mutex>
#include <random>
#include <set>
#include <utility>

namespace rotundacfg {

namespace {

constexpr const char* kBackspace = "<BACKSPACE>";
constexpr const char* kStop = "<STOP>";
constexpr const char* kUnk = "<UNK>";
constexpr const char* kEos = "<EOS>";
constexpr const char* kSep = "<SEP>";
constexpr double kMaxPredictedPressCount = 1024.0;
constexpr double kMinSampledDtMs = 6.0;
constexpr double kMaxSampledDtMs = 650.0;

double sigmoid(double value) { return 1.0 / (1.0 + std::exp(-value)); }

double softplus(double value) {
  if (value > 20.0) return value;
  return std::log1p(std::exp(value));
}

double logToDt(double value) {
  return std::expm1(std::max(0.0, std::min(value, std::log1p(5000.0))));
}

double sampledKeyboardDt(double dtMs, double timingJitterSigma,
                         double pauseProbability, double pauseMeanMs,
                         std::mt19937& rng) {
  double sampled = dtMs;
  if (timingJitterSigma > 0.0) {
    double sigma = std::min(std::max(0.0, timingJitterSigma), 1.0);
    std::lognormal_distribution<double> residual(
        -0.5 * sigma * sigma, sigma);
    sampled *= residual(rng);
  }
  if (pauseProbability > 0.0 && pauseMeanMs > 0.0) {
    std::uniform_real_distribution<double> uniform(0.0, 1.0);
    if (uniform(rng) < std::min(std::max(0.0, pauseProbability), 1.0)) {
      std::exponential_distribution<double> pause(1.0 / pauseMeanMs);
      sampled += pause(rng);
    }
  }
  return std::min(kMaxSampledDtMs, std::max(kMinSampledDtMs, sampled));
}

bool startsWith(const std::string& value, const std::string& prefix) {
  return prefix.size() <= value.size() &&
         value.compare(0, prefix.size(), prefix) == 0;
}

size_t commonPrefixLength(const std::string& left, const std::string& right) {
  size_t limit = std::min(left.size(), right.size());
  for (size_t i = 0; i < limit; ++i) {
    if (left[i] != right[i]) return i;
  }
  return limit;
}

std::vector<std::string> byteTokens(const std::string& value) {
  std::vector<std::string> tokens;
  tokens.reserve(value.size());
  for (char ch : value) tokens.emplace_back(1, ch);
  return tokens;
}

}  // namespace

KeyboardRuntimeModel::KeyboardRuntimeModel(RuntimeWeights weights)
    : m_weights(std::move(weights)) {
  if (auto metadata = m_weights.rotundaMetadata()) {
    m_metadata = *metadata;
    if (m_metadata.value("kind", "") != "keyboard_action_gru") return;
    if (m_metadata.contains("charToId")) {
      for (auto it = m_metadata["charToId"].begin();
           it != m_metadata["charToId"].end(); ++it) {
        m_charToId[it.key()] = it.value().get<int>();
      }
    }
    if (m_metadata.contains("idToAction")) {
      for (auto it = m_metadata["idToAction"].begin();
           it != m_metadata["idToAction"].end(); ++it) {
        m_idToAction[std::stoi(it.key())] = it.value().get<std::string>();
      }
    }
    if (m_metadata.contains("actionToId")) {
      for (auto it = m_metadata["actionToId"].begin();
           it != m_metadata["actionToId"].end(); ++it) {
        m_actionToId[it.key()] = it.value().get<int>();
      }
    }
    if (m_actionToId.empty()) {
      for (const auto& [id, action] : m_idToAction) m_actionToId[action] = id;
    }
    if (m_metadata.contains("modelConfig")) {
      const auto& config = m_metadata["modelConfig"];
      m_hiddenSize = config.value("hidden_size", 0);
      m_layers = config.value("layers", 1);
      m_actionCount = config.value("action_vocab_size",
                                   static_cast<int>(m_idToAction.size()));
    }
    m_hasLearnedTypoHead = m_weights.get("typo_head.weight") &&
                           m_weights.get("typo_head.bias") &&
                           m_weights.get("typo_action_head.weight") &&
                           m_weights.get("typo_action_head.bias");
    m_hasPressCountHead = m_weights.get("press_count_head.weight") &&
                          m_weights.get("press_count_head.bias");
    m_loaded = m_hiddenSize > 0 && m_layers > 0 && !m_charToId.empty() &&
               !m_idToAction.empty() && !m_actionToId.empty();
  }
}

std::optional<KeyboardRuntimeModel> KeyboardRuntimeModel::Load(
    const std::string& path) {
  auto weights = RuntimeWeights::Load(path);
  if (!weights) return std::nullopt;
  KeyboardRuntimeModel model(std::move(*weights));
  if (!model.isLoaded()) return std::nullopt;
  return model;
}

std::vector<KeyboardRuntimeRow> KeyboardRuntimeModel::GenerateFromConfig(
    const std::string& initialString, const std::string& finalString) {
  static std::once_flag initFlag;
  static std::unique_ptr<KeyboardRuntimeModel> model;
  std::call_once(initFlag, []() {
    auto path = MaskConfig::GetString("humanize.keyboardModelPath");
    if (!path || path->empty()) {
      path = RuntimeWeights::ResolveBundledModelPath("keyboard.safetensors");
    }
    if (!path || path->empty()) return;
    auto loaded = KeyboardRuntimeModel::Load(*path);
    if (loaded) {
      model = std::make_unique<KeyboardRuntimeModel>(std::move(*loaded));
    }
  });

  if (!model) return {};

  int maxSteps = 256;
  if (auto configured = MaskConfig::GetInt32("humanize.keyboardMaxSteps")) {
    maxSteps = std::max(1, *configured);
  }
  int structuredExtraSteps = 6;
  if (auto configured =
          MaskConfig::GetInt32("humanize.keyboardStructuredExtraSteps")) {
    structuredExtraSteps = std::max(0, *configured);
  }
  double canonicalBias = 3.0;
  if (auto configured = MaskConfig::GetDouble("humanize.keyboardCanonicalBias")) {
    canonicalBias = std::max(0.0, *configured);
  }
  double learnedTypoThreshold = 0.2;
  if (auto configured =
          MaskConfig::GetDouble("humanize.keyboardLearnedTypoThreshold")) {
    learnedTypoThreshold = std::max(0.0, std::min(1.0, *configured));
  }
  int maxLearnedTypos = 2;
  if (auto configured = MaskConfig::GetInt32("humanize.keyboardMaxTypos")) {
    maxLearnedTypos = std::max(0, *configured);
  }
  bool sampleLearnedTypos = true;
  if (auto configured = MaskConfig::GetBool("humanize.keyboardSampleTypos")) {
    sampleLearnedTypos = *configured;
  }
  double timingJitterSigma = 0.22;
  if (auto configured =
          MaskConfig::GetDouble("humanize.keyboardTimingJitterSigma")) {
    timingJitterSigma = std::max(0.0, *configured);
  }
  double pauseProbability = 0.0;
  if (auto configured =
          MaskConfig::GetDouble("humanize.keyboardPauseProbability")) {
    pauseProbability = std::max(0.0, std::min(1.0, *configured));
  }
  double pauseMeanMs = 35.0;
  if (auto configured = MaskConfig::GetDouble("humanize.keyboardPauseMeanMs")) {
    pauseMeanMs = std::max(0.0, *configured);
  }
  return model->decode(initialString, finalString, maxSteps, "constrained",
                       structuredExtraSteps, canonicalBias,
                       learnedTypoThreshold, maxLearnedTypos,
                       sampleLearnedTypos, timingJitterSigma,
                       pauseProbability, pauseMeanMs);
}

int KeyboardRuntimeModel::charId(const std::string& token) const {
  auto it = m_charToId.find(token);
  if (it != m_charToId.end()) return it->second;
  auto unk = m_charToId.find(kUnk);
  return unk == m_charToId.end() ? 0 : unk->second;
}

int KeyboardRuntimeModel::actionId(const std::string& action) const {
  auto it = m_actionToId.find(action);
  return it == m_actionToId.end() ? -1 : it->second;
}

std::string KeyboardRuntimeModel::actionForId(int actionId) const {
  auto it = m_idToAction.find(actionId);
  return it == m_idToAction.end() ? std::string(kStop) : it->second;
}

std::vector<int> KeyboardRuntimeModel::encodeCondition(
    const std::string& initialString, const std::string& finalString) const {
  std::vector<int> ids;
  if (m_charToId.find(kSep) != m_charToId.end()) {
    for (const auto& token : byteTokens(initialString)) ids.push_back(charId(token));
    ids.push_back(charId(kSep));
    for (const auto& token : byteTokens(finalString)) ids.push_back(charId(token));
  } else {
    for (const auto& token : byteTokens(finalString)) ids.push_back(charId(token));
  }
  ids.push_back(charId(kEos));
  return ids;
}

std::vector<double> KeyboardRuntimeModel::embeddingRow(
    const std::string& tensorName, int rowId) const {
  const RuntimeTensor* tensor = m_weights.get(tensorName);
  if (!tensor || tensor->shape.size() != 2 || rowId < 0 ||
      static_cast<size_t>(rowId) >= tensor->dim(0)) {
    return {};
  }
  size_t width = tensor->dim(1);
  std::vector<double> row(width, 0.0);
  size_t offset = static_cast<size_t>(rowId) * width;
  for (size_t i = 0; i < width; ++i) {
    row[i] = tensor->values[offset + i];
  }
  return row;
}

std::vector<double> KeyboardRuntimeModel::linear(
    const std::vector<double>& input, const std::string& weightName,
    const std::string& biasName) const {
  const RuntimeTensor* weight = m_weights.get(weightName);
  const RuntimeTensor* bias = m_weights.get(biasName);
  if (!weight || !bias || weight->shape.size() != 2) return {};
  size_t outDim = weight->dim(0);
  size_t inDim = weight->dim(1);
  if (input.size() != inDim || bias->size() != outDim) return {};

  std::vector<double> output(outDim, 0.0);
  for (size_t out = 0; out < outDim; ++out) {
    double value = bias->values[out];
    for (size_t in = 0; in < inDim; ++in) {
      value += static_cast<double>(weight->values[out * inDim + in]) * input[in];
    }
    output[out] = value;
  }
  return output;
}

std::vector<double> KeyboardRuntimeModel::gruCell(
    const std::string& prefix, const std::vector<double>& input,
    const std::vector<double>& hidden, int layer) const {
  std::string suffix = "_l" + std::to_string(layer);
  const RuntimeTensor* wih = m_weights.get(prefix + ".weight_ih" + suffix);
  const RuntimeTensor* whh = m_weights.get(prefix + ".weight_hh" + suffix);
  const RuntimeTensor* bih = m_weights.get(prefix + ".bias_ih" + suffix);
  const RuntimeTensor* bhh = m_weights.get(prefix + ".bias_hh" + suffix);
  if (!wih || !whh || !bih || !bhh || wih->shape.size() != 2 ||
      whh->shape.size() != 2) {
    return {};
  }

  const size_t hiddenSize = hidden.size();
  const size_t inputSize = input.size();
  if (wih->dim(0) != hiddenSize * 3 || whh->dim(0) != hiddenSize * 3 ||
      wih->dim(1) != inputSize || whh->dim(1) != hiddenSize ||
      bih->size() != hiddenSize * 3 || bhh->size() != hiddenSize * 3) {
    return {};
  }

  std::vector<double> ih(hiddenSize * 3, 0.0);
  std::vector<double> hh(hiddenSize * 3, 0.0);
  for (size_t gate = 0; gate < hiddenSize * 3; ++gate) {
    double iv = bih->values[gate];
    for (size_t in = 0; in < inputSize; ++in) {
      iv += static_cast<double>(wih->values[gate * inputSize + in]) * input[in];
    }
    ih[gate] = iv;

    double hv = bhh->values[gate];
    for (size_t in = 0; in < hiddenSize; ++in) {
      hv += static_cast<double>(whh->values[gate * hiddenSize + in]) *
            hidden[in];
    }
    hh[gate] = hv;
  }

  std::vector<double> next(hiddenSize, 0.0);
  for (size_t i = 0; i < hiddenSize; ++i) {
    double reset = sigmoid(ih[i] + hh[i]);
    double update = sigmoid(ih[hiddenSize + i] + hh[hiddenSize + i]);
    double candidate =
        std::tanh(ih[2 * hiddenSize + i] + reset * hh[2 * hiddenSize + i]);
    next[i] = (1.0 - update) * candidate + update * hidden[i];
  }
  return next;
}

std::vector<double> KeyboardRuntimeModel::encode(
    const std::string& initialString, const std::string& finalString) const {
  std::vector<int> ids = encodeCondition(initialString, finalString);
  std::vector<double> hidden(static_cast<size_t>(m_hiddenSize), 0.0);
  for (int id : ids) {
    std::vector<double> input = embeddingRow("char_embed.weight", id);
    if (input.empty()) return {};
    hidden = gruCell("encoder", input, hidden, 0);
    if (hidden.empty()) return {};
  }
  return hidden;
}

std::optional<double> KeyboardRuntimeModel::predictPressCount(
    const std::vector<double>& condition) const {
  if (!m_hasPressCountHead) return std::nullopt;
  std::vector<double> head =
      linear(condition, "press_count_head.weight", "press_count_head.bias");
  if (head.empty()) return std::nullopt;
  double logCount = std::min(softplus(head[0]), std::log1p(kMaxPredictedPressCount));
  double count = std::expm1(logCount);
  if (!std::isfinite(count)) return std::nullopt;
  return count;
}

std::string KeyboardRuntimeModel::nextChar(
    const std::string& finalString, const std::string& text) const {
  if (startsWith(finalString, text) && text.size() < finalString.size()) {
    return finalString.substr(text.size(), 1);
  }
  return kEos;
}

std::string KeyboardRuntimeModel::constrainedAction(
    const std::string& finalString, const std::string& text) const {
  if (text == finalString) return kStop;
  if (startsWith(finalString, text) && text.size() < finalString.size()) {
    return finalString.substr(text.size(), 1);
  }
  return kBackspace;
}

std::string KeyboardRuntimeModel::applyActionCopy(
    const std::string& text, const std::string& action) const {
  std::string result = text;
  if (action == kBackspace) {
    if (!result.empty()) result.pop_back();
  } else if (action != kStop) {
    result += action;
  }
  return result;
}

int KeyboardRuntimeModel::minimumTerminalEditSteps(
    const std::string& finalString, const std::string& text) const {
  size_t prefix = commonPrefixLength(text, finalString);
  return static_cast<int>((text.size() - prefix) + (finalString.size() - prefix));
}

std::vector<int> KeyboardRuntimeModel::structuredActionIds(
    const std::string& finalString, const std::string& text,
    int remainingStepsAfterAction) const {
  if (text == finalString) {
    int stopId = actionId(kStop);
    return stopId < 0 ? std::vector<int>() : std::vector<int>{stopId};
  }

  std::set<int> valid;
  for (const auto& [action, id] : m_actionToId) {
    if (action == kStop) continue;
    if (action == kBackspace && (text.empty() || startsWith(finalString, text))) {
      continue;
    }
    std::string candidate = applyActionCopy(text, action);
    if (candidate == text) continue;
    if (minimumTerminalEditSteps(finalString, candidate) <=
        remainingStepsAfterAction) {
      valid.insert(id);
    }
  }
  if (valid.empty()) {
    int fallback = actionId(constrainedAction(finalString, text));
    if (fallback >= 0) valid.insert(fallback);
  }
  return {valid.begin(), valid.end()};
}

bool KeyboardRuntimeModel::targetSupported(
    const std::string& initialString, const std::string& finalString) const {
  size_t prefix = commonPrefixLength(initialString, finalString);
  if (initialString.size() > prefix && actionId(kBackspace) < 0) return false;
  for (size_t i = prefix; i < finalString.size(); ++i) {
    if (m_actionToId.find(finalString.substr(i, 1)) == m_actionToId.end()) {
      return false;
    }
  }
  return true;
}

std::vector<KeyboardRuntimeRow> KeyboardRuntimeModel::decode(
    const std::string& initialString, const std::string& finalString,
    int maxSteps, const std::string& decodeMode, int structuredExtraSteps,
    double canonicalBias, double learnedTypoThreshold, int maxLearnedTypos,
    bool sampleLearnedTypos, double timingJitterSigma,
    double pauseProbability, double pauseMeanMs, std::uint32_t randomSeed) const {
  return decodeInternal(initialString, finalString, maxSteps, decodeMode,
                        structuredExtraSteps, canonicalBias,
                        learnedTypoThreshold, maxLearnedTypos,
                        sampleLearnedTypos, timingJitterSigma,
                        pauseProbability, pauseMeanMs, randomSeed, false)
      .rows;
}

KeyboardRuntimeTrace KeyboardRuntimeModel::traceDecode(
    const std::string& initialString, const std::string& finalString,
    int maxSteps, const std::string& decodeMode, int structuredExtraSteps,
    double canonicalBias, double learnedTypoThreshold, int maxLearnedTypos,
    bool sampleLearnedTypos, double timingJitterSigma,
    double pauseProbability, double pauseMeanMs, std::uint32_t randomSeed) const {
  return decodeInternal(initialString, finalString, maxSteps, decodeMode,
                        structuredExtraSteps, canonicalBias,
                        learnedTypoThreshold, maxLearnedTypos,
                        sampleLearnedTypos, timingJitterSigma,
                        pauseProbability, pauseMeanMs, randomSeed, true);
}

KeyboardRuntimeTrace KeyboardRuntimeModel::decodeInternal(
    const std::string& initialString, const std::string& finalString,
    int maxSteps, const std::string& decodeMode, int structuredExtraSteps,
    double canonicalBias, double learnedTypoThreshold, int maxLearnedTypos,
    bool sampleLearnedTypos, double timingJitterSigma,
    double pauseProbability, double pauseMeanMs, std::uint32_t randomSeed,
    bool collectTrace) const {
  KeyboardRuntimeTrace trace;
  if (!m_loaded || maxSteps <= 0) return {};
  if (decodeMode != "constrained" && decodeMode != "canonical") return {};
  if (!targetSupported(initialString, finalString)) return {};
  structuredExtraSteps = std::max(0, structuredExtraSteps);
  learnedTypoThreshold = std::max(0.0, std::min(1.0, learnedTypoThreshold));
  maxLearnedTypos = std::max(0, maxLearnedTypos);

  int minSteps = minimumTerminalEditSteps(finalString, initialString);
  if (maxSteps < minSteps) return {};

  if (collectTrace) {
    trace.minimumSteps = minSteps;
    trace.conditionIds = encodeCondition(initialString, finalString);
  }
  std::vector<double> condition = encode(initialString, finalString);
  if (condition.empty()) return {};
  if (collectTrace) trace.condition = condition;
  std::optional<double> predictedPressCount;
  int effectiveMaxSteps = maxSteps;
  if (decodeMode == "constrained") {
    if (!m_hasPressCountHead) return {};
    predictedPressCount = predictPressCount(condition);
    if (!predictedPressCount) return {};
    int floorBudget =
        std::max(minSteps, static_cast<int>(finalString.size()) + structuredExtraSteps);
    int predictedBudget =
        std::max(minSteps, static_cast<int>(std::ceil(std::max(0.0, *predictedPressCount - 1e-6))));
    effectiveMaxSteps = std::min(maxSteps, std::max(floorBudget, predictedBudget));
  }
  if (collectTrace) {
    trace.effectiveMaxSteps = effectiveMaxSteps;
    if (predictedPressCount) {
      trace.predictedPressCount = *predictedPressCount;
      trace.usedPredictedPressCount = true;
    }
  }
  std::vector<std::vector<double>> hidden(
      static_cast<size_t>(m_layers), condition);

  int previousActionId = m_actionCount;
  double previousDt = 0.0;
  double offset = 0.0;
  std::string text = initialString;
  std::vector<KeyboardRuntimeRow> rows;
  int learnedTyposUsed = 0;
  std::set<std::string> learnedTypoPrefixes;
  bool sampleTiming =
      timingJitterSigma > 0.0 || (pauseProbability > 0.0 && pauseMeanMs > 0.0);
  std::optional<std::mt19937> randomSampler;
  if (sampleTiming || sampleLearnedTypos) {
    randomSampler.emplace(randomSeed == 0 ? std::random_device{}() : randomSeed);
  }

  for (int step = 0; step < effectiveMaxSteps; ++step) {
    std::string next = nextChar(finalString, text);
    std::vector<double> actionEmbedding =
        embeddingRow("action_embed.weight", previousActionId);
    std::vector<double> nextCharEmbedding =
        embeddingRow("char_embed.weight", charId(next));
    if (actionEmbedding.empty() || nextCharEmbedding.empty()) return {};

    std::vector<double> input = condition;
    input.insert(input.end(), actionEmbedding.begin(), actionEmbedding.end());
    input.insert(input.end(), nextCharEmbedding.begin(), nextCharEmbedding.end());
    input.push_back(previousDt);
    KeyboardRuntimeTraceStep traceStep;
    if (collectTrace) {
      traceStep.step = step;
      traceStep.textBefore = text;
      traceStep.nextChar = next;
      traceStep.actionEmbedding = actionEmbedding;
      traceStep.nextCharEmbedding = nextCharEmbedding;
      traceStep.decoderInput = input;
      traceStep.previousActionId = previousActionId;
      traceStep.previousDt = previousDt;
    }

    for (int layer = 0; layer < m_layers; ++layer) {
      std::vector<double> nextHidden =
          gruCell("decoder", input, hidden[static_cast<size_t>(layer)], layer);
      if (nextHidden.empty()) return {};
      hidden[static_cast<size_t>(layer)] = nextHidden;
      input = nextHidden;
    }

    std::vector<double> dtHead = linear(input, "dt_head.weight", "dt_head.bias");
    std::vector<double> actionHead =
        linear(input, "action_head.weight", "action_head.bias");
    if (dtHead.empty() || actionHead.empty()) return {};
    std::vector<double> typoHead;
    std::vector<double> typoActionHead;
    if (m_hasLearnedTypoHead) {
      typoHead = linear(input, "typo_head.weight", "typo_head.bias");
      typoActionHead =
          linear(input, "typo_action_head.weight", "typo_action_head.bias");
      if (typoHead.empty() || typoActionHead.empty()) return {};
    }
    if (collectTrace) {
      traceStep.hidden = input;
      traceStep.dtHead = dtHead;
      traceStep.actionHead = actionHead;
      traceStep.typoHead = typoHead;
      traceStep.typoActionHead = typoActionHead;
      if (!typoHead.empty()) traceStep.learnedTypoProbability = sigmoid(typoHead[0]);
    }

    std::string action;
    int selectedActionId = -1;
    int preferredId = -1;
    std::string stepKind = "target";
    if (decodeMode == "canonical") {
      action = constrainedAction(finalString, text);
      selectedActionId = actionId(action);
      preferredId = selectedActionId;
      stepKind = action == kBackspace ? "repair" : "target";
    } else {
      int remaining = std::max(0, effectiveMaxSteps - static_cast<int>(rows.size()) - 1);
      std::vector<int> valid = structuredActionIds(finalString, text, remaining);
      std::string preferred = constrainedAction(finalString, text);
      preferredId = actionId(preferred);
      if (collectTrace) traceStep.validActionIds = valid;
      if (m_hasLearnedTypoHead && learnedTyposUsed < maxLearnedTypos &&
          learnedTypoPrefixes.find(text) == learnedTypoPrefixes.end() &&
          startsWith(finalString, text) && text != finalString &&
          !typoHead.empty() && !typoActionHead.empty()) {
        double typoProbability = sigmoid(typoHead[0]);
        bool shouldTryTypo = typoProbability >= learnedTypoThreshold;
        if (shouldTryTypo && sampleLearnedTypos && randomSampler.has_value()) {
          std::uniform_real_distribution<double> uniform(0.0, 1.0);
          shouldTryTypo = uniform(*randomSampler) < typoProbability;
        }
        if (shouldTryTypo) {
          double bestTypoLogit = -std::numeric_limits<double>::infinity();
          for (int id : valid) {
            if (id < 0 || static_cast<size_t>(id) >= typoActionHead.size() ||
                id == preferredId) {
              continue;
            }
            std::string candidateAction = actionForId(id);
            if (candidateAction == kBackspace || candidateAction == kStop) {
              continue;
            }
            double value = typoActionHead[static_cast<size_t>(id)];
            if (selectedActionId < 0 || value > bestTypoLogit) {
              bestTypoLogit = value;
              selectedActionId = id;
            }
          }
          if (selectedActionId >= 0) {
            ++learnedTyposUsed;
            learnedTypoPrefixes.insert(text);
            stepKind = "learned_typo";
          }
        }
      }
      if (selectedActionId < 0) {
        double bestLogit = -std::numeric_limits<double>::infinity();
        for (int id : valid) {
          if (id < 0 || static_cast<size_t>(id) >= actionHead.size()) continue;
          double value = actionHead[static_cast<size_t>(id)] +
                         (id == preferredId ? canonicalBias : 0.0);
          if (selectedActionId < 0 || value > bestLogit) {
            bestLogit = value;
            selectedActionId = id;
          }
        }
      }
      action = actionForId(selectedActionId);
      if (stepKind == "learned_typo") {
        // The learned typo head selected a wrong character. The next steps go
        // back through normal structured decoding, which decides the repair.
      } else if (action == kStop) {
        stepKind = "model_stop";
      } else if (action == kBackspace) {
        stepKind = "model_repair";
      } else if (startsWith(finalString, text) && text.size() < finalString.size() &&
                 action == finalString.substr(text.size(), 1)) {
        stepKind = "model_target";
      } else {
        stepKind = "model_edit";
      }
    }

    if (selectedActionId < 0) return {};
    double dtMs = logToDt(dtHead[0]);
    if (sampleTiming && action != kStop && randomSampler.has_value()) {
      dtMs = sampledKeyboardDt(dtMs, timingJitterSigma, pauseProbability,
                               pauseMeanMs, *randomSampler);
    }
    offset += dtMs;
    if (collectTrace) {
      traceStep.selectedActionId = selectedActionId;
      traceStep.preferredActionId = preferredId;
      traceStep.offsetMs = offset;
      traceStep.dtMs = dtMs;
      traceStep.action = action;
      traceStep.stepKind = stepKind;
      traceStep.textAfter = text;
      traceStep.terminal = action == kStop;
    }
    if (action == kStop) {
      if (collectTrace) trace.steps.push_back(std::move(traceStep));
      break;
    }

    text = applyActionCopy(text, action);
    rows.push_back({offset, dtMs, action, text, stepKind});
    if (collectTrace) {
      traceStep.textAfter = text;
      trace.steps.push_back(std::move(traceStep));
    }
    previousActionId = selectedActionId;
    previousDt = dtHead[0];
  }

  if (text != finalString) return {};
  trace.rows = std::move(rows);
  return trace;
}

}  // namespace rotundacfg

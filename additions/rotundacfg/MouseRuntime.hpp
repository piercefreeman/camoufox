#pragma once

#include <optional>
#include <string>
#include <vector>

#include "RuntimeWeights.hpp"

namespace rotundacfg {

struct MouseTrajectoryPoint {
  double x = 0.0;
  double y = 0.0;
  double dtMs = 0.0;
  int action = 0;
};

class MouseRuntimeModel {
 public:
  static std::optional<MouseRuntimeModel> Load(const std::string& path);
  static std::vector<MouseTrajectoryPoint> GenerateFromConfig(
      double fromX, double fromY, double toX, double toY, bool clickAtEnd);

  std::vector<MouseTrajectoryPoint> decode(double fromX, double fromY,
                                           double toX, double toY,
                                           bool clickAtEnd,
                                           int maxSteps = 128,
                                           double clickThreshold = 0.98,
                                           double minDtMs = 4.0) const;

 private:
  explicit MouseRuntimeModel(RuntimeWeights weights);

  std::vector<double> linear(const std::vector<double>& input,
                             const std::string& weightName,
                             const std::string& biasName) const;
  std::vector<double> conditionEmbedding(const std::vector<double>& condition) const;
  std::vector<double> gruCell(const std::vector<double>& input,
                              const std::vector<double>& hidden,
                              int layer) const;
  std::vector<MouseTrajectoryPoint> fallback(double fromX, double fromY,
                                             double toX, double toY,
                                             bool clickAtEnd,
                                             int maxSteps) const;

  RuntimeWeights m_weights;
  nlohmann::json m_metadata;
  double m_coordinateScale = 1.0;
  int m_hiddenSize = 0;
  int m_layers = 1;
  int m_actionCount = 5;
  std::string m_positionFrame = "goal_relative_delta";
};

}  // namespace rotundacfg

#include "RuntimeWeights.hpp"

#include "mozilla/glue/Debug.h"

#include <cstdint>
#include <cstring>
#include <fstream>
#include <iterator>

namespace rotundacfg {

namespace {

std::optional<uint64_t> readLittleU64(const std::vector<uint8_t>& bytes) {
  if (bytes.size() < 8) return std::nullopt;
  uint64_t value = 0;
  for (size_t i = 0; i < 8; ++i) {
    value |= static_cast<uint64_t>(bytes[i]) << (8 * i);
  }
  return value;
}

std::vector<uint8_t> readFile(const std::string& path) {
  std::ifstream file(path, std::ios::binary);
  if (!file) return {};
  return std::vector<uint8_t>(std::istreambuf_iterator<char>(file),
                              std::istreambuf_iterator<char>());
}

}  // namespace

std::optional<RuntimeWeights> RuntimeWeights::Load(const std::string& path) {
  std::vector<uint8_t> bytes = readFile(path);
  if (bytes.empty()) {
    printf_stderr("ERROR: could not read Rotunda runtime weights: %s\n",
                  path.c_str());
    return std::nullopt;
  }

  auto headerLen = readLittleU64(bytes);
  if (!headerLen || bytes.size() < 8 + *headerLen) {
    printf_stderr("ERROR: invalid Rotunda runtime weights header: %s\n",
                  path.c_str());
    return std::nullopt;
  }

  std::string headerText(reinterpret_cast<const char*>(bytes.data() + 8),
                         static_cast<size_t>(*headerLen));
  if (!nlohmann::json::accept(headerText)) {
    printf_stderr("ERROR: invalid Rotunda runtime weights JSON header: %s\n",
                  path.c_str());
    return std::nullopt;
  }

  nlohmann::json header = nlohmann::json::parse(headerText);
  const size_t dataStart = 8 + static_cast<size_t>(*headerLen);
  RuntimeWeights weights;

  for (auto it = header.begin(); it != header.end(); ++it) {
    const std::string name = it.key();
    const nlohmann::json& entry = it.value();
    if (name == "__metadata__") {
      if (entry.is_object()) {
        for (auto meta = entry.begin(); meta != entry.end(); ++meta) {
          if (meta.value().is_string()) {
            weights.m_metadata[meta.key()] = meta.value().get<std::string>();
          }
        }
      }
      continue;
    }

    if (!entry.is_object() || entry.value("dtype", "") != "F32" ||
        !entry.contains("shape") || !entry.contains("data_offsets")) {
      printf_stderr("ERROR: unsupported tensor in Rotunda runtime weights: %s\n",
                    name.c_str());
      return std::nullopt;
    }

    std::vector<size_t> shape;
    for (const auto& dim : entry["shape"]) {
      shape.push_back(dim.get<size_t>());
    }
    const auto& offsets = entry["data_offsets"];
    if (!offsets.is_array() || offsets.size() != 2) return std::nullopt;
    size_t begin = offsets[0].get<size_t>();
    size_t end = offsets[1].get<size_t>();
    if (end < begin || dataStart + end > bytes.size() ||
        ((end - begin) % sizeof(float)) != 0) {
      printf_stderr("ERROR: invalid tensor offsets in Rotunda runtime weights: %s\n",
                    name.c_str());
      return std::nullopt;
    }

    RuntimeTensor tensor;
    tensor.shape = std::move(shape);
    tensor.values.resize((end - begin) / sizeof(float));
    std::memcpy(tensor.values.data(), bytes.data() + dataStart + begin,
                end - begin);
    weights.m_tensors[name] = std::move(tensor);
  }

  return weights;
}

const RuntimeTensor* RuntimeWeights::get(const std::string& name) const {
  auto it = m_tensors.find(name);
  return it == m_tensors.end() ? nullptr : &it->second;
}

std::optional<std::string> RuntimeWeights::metadata(
    const std::string& key) const {
  auto it = m_metadata.find(key);
  if (it == m_metadata.end()) return std::nullopt;
  return it->second;
}

std::optional<nlohmann::json> RuntimeWeights::rotundaMetadata() const {
  auto raw = metadata("rotunda_metadata");
  if (!raw || !nlohmann::json::accept(*raw)) return std::nullopt;
  return nlohmann::json::parse(*raw);
}

}  // namespace rotundacfg

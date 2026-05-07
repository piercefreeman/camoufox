#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

schema="${ML_DATA_OPENAPI_SCHEMA:-schemas/rotunda-ml-data-capture.openapi.yaml}"
output="${PY_ML_DATA_MODELS:-ml-models/rotunda_models/_generated_data_capture.py}"

uvx --from datamodel-code-generator datamodel-codegen \
  --input "$schema" \
  --input-file-type openapi \
  --output "$output" \
  --output-model-type pydantic_v2.BaseModel \
  --target-python-version 3.10 \
  --use-standard-collections \
  --use-union-operator \
  --field-constraints \
  --snake-case-field \
  --extra-fields forbid \
  --formatters black isort \
  --disable-timestamp

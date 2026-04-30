from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SCHEMA = ROOT / "schemas" / "camoufox-profile.openapi.yaml"
DEFAULT_EXAMPLE = ROOT / "example" / "fingerprint.json"
ROOT_SCHEMA_REF = "#/components/schemas/CamoufoxProfile"


class FingerprintExampleValidationError(ValueError):
    pass


class OpenApiValidator:
    def __init__(self, document: dict[str, Any]) -> None:
        self.document = document

    def validate(self, value: Any, schema: dict[str, Any], path: str = "$") -> None:
        schema = self._resolve_schema(schema)

        if "oneOf" in schema:
            self._validate_one_of(value, schema["oneOf"], path)
            return

        schema_type = schema.get("type")
        if schema_type == "object" or "properties" in schema or "additionalProperties" in schema:
            self._validate_object(value, schema, path)
            return
        if schema_type == "array":
            self._validate_array(value, schema, path)
            return
        if schema_type == "string":
            self._validate_string(value, schema, path)
            return
        if schema_type == "boolean":
            self._validate_boolean(value, path)
            return
        if schema_type == "integer":
            self._validate_integer(value, schema, path)
            return
        if schema_type == "number":
            self._validate_number(value, schema, path)
            return
        if schema_type == "null":
            if value is not None:
                raise FingerprintExampleValidationError(f"{path}: expected null, got {type(value).__name__}")
            return

        raise FingerprintExampleValidationError(
            f"{path}: unsupported schema shape with keys {sorted(schema.keys())}"
        )

    def _resolve_schema(self, schema: dict[str, Any]) -> dict[str, Any]:
        resolved = schema
        while "$ref" in resolved:
            resolved = self._resolve_ref(resolved["$ref"])
        return resolved

    def _resolve_ref(self, ref: str) -> dict[str, Any]:
        if not ref.startswith("#/"):
            raise FingerprintExampleValidationError(f"Unsupported external ref: {ref}")

        node: Any = self.document
        try:
            for part in ref[2:].split("/"):
                node = node[part]
        except (KeyError, TypeError) as exc:
            raise FingerprintExampleValidationError(f"Reference {ref} could not be resolved") from exc
        if not isinstance(node, dict):
            raise FingerprintExampleValidationError(f"Reference {ref} did not resolve to an object schema")
        return node

    def _validate_one_of(self, value: Any, options: list[dict[str, Any]], path: str) -> None:
        errors: list[str] = []
        for option in options:
            try:
                self.validate(value, option, path)
                return
            except FingerprintExampleValidationError as exc:
                errors.append(str(exc))

        detail = "; ".join(errors[:3])
        raise FingerprintExampleValidationError(
            f"{path}: value {value!r} did not match any allowed schema variant ({detail})"
        )

    def _validate_object(self, value: Any, schema: dict[str, Any], path: str) -> None:
        if not isinstance(value, dict):
            raise FingerprintExampleValidationError(f"{path}: expected object, got {type(value).__name__}")

        properties = schema.get("properties", {})
        additional_properties = schema.get("additionalProperties", True)

        missing = [key for key in properties if key not in value]
        if missing:
            missing_list = ", ".join(missing)
            raise FingerprintExampleValidationError(
                f"{path}: missing required properties: {missing_list}"
            )

        extra_keys = [key for key in value if key not in properties]
        if additional_properties is False and extra_keys:
            extras = ", ".join(extra_keys)
            raise FingerprintExampleValidationError(f"{path}: unexpected properties: {extras}")

        for key, property_schema in properties.items():
            self.validate(value[key], property_schema, f"{path}.{key}")

        if isinstance(additional_properties, dict):
            for key in extra_keys:
                self.validate(value[key], additional_properties, f"{path}.{key}")

    def _validate_array(self, value: Any, schema: dict[str, Any], path: str) -> None:
        if not isinstance(value, list):
            raise FingerprintExampleValidationError(f"{path}: expected array, got {type(value).__name__}")

        item_schema = schema.get("items")
        if not isinstance(item_schema, dict):
            raise FingerprintExampleValidationError(f"{path}: array schema is missing item definition")

        for index, item in enumerate(value):
            self.validate(item, item_schema, f"{path}[{index}]")

    def _validate_string(self, value: Any, schema: dict[str, Any], path: str) -> None:
        if not isinstance(value, str):
            raise FingerprintExampleValidationError(f"{path}: expected string, got {type(value).__name__}")

        enum = schema.get("enum")
        if enum is not None and value not in enum:
            raise FingerprintExampleValidationError(f"{path}: expected one of {enum}, got {value!r}")

    def _validate_boolean(self, value: Any, path: str) -> None:
        if not isinstance(value, bool):
            raise FingerprintExampleValidationError(f"{path}: expected boolean, got {type(value).__name__}")

    def _validate_integer(self, value: Any, schema: dict[str, Any], path: str) -> None:
        if isinstance(value, bool) or not isinstance(value, int):
            raise FingerprintExampleValidationError(f"{path}: expected integer, got {type(value).__name__}")
        self._validate_numeric_bounds(value, schema, path)

    def _validate_number(self, value: Any, schema: dict[str, Any], path: str) -> None:
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise FingerprintExampleValidationError(f"{path}: expected number, got {type(value).__name__}")
        self._validate_numeric_bounds(float(value), schema, path)

    def _validate_numeric_bounds(self, value: int | float, schema: dict[str, Any], path: str) -> None:
        minimum = schema.get("minimum")
        if minimum is not None and value < minimum:
            raise FingerprintExampleValidationError(f"{path}: expected value >= {minimum}, got {value}")

        maximum = schema.get("maximum")
        if maximum is not None and value > maximum:
            raise FingerprintExampleValidationError(f"{path}: expected value <= {maximum}, got {value}")

        exclusive_minimum = schema.get("exclusiveMinimum")
        if exclusive_minimum is not None and value <= exclusive_minimum:
            raise FingerprintExampleValidationError(f"{path}: expected value > {exclusive_minimum}, got {value}")

        exclusive_maximum = schema.get("exclusiveMaximum")
        if exclusive_maximum is not None and value >= exclusive_maximum:
            raise FingerprintExampleValidationError(f"{path}: expected value < {exclusive_maximum}, got {value}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Validate example/fingerprint.json against schemas/camoufox-profile.openapi.yaml "
            "while treating every object property as required."
        )
    )
    parser.add_argument("--schema", type=Path, default=DEFAULT_SCHEMA)
    parser.add_argument("--example", type=Path, default=DEFAULT_EXAMPLE)
    return parser.parse_args()


def load_json(path: Path) -> Any:
    try:
        with path.open(encoding="utf-8") as handle:
            return json.load(handle)
    except OSError as exc:
        raise FingerprintExampleValidationError(f"Could not read JSON file {path}") from exc
    except json.JSONDecodeError as exc:
        raise FingerprintExampleValidationError(f"Invalid JSON in {path}: {exc}") from exc


def load_yaml(path: Path) -> dict[str, Any]:
    try:
        with path.open(encoding="utf-8") as handle:
            document = yaml.safe_load(handle)
    except OSError as exc:
        raise FingerprintExampleValidationError(f"Could not read YAML file {path}") from exc
    except yaml.YAMLError as exc:
        raise FingerprintExampleValidationError(f"Invalid YAML in {path}: {exc}") from exc
    if not isinstance(document, dict):
        raise FingerprintExampleValidationError(f"{path}: expected top-level mapping")
    return document


def display_path(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def main() -> int:
    args = parse_args()
    schema_path = args.schema.resolve()
    example_path = args.example.resolve()

    document = load_yaml(schema_path)
    example = load_json(example_path)
    validator = OpenApiValidator(document)
    validator.validate(example, {"$ref": ROOT_SCHEMA_REF})

    print(
        f"Validated {display_path(example_path)} against {display_path(schema_path)} "
        "with all object properties required."
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except FingerprintExampleValidationError as exc:
        print(f"Fingerprint example validation failed: {exc}", file=sys.stderr)
        raise SystemExit(1)

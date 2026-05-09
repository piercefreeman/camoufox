from __future__ import annotations

import json
import time
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Generic, TypeVar

from platformdirs import user_cache_dir
from pydantic import BaseModel, Field, ValidationError

TModel = TypeVar("TModel", bound=BaseModel)

ROTUNDA_CACHE_DIR = Path(user_cache_dir("rotunda"))


class CachedModel(BaseModel, Generic[TModel]):
    cache_version: int
    cached_at: float = Field(default_factory=time.time)
    payload: TModel
    metadata: dict[str, str] = Field(default_factory=dict)

    @property
    def cached_at_datetime(self) -> datetime:
        return datetime.fromtimestamp(self.cached_at, tz=timezone.utc)

    def age_seconds(self, *, now: float | None = None) -> float:
        return max((time.time() if now is None else now) - self.cached_at, 0)

    def expires_at(self, max_age_seconds: float) -> float:
        return self.cached_at + max_age_seconds

    def is_fresh(
        self,
        *,
        cache_version: int,
        max_age_seconds: float,
        now: float | None = None,
    ) -> bool:
        return self.cache_version == cache_version and self.age_seconds(now=now) <= max_age_seconds


class PydanticDiskCache(Generic[TModel]):
    def __init__(
        self,
        path: Path,
        *,
        payload_model: type[TModel],
        cache_version: int,
        max_age_seconds: float,
    ) -> None:
        self.path = path
        self.payload_model = payload_model
        self.cache_version = cache_version
        self.max_age_seconds = max_age_seconds

    def read_envelope(self, *, now: float | None = None) -> CachedModel[TModel] | None:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return None
        if not isinstance(raw, dict):
            return None

        try:
            payload = self.payload_model.model_validate(raw.get("payload"))
            envelope = CachedModel(
                cache_version=int(raw.get("cache_version") or 0),
                cached_at=float(raw.get("cached_at") or 0),
                payload=payload,
                metadata=_metadata(raw.get("metadata")),
            )
        except (TypeError, ValueError, ValidationError):
            return None

        if not envelope.is_fresh(
            cache_version=self.cache_version,
            max_age_seconds=self.max_age_seconds,
            now=now,
        ):
            return None
        return envelope

    def read(self, *, now: float | None = None) -> TModel | None:
        envelope = self.read_envelope(now=now)
        return envelope.payload if envelope else None

    def write(
        self,
        payload: TModel,
        *,
        metadata: Mapping[str, str] | None = None,
        now: float | None = None,
    ) -> CachedModel[TModel]:
        envelope = CachedModel(
            cache_version=self.cache_version,
            cached_at=time.time() if now is None else now,
            payload=payload,
            metadata=dict(metadata or {}),
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.path.with_name(f".{self.path.name}.{time.time_ns()}.tmp")
        tmp_path.write_text(
            json.dumps(envelope.model_dump(mode="json"), sort_keys=True),
            encoding="utf-8",
        )
        tmp_path.replace(self.path)
        return envelope

    def get_or_create(self, factory: Callable[[], TModel]) -> TModel:
        cached = self.read()
        if cached is not None:
            return cached
        payload = factory()
        self.write(payload)
        return payload


def cache_path(*parts: str) -> Path:
    return ROTUNDA_CACHE_DIR.joinpath(*parts)


def _metadata(value: object) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    return {str(key): str(item) for key, item in value.items()}

from __future__ import annotations

from pydantic import BaseModel

from rotunda.cache import PydanticDiskCache


class Payload(BaseModel):
    value: str


def test_pydantic_disk_cache_wraps_payload_with_fresh_envelope(tmp_path) -> None:
    cache = PydanticDiskCache(
        tmp_path / "payload.json",
        payload_model=Payload,
        cache_version=3,
        max_age_seconds=60,
    )

    envelope = cache.write(Payload(value="ready"), now=100, metadata={"source": "test"})
    cached = cache.read_envelope(now=120)

    assert envelope.cache_version == 3
    assert cached is not None
    assert cached.payload.value == "ready"
    assert cached.metadata == {"source": "test"}
    assert cached.age_seconds(now=120) == 20
    assert cached.expires_at(60) == 160


def test_pydantic_disk_cache_invalidates_stale_and_wrong_version_payloads(tmp_path) -> None:
    path = tmp_path / "payload.json"
    cache = PydanticDiskCache(
        path,
        payload_model=Payload,
        cache_version=1,
        max_age_seconds=10,
    )
    cache.write(Payload(value="old"), now=100)

    assert cache.read(now=111) is None
    assert (
        PydanticDiskCache(
            path,
            payload_model=Payload,
            cache_version=2,
            max_age_seconds=10,
        ).read(now=105)
        is None
    )


def test_pydantic_disk_cache_get_or_create_uses_fresh_cache(tmp_path) -> None:
    cache = PydanticDiskCache(
        tmp_path / "payload.json",
        payload_model=Payload,
        cache_version=1,
        max_age_seconds=60,
    )
    calls = 0

    def factory() -> Payload:
        nonlocal calls
        calls += 1
        return Payload(value=f"value-{calls}")

    assert cache.get_or_create(factory).value == "value-1"
    assert cache.get_or_create(factory).value == "value-1"
    assert calls == 1

"""内蔵model manifestの読み込み。"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any


class ModelManifestError(ValueError):
    """manifestの形状または必須情報が不正。"""


@dataclass(frozen=True)
class ModelManifest:
    model_id: str
    artifact: str
    format: str
    quantization: str
    runtime: str
    license: str
    license_url: str
    source_url: str
    weights_in_source_control: bool
    release_bundle_required: bool
    model_sha256: str | None
    artifact_status: str

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "ModelManifest":
        required = {
            "model_id",
            "artifact",
            "format",
            "quantization",
            "runtime",
            "license",
            "license_url",
            "source_url",
            "weights_in_source_control",
            "release_bundle_required",
            "model_sha256",
            "artifact_status",
        }
        if set(raw) != {"schema_version", *required}:
            raise ModelManifestError("model manifest keys do not match the contract")
        if raw["format"] != "GGUF" or raw["runtime"] != "llama.cpp":
            raise ModelManifestError("P0 requires GGUF and llama.cpp")
        if raw["weights_in_source_control"] is not False:
            raise ModelManifestError("model weights must not be source-controlled")
        checksum = raw["model_sha256"]
        if checksum is not None and (
            not isinstance(checksum, str)
            or len(checksum) != 64
            or any(character not in "0123456789abcdefABCDEF" for character in checksum)
        ):
            raise ModelManifestError("model_sha256 must be null or a SHA-256 hex string")
        return cls(**{key: raw[key] for key in required})


def load_manifest(path: Path) -> ModelManifest:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ModelManifestError(f"could not read model manifest: {path}") from exc
    if not isinstance(raw, dict):
        raise ModelManifestError("model manifest must be an object")
    return ModelManifest.from_dict(raw)

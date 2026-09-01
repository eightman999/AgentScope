"""内蔵model manifestの読み込み。"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from urllib.parse import urlsplit
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
    artifact_url: str
    model_size_bytes: int
    weights_in_source_control: bool
    release_bundle_required: bool
    model_sha256: str | None
    artifact_status: str

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "ModelManifest":
        if raw.get("schema_version") != "0.1":
            raise ModelManifestError("unsupported model manifest schema_version")
        required = {
            "model_id",
            "artifact",
            "format",
            "quantization",
            "runtime",
            "license",
            "license_url",
            "source_url",
            "artifact_url",
            "model_size_bytes",
            "weights_in_source_control",
            "release_bundle_required",
            "model_sha256",
            "artifact_status",
        }
        if set(raw) != {"schema_version", *required}:
            raise ModelManifestError("model manifest keys do not match the contract")
        if raw["format"] != "GGUF" or raw["runtime"] != "llama.cpp":
            raise ModelManifestError("P0 requires GGUF and llama.cpp")
        for field_name in ("model_id", "artifact", "quantization", "license", "license_url", "source_url", "artifact_url", "artifact_status"):
            if not isinstance(raw[field_name], str) or not raw[field_name].strip():
                raise ModelManifestError(f"{field_name} must be a non-empty string")
        artifact_path = Path(raw["artifact"])
        if (
            artifact_path.is_absolute()
            or artifact_path.name != raw["artifact"]
            or raw["artifact"] in {".", ".."}
        ):
            raise ModelManifestError("artifact must be a relative file name")
        for field_name in ("license_url", "source_url", "artifact_url"):
            parsed_url = urlsplit(raw[field_name])
            if parsed_url.scheme != "https" or not parsed_url.netloc:
                raise ModelManifestError(f"{field_name} must be an https URL")
        if raw["weights_in_source_control"] is not False:
            raise ModelManifestError("model weights must not be source-controlled")
        if raw["release_bundle_required"] is not True:
            raise ModelManifestError("model weights require a release bundle")
        if (
            not isinstance(raw["model_size_bytes"], int)
            or isinstance(raw["model_size_bytes"], bool)
            or raw["model_size_bytes"] < 1
        ):
            raise ModelManifestError("model_size_bytes must be a positive integer")
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

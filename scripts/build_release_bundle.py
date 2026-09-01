#!/usr/bin/env python3
"""wheel・local model・llama.cppを検証済みbundleへまとめる。"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tomllib
from typing import Iterable


ROOT = Path(__file__).resolve().parents[1]
RESOURCE_ROOT = ROOT / "resources"
SYSTEM_PREFIXES = (Path("/usr/lib"), Path("/System"), Path("/Library"))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _require_file(path: Path, label: str) -> Path:
    if not path.is_file():
        raise SystemExit(f"{label} was not found: {path}")
    return path


def _load_json(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SystemExit(f"could not read JSON: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise SystemExit(f"JSON root must be an object: {path}")
    return value


def _runtime_version(path: Path) -> str:
    try:
        completed = subprocess.run(
            [str(path), "--version"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise SystemExit(f"could not inspect runtime version: {exc}") from exc
    lines = completed.stdout.strip().splitlines()
    if completed.returncode != 0 or not lines:
        raise SystemExit("llama.cpp runtime --version failed")
    for line in lines:
        if line.lower().startswith("version:"):
            return line[:500]
    return lines[0][:500]


def _otool_lines(path: Path, *args: str) -> list[str]:
    try:
        completed = subprocess.run(
            ["otool", *args, str(path)],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise SystemExit(f"could not inspect runtime binary with otool: {exc}") from exc
    if completed.returncode != 0:
        raise SystemExit(completed.stderr.strip() or f"otool failed for {path}")
    return completed.stdout.splitlines()


def _dependencies(path: Path) -> list[str]:
    dependencies: list[str] = []
    for line in _otool_lines(path, "-L")[1:]:
        value = line.strip().split(" (", 1)[0]
        if value:
            dependencies.append(value)
    return dependencies


def _rpaths(path: Path) -> list[str]:
    lines = _otool_lines(path, "-l")
    result: list[str] = []
    for index, line in enumerate(lines):
        if "cmd LC_RPATH" not in line:
            continue
        for candidate in lines[index + 1 : index + 5]:
            stripped = candidate.strip()
            if stripped.startswith("path "):
                result.append(stripped.split(" ", 2)[1])
                break
    return result


def _is_system_path(path: Path) -> bool:
    return any(path == prefix or prefix in path.parents for prefix in SYSTEM_PREFIXES)


def _candidate_search_dirs(source: Path, runtime_source: Path) -> Iterable[Path]:
    seen: set[Path] = set()
    candidates = [
        source.parent,
        runtime_source.parent,
        runtime_source.parent.parent / "lib",
        Path("/opt/homebrew/lib"),
        Path("/opt/homebrew/opt/llama.cpp/lib"),
        Path("/opt/homebrew/opt/ggml/lib"),
        Path("/opt/homebrew/opt/openssl@3/lib"),
        Path("/opt/homebrew/opt/libomp/lib"),
    ]
    for candidate in candidates:
        candidate = candidate.resolve()
        if candidate not in seen and candidate.is_dir():
            seen.add(candidate)
            yield candidate


def _resolve_dependency(
    dependency: str,
    *,
    source: Path,
    runtime_source: Path,
) -> Path | None:
    if dependency.startswith("@loader_path/"):
        candidate = (source.parent / dependency.removeprefix("@loader_path/")).resolve()
        return candidate if candidate.is_file() else None
    if dependency.startswith("@executable_path/"):
        candidate = (runtime_source.parent / dependency.removeprefix("@executable_path/")).resolve()
        return candidate if candidate.is_file() else None
    if dependency.startswith("@rpath/"):
        name = dependency.removeprefix("@rpath/")
        for directory in _candidate_search_dirs(source, runtime_source):
            candidate = directory / name
            if candidate.is_file():
                return candidate.resolve()
        return None
    candidate = Path(dependency)
    if _is_system_path(candidate):
        return None
    return candidate.resolve() if candidate.is_file() else None


def _collect_runtime_dependencies(runtime_source: Path) -> dict[Path, list[str]]:
    root = runtime_source.resolve()
    dependencies: dict[Path, list[str]] = {}
    pending = [root]
    while pending:
        source = pending.pop()
        if source in dependencies:
            continue
        resolved: list[str] = []
        dependencies[source] = resolved
        for dependency in _dependencies(source):
            resolved.append(dependency)
            candidate = _resolve_dependency(
                dependency,
                source=source,
                runtime_source=root,
            )
            if candidate is None:
                if dependency.startswith(("@rpath/", "@loader_path/", "@executable_path/")):
                    raise SystemExit(
                        f"could not resolve bundled runtime dependency {dependency} from {source}"
                    )
                continue
            if candidate != source and candidate not in dependencies:
                pending.append(candidate)
    return dependencies


def _run_install_name_tool(arguments: list[str], path: Path) -> None:
    try:
        completed = subprocess.run(
            ["install_name_tool", *arguments, str(path)],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise SystemExit(f"could not rewrite runtime dependency names: {exc}") from exc
    if completed.returncode != 0:
        raise SystemExit(completed.stderr.strip() or f"install_name_tool failed for {path}")


def _bundle_runtime(runtime_source: Path, destination: Path) -> dict[str, str]:
    runtime_source = _require_file(runtime_source, "llama.cpp runtime").resolve()
    if platform.system() != "Darwin":
        raise SystemExit("the P0 runtime bundle currently supports macOS (Darwin) only")
    dependency_map = _collect_runtime_dependencies(runtime_source)
    runtime_bin = destination / "runtime" / "bin" / runtime_source.name
    runtime_lib = destination / "runtime" / "lib"
    runtime_bin.parent.mkdir(parents=True, exist_ok=True)
    runtime_lib.mkdir(parents=True, exist_ok=True)
    destination_by_source: dict[Path, Path] = {runtime_source: runtime_bin}
    for source in dependency_map:
        if source == runtime_source:
            continue
        destination_by_source[source] = runtime_lib / source.name
    for source, target in destination_by_source.items():
        shutil.copy2(source, target)

    source_by_dependency: dict[str, Path] = {}
    for source in dependency_map:
        for dependency in dependency_map[source]:
            candidate = _resolve_dependency(
                dependency,
                source=source,
                runtime_source=runtime_source,
            )
            if candidate in destination_by_source:
                source_by_dependency[dependency] = candidate
    for source, target in destination_by_source.items():
        for dependency in dependency_map[source]:
            bundled_source = source_by_dependency.get(dependency)
            if bundled_source is not None:
                _run_install_name_tool(
                    ["-change", dependency, f"@rpath/{bundled_source.name}"],
                    target,
                )
        if target.suffix == ".dylib":
            _run_install_name_tool(["-id", f"@rpath/{target.name}"], target)
            if not _rpaths(target):
                _run_install_name_tool(["-add_rpath", "@loader_path"], target)
        elif not _rpaths(target):
            _run_install_name_tool(["-add_rpath", "@loader_path/../lib"], target)

    for target in sorted(runtime_lib.glob("*.dylib")):
        try:
            signed = subprocess.run(
                ["codesign", "--force", "--sign", "-", str(target)],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
                timeout=30,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise SystemExit(f"could not ad-hoc sign runtime library: {exc}") from exc
        if signed.returncode != 0:
            raise SystemExit(signed.stderr.strip() or f"codesign failed for {target}")
    try:
        signed = subprocess.run(
            ["codesign", "--force", "--sign", "-", str(runtime_bin)],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise SystemExit(f"could not ad-hoc sign runtime bundle: {exc}") from exc
    if signed.returncode != 0:
        raise SystemExit(signed.stderr.strip() or "codesign failed for runtime bundle")
    if _runtime_version(runtime_bin) != _runtime_version(runtime_source):
        raise SystemExit("bundled runtime version differs from the source runtime")
    return {
        path.relative_to(destination).as_posix(): _sha256(path)
        for path in sorted(destination.rglob("*"))
        if path.is_file()
    }


def _copy_resources(destination: Path, model_path: Path, manifest: dict[str, object]) -> None:
    target_root = destination / "resources"
    target_root.mkdir(parents=True, exist_ok=True)
    for source in sorted(RESOURCE_ROOT.iterdir()):
        if source.name == "models":
            continue
        if source.is_file():
            shutil.copy2(source, target_root / source.name)
    model_target = target_root / "models" / str(manifest["artifact"])
    model_target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(model_path, model_target)


def _write_launcher(destination: Path) -> None:
    launcher = destination / "run.sh"
    launcher.write_text(
        "#!/bin/sh\n"
        "set -eu\n"
        "BUNDLE_DIR=$(CDPATH= cd -- \"$(dirname -- \"$0\")\" && pwd)\n"
        "export AGENTSCOPE_RESOURCE_ROOT=\"$BUNDLE_DIR/resources\"\n"
        "export PATH=\"$BUNDLE_DIR/runtime/bin:$PATH\"\n"
        "exec agentscope \"$@\"\n",
        encoding="utf-8",
    )
    launcher.chmod(0o755)


def _file_entries(root: Path) -> dict[str, dict[str, object]]:
    return {
        path.relative_to(root).as_posix(): {
            "size_bytes": path.stat().st_size,
            "sha256": _sha256(path),
        }
        for path in sorted(root.rglob("*"))
        if path.is_file() and path.name != "release-manifest.json"
    }


def build_bundle(
    *,
    output: Path,
    wheel: Path,
    model: Path,
    runtime: Path,
) -> Path:
    output = output.resolve()
    if output.exists():
        raise SystemExit(f"output already exists; choose a new path: {output}")
    wheel = _require_file(wheel.resolve(), "package wheel")
    model = _require_file(model.resolve(), "model artifact")
    runtime = _require_file(runtime.resolve(), "llama.cpp runtime")
    raw_manifest = _load_json(RESOURCE_ROOT / "model-manifest.json")
    artifact = raw_manifest.get("artifact")
    expected_size = raw_manifest.get("model_size_bytes")
    expected_sha = raw_manifest.get("model_sha256")
    if not isinstance(artifact, str) or not artifact:
        raise SystemExit("model manifest artifact is invalid")
    if model.name != artifact:
        raise SystemExit(f"model filename does not match manifest: {model.name} != {artifact}")
    if model.stat().st_size != expected_size or _sha256(model) != expected_sha:
        raise SystemExit("model size or checksum does not match resources/model-manifest.json")
    output.mkdir(parents=True)
    _copy_resources(output, model, raw_manifest)
    shutil.copy2(ROOT / "LICENSE", output / "LICENSE")
    shutil.copy2(ROOT / "README.md", output / "README.md")
    package_target = output / "packages" / wheel.name
    package_target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(wheel, package_target)
    runtime_files = _bundle_runtime(runtime, output)
    _write_launcher(output)
    with (ROOT / "pyproject.toml").open("rb") as stream:
        project = tomllib.load(stream)["project"]
    release_manifest = {
        "schema_version": "0.1",
        "project": {
            "name": project["name"],
            "version": project["version"],
            "license": "Apache-2.0",
            "wheel": package_target.relative_to(output).as_posix(),
        },
        "model": {
            "id": raw_manifest["model_id"],
            "artifact": raw_manifest["artifact"],
            "format": raw_manifest["format"],
            "quantization": raw_manifest["quantization"],
            "license": raw_manifest["license"],
            "source_url": raw_manifest["source_url"],
            "size_bytes": model.stat().st_size,
            "sha256": _sha256(output / "resources" / "models" / artifact),
        },
        "runtime": {
            "name": runtime.name,
            "version": _runtime_version(output / "runtime" / "bin" / runtime.name),
            "files": runtime_files,
        },
        "files": _file_entries(output),
    }
    (output / "release-manifest.json").write_text(
        json.dumps(release_manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--wheel", type=Path, required=True)
    parser.add_argument(
        "--model",
        type=Path,
        default=RESOURCE_ROOT / "models" / "Qwen3-0.6B-Q8_0.gguf",
    )
    parser.add_argument("--runtime", type=Path, default=Path("/opt/homebrew/bin/llama-cli"))
    args = parser.parse_args()
    build_bundle(
        output=args.output,
        wheel=args.wheel,
        model=args.model,
        runtime=args.runtime,
    )
    print(args.output.resolve())
    return 0


if __name__ == "__main__":
    sys.exit(main())

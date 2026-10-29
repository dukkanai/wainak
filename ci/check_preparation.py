#!/usr/bin/env python3
"""Offline source/config validation only. Never installs, compiles or invokes tools."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ci.testflight import policy as testflight_policy
from ci.rename_provenance import source_matches, source_path

BASE = "120a0c24970427438af7c693e772b95050b3fcfc"
NATIVE = "5ff300d48b38e98212ff8b5a7333dd92f8c1c3ff"
COMMANDS = [
    "python3 ci/check_preparation.py",
    "python3 -m unittest discover -s ci/tests -p 'test_*.py' -v",
    "python3 -m unittest discover -s ci/native -p 'test_*.py' -v",
    "python3 ci/native/build.py --check",
    "python3 ci/ios/build.py --build-unsigned",
]


class InvalidPreparation(ValueError):
    pass


def require(ok: bool, reason: str) -> None:
    if not ok:
        raise InvalidPreparation(reason)


def no_duplicates(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "duplicate_json_key")
        result[key] = value
    return result


def read_json(path: Path):
    require(path.is_file() and not path.is_symlink(), "not_regular_json")
    require(path.stat().st_size <= 1024 * 1024, "json_too_large")
    return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=no_duplicates)


def validate_workflow(config) -> None:
    # JSON is a strict subset of YAML. Exact keys keep the workflow manually started only:
    # unsigned recipes retain their original no-signing/no-publishing policy.
    # The signed recipe has a separate exact internal-only allowlist.
    require(isinstance(config, dict) and set(config) == {"workflows"}, "workflow_root")
    workflows = config["workflows"]
    labels = {
        "ios-unsigned-archive": "iOS unsigned archive — manual compile validation (not runtime)",
        "ios-unsigned-40gib-experiment": "iOS unsigned compile — one 40 GiB logical-space experiment",
    }
    require(isinstance(workflows, dict) and set(workflows) == set(labels) | {"ios-testflight"}, "workflow_count")
    try:
        testflight_policy.validate_workflow(workflows["ios-testflight"])
    except testflight_policy.PolicyError as error:
        raise InvalidPreparation(str(error)) from None
    for key, label in labels.items():
        workflow = workflows[key]
        require(isinstance(workflow, dict), "workflow_type")
        require(set(workflow) == {"name", "instance_type", "max_build_duration", "environment", "scripts"}, "workflow_keys")
        require(workflow["name"] == label, "workflow_label")
        require(workflow["instance_type"] == "mac_mini_m2", "not_personal_m2")
        require(type(workflow["max_build_duration"]) is int and workflow["max_build_duration"] == 45, "duration")
        require(workflow["environment"] == {"xcode": "26.4.1", "flutter": "3.47.8"}, "environment")
        commands = list(COMMANDS)
        if key == "ios-unsigned-40gib-experiment":
            commands[-1] += " --logical-workspace-40gib-experiment"
        scripts = workflow["scripts"]
        require(isinstance(scripts, list) and len(scripts) == len(commands), "scripts_count")
        for step, command in zip(scripts, commands):
            require(isinstance(step, dict) and set(step) == {"name", "script"}, "script_keys")
            require(isinstance(step["name"], str) and 0 < len(step["name"]) < 100, "script_name")
            require(step["script"] == command, "unreviewed_workflow_command")


def checked_file(root: Path, relative: str) -> Path:
    require(isinstance(relative, str), "path_type")
    path = PurePosixPath(relative)
    require(not path.is_absolute() and ".." not in path.parts and str(path) == relative, "unsafe_path")
    current = root
    for part in path.parts:
        current = current / part
        require(not current.is_symlink(), "symlink_path")
    require(current.is_file(), "missing_source")
    return current


def validate_sources(root: Path, provenance, deltas) -> int:
    require(provenance.get("schema") == 1, "provenance_schema")
    require(provenance.get("source_commit") == NATIVE and provenance.get("mobile_base_commit") == BASE, "source_anchor")
    files = provenance.get("files")
    require(isinstance(files, dict) and len(files) == 22, "source_count")
    required = {
        "archive/archive.go", "archive/archive_test.go", "archive/interop_test.go",
        "archive/go.mod", "archive/go.sum", "archivebridge/bridge.go",
        "archivebridge/bridge_test.go", "archivebridge/go.mod", "archivebridge/go.sum",
    }
    require(required <= set(files) and all(name in required or name.startswith("archive/notices/") for name in files), "source_allowlist")
    require(deltas.get("schema") == 1 and isinstance(deltas.get("files"), dict), "delta_schema")
    allowed = {"archive/go.mod", "archive/go.sum", "archivebridge/go.mod", "archivebridge/go.sum", "archive/interop_test.go"}
    require(set(deltas["files"]) <= allowed, "unexpected_core_delta")
    for name, change in deltas["files"].items():
        require(change["before_sha256"] == files[name] and isinstance(change["reason"], str) and change["reason"], "delta_anchor")
    for name, original_digest in files.items():
        digest = deltas["files"].get(name, {}).get("after_sha256", original_digest)
        require(isinstance(digest, str) and len(digest) == 64 and all(c in "0123456789abcdef" for c in digest), "digest_format")
        data = source_path(root, name).read_bytes()
        require(len(data) < 1024 * 1024 and source_matches(root, name, digest), "source_digest")
    return len(files)


def validate_android(root: Path, baseline, deltas) -> int:
    require(baseline.get("commit") == BASE and isinstance(baseline.get("files"), dict), "android_anchor")
    require(len(baseline["files"]) > 10, "android_inventory")
    require(deltas.get("schema") == 1 and isinstance(deltas.get("files"), dict), "android_delta_schema")
    only = "apps/mobile/android/app/src/main/kotlin/invalid/example/wainak/wainak_mobile/NativeArchiveChannel.kt"
    require(set(deltas["files"]) == {only}, "android_delta_scope")
    require(deltas["files"][only]["before_sha256"] == baseline["files"][only], "android_delta_anchor")
    for name, original_digest in baseline["files"].items():
        digest = deltas["files"].get(name, {}).get("after_sha256", original_digest)
        require(name.startswith("apps/mobile/android/"), "android_scope")
        require(source_matches(root, name, digest), "android_changed")
    return len(baseline["files"])


def validate_ios(root: Path, manifest) -> int:
    require(manifest.get("schema") == 1 and len(manifest.get("files", {})) == 16, "ios_manifest")
    for name, digest in manifest["files"].items():
        require(name.startswith(("apps/mobile/ios/", "apps/mobile/test/", "apps/mobile/lib/", "docs/")), "ios_file_scope")
        require(source_matches(root, name, digest), "ios_source_digest")
    return len(manifest["files"])


def validate_parity(root: Path, manifest) -> int:
    require(manifest.get("schema") == 1 and len(manifest.get("modified", {})) == 4 and len(manifest.get("new_source_files", {})) == 3, "parity_inventory")
    expected = {name: change["after_sha256"] for name, change in manifest["modified"].items()}
    expected.update(manifest["new_source_files"])
    for name, digest in expected.items():
        require(name.startswith("apps/mobile/"), "parity_scope")
        require(source_matches(root, name, digest), "parity_source_digest")
    return len(expected)


def main() -> None:
    validate_workflow(read_json(ROOT / "codemagic.yaml"))
    require(checked_file(ROOT, "ci/testflight/Signing.xcconfig").read_text() == testflight_policy.SIGNING_CONFIG, "testflight_signing_config")
    source_count = validate_sources(ROOT, read_json(ROOT / "ci/source-provenance.json"), read_json(ROOT / "ci/native-source-deltas.json"))
    android_count = validate_android(ROOT, read_json(ROOT / "ci/android-baseline.json"), read_json(ROOT / "ci/android-source-deltas.json"))
    ios_count = validate_ios(ROOT, read_json(ROOT / "ci/ios-source-provenance.json"))
    parity_count = validate_parity(ROOT, read_json(ROOT / "ci/android-parity-provenance.json"))
    print(json.dumps({"ios_files": ios_count, "parity_files": parity_count, "status": "STATIC_SOURCE_CONFIG_PASS", "native_source_files": source_count,
                      "anchored_android_files": android_count, "native_recipe_executed": False,
                      "mac_xcode_swift_execution": "NOT_RUN", "signing": "INTERNAL_RECIPE_PREPARED_NOT_EXECUTED"}))


if __name__ == "__main__":
    main()

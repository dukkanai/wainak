"""Independent read-only comparison of the four approved SDK package archives."""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import stat
import xml.etree.ElementTree as ET
import zipfile

LICENSE_SHA = "1f8729233617b193fd619213792ae16a41b95d2bbbf525dfe66998252ba68b16"
XML_SHA = "13a7a28e4467408860995a32b5c3bc7b0e2f66088c21e42bf7ceabc025afc716"
CLI_SHA = "4e4c464f145a7512b57d088ac6c278c03c9eea610886b35a5e0804e74eedf583"
PACKAGES = {
    "cmdline-tools;22.0": ("cmdline-tools/22.0", "commandlinetools-linux-15859902_latest.zip"),
    "platforms;android-36": ("platforms/android-36", "platform-36_r02.zip"),
    "build-tools;36.0.0": ("build-tools/36.0.0", "build-tools_r36_linux.zip"),
    "ndk;30.0.16248370": ("ndk/30.0.16248370", "android-ndk-r30-linux.zip"),
}


def need(condition, code):
    if not condition:
        raise ValueError(code)


def sha(path, algorithm="sha256"):
    with Path(path).open("rb") as f:
        return hashlib.file_digest(f, algorithm).hexdigest()


def verify(root):
    need(os.geteuid() == 1001, "expected_chatbot")
    need(not root.is_symlink() and root.stat().st_uid == 1001, "tools_owner")
    evidence = root / "logs/sdk-ipv4-20261024T2342"
    xml = evidence / "repository2-4.xml"
    need(sha(xml) == XML_SHA, "repository_snapshot")
    doc = ET.parse(xml).getroot()
    tag = lambda node: node.tag.split("}")[-1]
    license_node = next(x for x in doc if tag(x) == "license" and x.get("id") == "android-sdk-license")
    license_bytes = "".join(license_node.itertext()).encode()
    need(hashlib.sha256(license_bytes).hexdigest() == LICENSE_SHA, "license_exact_text")
    need((evidence / "android-sdk-license.txt").read_bytes() == license_bytes, "license_retained")
    acceptance = json.loads((evidence / "license-accepted.json").read_bytes())
    need(acceptance["receipt"] == "Sentinel_a8bb0e57af688191b551aa7d467a2212", "approval_receipt")
    need(acceptance["text_sha256"] == LICENSE_SHA, "approval_text")
    need(set(acceptance["packages"]) == set(PACKAGES), "approval_package_scope")
    fingerprints = (root / "sdk/licenses/android-sdk-license").read_text().split()
    need(len(fingerprints) == 1, "accepted_license_scope")
    canonical_fingerprints = set()
    results = []
    for package, (location, archive_name) in PACKAGES.items():
        node = next(x for x in doc if tag(x) == "remotePackage" and x.get("path") == package)
        need([x.get("ref") for x in node if tag(x) == "uses-license"] == ["android-sdk-license"], "package_license")
        complete = next(x for x in node.iter() if tag(x) == "complete" and any(
            tag(y) == "url" and y.text == archive_name for y in x
        ))
        values = {tag(x): x for x in complete}
        archive = root / "downloads" / archive_name
        need(archive.is_file() and not archive.is_symlink(), "archive_type")
        need(archive.stat().st_size == int(values["size"].text), "archive_size")
        algorithm = values["checksum"].get("type")
        need(algorithm in ("sha1", "sha256"), "publisher_checksum_algorithm")
        need(sha(archive, algorithm) == values["checksum"].text, "publisher_checksum")
        archive_sha = sha(archive)
        if package.startswith("cmdline-tools;"):
            need(archive_sha == CLI_SHA, "command_tools_published_sha256")
        base = root / "sdk" / location
        need(base.is_dir() and not base.is_symlink() and base.stat().st_uid == 1001, "package_root")
        seen, records, expanded, symlinks = set(), [], 0, 0
        with zipfile.ZipFile(archive) as z:
            need(len(z.infolist()) <= 20000, "archive_member_count")
            for member in z.infolist():
                name = member.orig_filename
                posix = PurePosixPath(name)
                need(name and "\x00" not in name and "\\" not in name and ":" not in name,
                     "archive_member_name")
                need(not posix.is_absolute() and ".." not in posix.parts, "archive_member_path")
                need(not member.flag_bits & 1, "archive_encryption")
                if len(posix.parts) == 1:
                    need(member.is_dir(), "archive_root_not_directory")
                    continue
                relative = Path(*posix.parts[1:])
                need(str(relative) not in seen, "archive_duplicate")
                seen.add(str(relative))
                expanded += member.file_size
                need(expanded <= 3 * 1024**3 and member.file_size <= 1024**3, "archive_expansion")
                path = base / relative
                mode = member.external_attr >> 16
                need(path.lstat().st_uid == 1001, "installed_owner")
                if stat.S_ISDIR(mode):
                    need(path.is_dir() and not path.is_symlink(), "installed_directory")
                elif stat.S_ISLNK(mode):
                    target = z.read(member).decode("utf-8", "strict")
                    need(path.is_symlink() and os.readlink(path) == target, "installed_link")
                    need(path.resolve(strict=True).is_relative_to(base.resolve()), "installed_link_escape")
                    symlinks += 1
                    records.append({"path": str(relative), "symlink": target})
                else:
                    need(stat.S_ISREG(mode) and path.is_file() and not path.is_symlink(), "installed_file")
                    need(path.resolve().is_relative_to(base.resolve()), "installed_file_escape")
                    need(path.stat().st_size == member.file_size, "installed_size")
                    with z.open(member) as f:
                        expected = hashlib.file_digest(f, "sha256").hexdigest()
                    need(sha(path) == expected, "installed_bytes")
                    need(not path.stat().st_mode & 0o022, "installed_file_writable_by_other")
                    records.append({"path": str(relative), "sha256": expected})
        actual = {str(x.relative_to(base)) for x in base.rglob("*") if x.is_file() or x.is_symlink()}
        expected = {x["path"] for x in records}
        need(actual - expected <= {"package.xml"}, "unexpected_installed_file")
        metadata = base / "package.xml"
        if metadata.exists():
            need(metadata.is_file() and not metadata.is_symlink(), "package_metadata_type")
            installed_xml = ET.parse(metadata).getroot()
            installed_licenses = [x for x in installed_xml.iter() if tag(x) == "license"]
            need(len(installed_licenses) == 1 and installed_licenses[0].get("id") == "android-sdk-license",
                 "installed_metadata_license_id")
            canonical_text = "".join(installed_licenses[0].itertext())
            need(" ".join(canonical_text.split()) == " ".join(license_bytes.decode().split()),
                 "installed_metadata_license_text")
            canonical_hash = hashlib.sha1(canonical_text.encode()).hexdigest()
            need(fingerprints == [canonical_hash], "accepted_license_fingerprint")
            canonical_fingerprints.add(canonical_hash)
        else:
            need(package == "cmdline-tools;22.0", "missing_installed_metadata")
        manifest_hash = hashlib.sha256(json.dumps(records, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        results.append({"package": package, "archive_sha256": archive_sha,
                        "publisher_checksum_type": algorithm,
                        "publisher_checksum": values["checksum"].text,
                        "archive_bytes": archive.stat().st_size, "expanded_bytes": expanded,
                        "regular_files": len(records) - symlinks, "symlinks": symlinks,
                        "verified_tree_manifest_sha256": manifest_hash})
    need(canonical_fingerprints == set(fingerprints), "installed_canonical_license_consistency")
    return {"repository_sha256": XML_SHA, "approved_license_sha256": LICENSE_SHA,
            "license_fingerprint": fingerprints[0], "accepted_record_sha256": sha(evidence / "license-accepted.json"),
            "packages": results, "scope": "Read-only archive/license/installed-tree comparison; no native code execution."}


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("tools_root", type=Path)
    args = p.parse_args()
    print(json.dumps(verify(args.tools_root), indent=2, sort_keys=True))

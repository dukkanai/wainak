"""Read-only bounded AAR/APK structural audit, not a signature/runtime verifier."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import stat
import struct
import zipfile

MAX_ARCHIVE = 512 * 1024 * 1024
MAX_EXPANDED = 1024 * 1024 * 1024
MAX_MEMBER = 256 * 1024 * 1024
SIGNER_IDS = {0x7109871A: "v2", 0xF05368C0: "v3", 0x1B93AD61: "v3.1"}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def signing_block(f, central_offset):
    if central_offset < 24:
        return []
    f.seek(central_offset - 24)
    tail = f.read(24)
    if tail[8:] != b"APK Sig Block 42":
        return []
    size = struct.unpack("<Q", tail[:8])[0]
    require(24 <= size <= 4 * 1024 * 1024, "signing_block_size")
    start = central_offset - size - 8
    require(start >= 0, "signing_block_start")
    f.seek(start)
    block = f.read(size + 8)
    require(len(block) == size + 8, "signing_block_truncated")
    require(struct.unpack("<Q", block[:8])[0] == size, "signing_block_lengths")
    pos, end, ids = 8, len(block) - 24, []
    while pos < end:
        require(pos + 8 <= end, "signing_entry_header")
        length = struct.unpack_from("<Q", block, pos)[0]
        pos += 8
        require(4 <= length <= end - pos, "signing_entry_size")
        item = struct.unpack_from("<I", block, pos)[0]
        require(item not in ids, "signing_entry_duplicate")
        ids.append(item)
        pos += length
    require(pos == end, "signing_entry_trailing")
    return ids


def elf_segments(prefix, total_size):
    require(len(prefix) >= 64 and prefix[:4] == b"\x7fELF", "elf_header")
    require(prefix[4:7] == b"\x02\x01\x01", "elf_not_64bit_little_endian")
    fields = struct.unpack_from("<HHIQQQIHHHHHH", prefix, 16)
    kind, machine, version, _, phoff, _, _, ehsize, entsize, count, *_ = fields
    require(kind == 3 and machine == 183 and version == 1, "elf_not_aarch64_shared")
    require(ehsize == 64 and entsize == 56 and 0 < count <= 128, "elf_program_headers")
    require(phoff + count * entsize <= len(prefix), "elf_header_bounds")
    loads, relro = [], []
    for i in range(count):
        typ, flags, offset, address, _, filesz, memsz, align = struct.unpack_from(
            "<IIQQQQQQ", prefix, phoff + i * entsize
        )
        require(offset <= total_size and filesz <= total_size - offset, "elf_file_bounds")
        if typ == 1:
            require(memsz >= filesz and align > 0 and not align & (align - 1), "elf_load")
            require(offset % align == address % align, "elf_load_congruence")
            loads.append({"offset": offset, "vaddr": address, "filesz": filesz,
                          "memsz": memsz, "align": align, "flags": flags})
        elif typ == 0x6474E552:
            relro.append({"offset": offset, "vaddr": address, "filesz": filesz,
                          "memsz": memsz, "align": align})
    require(loads, "elf_no_load")
    return {"machine": "AARCH64", "load_segments": loads, "relro_segments": relro,
            "all_load_alignments_at_least_16k": all(x["align"] >= 16384 for x in loads)}


def inspect(path, kind):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as f:
        st = os.fstat(f.fileno())
        require(stat.S_ISREG(st.st_mode) and st.st_size <= MAX_ARCHIVE, "artifact_type_size")
        archive_hash = hashlib.file_digest(f, "sha256").hexdigest()
        f.seek(0)
        with zipfile.ZipFile(f) as z:
            rows = z.infolist()
            require(0 < len(rows) <= 20000, "member_count")
            require(sum(x.file_size for x in rows) <= MAX_EXPANDED, "expanded_limit")
            ids = signing_block(f, z.start_dir) if kind == "apk" else []
            seen, native, signatures = set(), [], []
            for item in rows:
                name = item.orig_filename
                p = PurePosixPath(name)
                require(name and "\x00" not in name and "\\" not in name,
                        "member_name")
                require(not p.is_absolute() and ".." not in p.parts and ":" not in name,
                        "member_path")
                require(name not in seen and item.file_size <= MAX_MEMBER, "member_duplicate_size")
                seen.add(name)
                mode = item.external_attr >> 16
                require(stat.S_IFMT(mode) in (0, stat.S_IFREG, stat.S_IFDIR), "member_type")
                require(not item.flag_bits & 1, "encrypted_zip_member")
                upper = name.upper()
                if upper.startswith("META-INF/") and upper.endswith((".SF", ".RSA", ".DSA", ".EC")):
                    signatures.append(name)
                h, prefix, read_size = hashlib.sha256(), bytearray(), 0
                with z.open(item) as member:
                    while chunk := member.read(65536):
                        read_size += len(chunk)
                        require(read_size <= item.file_size, "member_expansion")
                        h.update(chunk)
                        if len(prefix) < 65536:
                            prefix.extend(chunk[:65536 - len(prefix)])
                require(read_size == item.file_size, "member_short")
                if name.endswith(".so"):
                    expected = "lib/arm64-v8a/" if kind == "apk" else "jni/arm64-v8a/"
                    require(name.startswith(expected), "unexpected_native_abi_or_path")
                    f.seek(item.header_offset)
                    header = f.read(30)
                    require(len(header) == 30 and header[:4] == b"PK\x03\x04", "zip_local_header")
                    name_len, extra_len = struct.unpack_from("<HH", header, 26)
                    data_offset = item.header_offset + 30 + name_len + extra_len
                    native.append({"path": name, "sha256": h.hexdigest(), "bytes": read_size,
                                   "compression": item.compress_type, "data_offset": data_offset,
                                   "stored_16k_aligned": item.compress_type == zipfile.ZIP_STORED
                                   and data_offset % 16384 == 0,
                                   **elf_segments(prefix, read_size)})
            require(native, "no_native_library")
            return {"artifact": str(Path(path)), "kind": kind, "sha256": archive_hash,
                    "bytes": st.st_size, "entries": len(rows), "native_libraries": native,
                    "v1_signature_entries": signatures,
                    "signing_block_ids": [f"0x{x:08x}" for x in ids],
                    "recognized_apk_signers": [SIGNER_IDS[x] for x in ids if x in SIGNER_IDS],
                    "no_recognized_apk_signatures": kind == "apk" and not signatures
                    and not any(x in SIGNER_IDS for x in ids),
                    "limit": "Structural evidence only; requires apksigner/zipalign and does not prove runtime."}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("kind", choices=("aar", "apk"))
    parser.add_argument("artifact", type=Path)
    args = parser.parse_args()
    print(json.dumps(inspect(args.artifact, args.kind), indent=2, sort_keys=True))

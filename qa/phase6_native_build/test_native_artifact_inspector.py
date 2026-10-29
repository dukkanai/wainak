import io
from pathlib import Path
import struct
import tempfile
import unittest
import zipfile

from inspect_native_artifact import inspect, elf_segments, signing_block


def elf(align=16384):
    ident = b"\x7fELF\x02\x01\x01" + b"\0" * 9
    header = struct.pack("<HHIQQQIHHHHHH", 3, 183, 1, 0, 64, 0, 0, 64, 56, 1, 0, 0, 0)
    load = struct.pack("<IIQQQQQQ", 1, 5, 0, 0, 0, 120, 120, align)
    return ident + header + load


def apk(extra=None, align=16384):
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        z.writestr("lib/arm64-v8a/libfixture.so", elf(align))
        if extra:
            z.writestr(extra, b"public fixture")
    return b.getvalue()


class ArtifactInspectorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="wainek-artifact-inspector-")
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "fixture.apk"

    def run_artifact(self, data):
        self.path.write_bytes(data)
        return inspect(self.path, "apk")

    def test_unsigned_structure_positive_control(self):
        result = self.run_artifact(apk())
        self.assertTrue(result["no_recognized_apk_signatures"])
        self.assertTrue(result["native_libraries"][0]["all_load_alignments_at_least_16k"])
        self.assertFalse(result["native_libraries"][0]["stored_16k_aligned"])

    def test_v1_signature_is_not_unsigned(self):
        result = self.run_artifact(apk("META-INF/CERT.RSA"))
        self.assertFalse(result["no_recognized_apk_signatures"])

    def test_v2_signing_block_is_detected(self):
        data = apk()
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            central = z.start_dir
        entry = struct.pack("<QI", 4, 0x7109871A)
        size = len(entry) + 24
        block = struct.pack("<Q", size) + entry + struct.pack("<Q", size) + b"APK Sig Block 42"
        result = bytearray(data[:central] + block + data[central:])
        end = result.rfind(b"PK\x05\x06")
        struct.pack_into("<I", result, end + 16, central + len(block))
        info = self.run_artifact(result)
        self.assertEqual(info["recognized_apk_signers"], ["v2"])
        self.assertFalse(info["no_recognized_apk_signatures"])

    def test_malformed_signing_block_rejected(self):
        with self.assertRaises(ValueError):
            signing_block(io.BytesIO(struct.pack("<Q", 2**40) + b"APK Sig Block 42"), 24)

    def test_bad_load_alignment_is_reported(self):
        result = self.run_artifact(apk(align=4096))
        self.assertFalse(result["native_libraries"][0]["all_load_alignments_at_least_16k"])

    def test_bad_elf_bounds_rejected(self):
        broken = bytearray(elf())
        struct.pack_into("<Q", broken, 64 + 32, 121)
        with self.assertRaises(ValueError):
            elf_segments(broken, len(broken))

    def test_traversal_rejected_without_extraction(self):
        with self.assertRaises(ValueError):
            self.run_artifact(apk("../fixture"))
        self.assertFalse((self.path.parent.parent / "fixture").exists())

    def test_symlink_artifact_rejected(self):
        real = self.path.parent / "real.apk"
        real.write_bytes(apk())
        self.path.symlink_to(real)
        with self.assertRaises(OSError):
            inspect(self.path, "apk")

    def test_wrong_abi_rejected(self):
        b = io.BytesIO()
        with zipfile.ZipFile(b, "w") as z:
            z.writestr("lib/x86_64/libfixture.so", elf())
        with self.assertRaises(ValueError):
            self.run_artifact(b.getvalue())


if __name__ == "__main__":
    unittest.main()

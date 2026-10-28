"""Pure static negative controls; no subprocess, network or compiler."""
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

SPEC = importlib.util.spec_from_file_location("preparation", Path(__file__).resolve().parents[1] / "check_preparation.py")
check = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(check)


class PreparationChecks(unittest.TestCase):
    def setUp(self):
        self.config = check.read_json(check.ROOT / "codemagic.yaml")

    def reject(self, mutate):
        candidate = copy.deepcopy(self.config)
        mutate(candidate["workflows"]["ios-unsigned-archive"])
        with self.assertRaises(check.InvalidPreparation):
            check.validate_workflow(candidate)

    def test_current_manual_compile_config(self):
        check.validate_workflow(self.config)

    def test_push_trigger_rejected(self):
        self.reject(lambda w: w.update(triggering={"events": ["push"]}))

    def test_public_artifacts_rejected(self):
        self.reject(lambda w: w.update(artifacts=["**/*.ipa"]))

    def test_publishing_rejected(self):
        self.reject(lambda w: w.update(publishing={"app_store_connect": {}}))

    def test_secret_group_rejected(self):
        self.reject(lambda w: w["environment"].update(groups=["signing"]))

    def test_paid_linux_rejected(self):
        self.reject(lambda w: w.update(instance_type="linux_x2"))

    def test_unreviewed_command_rejected(self):
        self.reject(lambda w: w["scripts"][0].update(script="flutter build ios --no-codesign"))

    def test_appended_command_rejected(self):
        self.reject(lambda w: w["scripts"][0].update(script=check.COMMANDS[0] + "; echo unexpected"))

    def test_duration_bool_rejected(self):
        self.reject(lambda w: w.update(max_build_duration=True))

    def test_duplicate_json_key_rejected(self):
        with self.assertRaises(check.InvalidPreparation):
            json.loads('{"workflows":{},"workflows":{}}', object_pairs_hook=check.no_duplicates)

    def test_parent_escape_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(check.InvalidPreparation):
                check.checked_file(Path(temp), "../outside")

    def test_symlink_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "original").write_text("public synthetic fixture")
            (root / "linked").symlink_to(root / "original")
            with self.assertRaises(check.InvalidPreparation):
                check.checked_file(root, "linked")

    @unittest.skipUnless((check.ROOT / "ci/source-provenance.json").exists(), "not an integrated checkout")
    def test_native_source_manifest(self):
        self.assertEqual(check.validate_sources(check.ROOT, check.read_json(check.ROOT / "ci/source-provenance.json"), check.read_json(check.ROOT / "ci/native-source-deltas.json")), 22)

    @unittest.skipUnless((check.ROOT / "ci/android-source-deltas.json").exists(), "not an integrated checkout")
    def test_android_source_manifest(self):
        self.assertGreater(check.validate_android(check.ROOT, check.read_json(check.ROOT / "ci/android-baseline.json"), check.read_json(check.ROOT / "ci/android-source-deltas.json")), 10)


if __name__ == "__main__":
    unittest.main()

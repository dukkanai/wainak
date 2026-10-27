import importlib.util
import os
import signal
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

INTEGRATION = Path(__file__).resolve().parents[1] / "integration"
sys.path.insert(0, str(INTEGRATION))
try:
    specification = importlib.util.spec_from_file_location("flutter_postgres_controls", INTEGRATION / "run_flutter_postgres.py")
    controls = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(controls)
finally:
    sys.path.pop(0)


class IntegrationControlTests(unittest.TestCase):
    def test_fixed_marker_round_trip(self):
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / "active.resumed"
            controls.create_marker(marker, "resumed")
            controls.validate_marker(marker, "resumed")
            self.assertEqual(marker.stat().st_mode & 0o777, 0o600)

    def test_existing_marker_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / "active.resumed"
            controls.create_marker(marker, "resumed")
            with self.assertRaises(FileExistsError):
                controls.create_marker(marker, "changed")
            self.assertEqual(marker.read_text(), "resumed")

    def test_marker_symlink_is_not_followed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "target").write_text("ready")
            (root / "active.ready").symlink_to(root / "target")
            with self.assertRaises(RuntimeError):
                controls.validate_marker(root / "active.ready", "ready")

    @unittest.skipUnless(hasattr(os, "mkfifo"), "POSIX-only harness")
    def test_fifo_is_rejected_without_blocking(self):
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / "active.ready"
            os.mkfifo(marker)
            with self.assertRaises(RuntimeError):
                controls.validate_marker(marker, "ready")

    def test_marker_wrong_content_or_oversize_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / "active.ready"
            for content in ("wrong", "ready\n", "x" * 33):
                marker.write_text(content)
                with self.assertRaises(RuntimeError):
                    controls.validate_marker(marker, "ready")

    def test_failure_log_filters_bearer_and_long_opaque_values(self):
        synthetic = "a" * 43
        output = controls.safe_failure_output("Authorization: Bearer " + synthetic + " opaque=" + synthetic)
        self.assertNotIn(synthetic, output)
        self.assertIn("REDACTED", output)

    def test_owned_test_path_cannot_escape_or_follow_a_symlink(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "test").mkdir()
            (root / "test/good_test.dart").write_text("// synthetic test")
            self.assertEqual(controls.owned_test(root, Path("test/good_test.dart")), root / "test/good_test.dart")
            (root / "test/link_test.dart").symlink_to(root / "test/good_test.dart")
            for value in ("../other_test.dart", "/tmp/other_test.dart", "lib/app.dart", "test/link_test.dart"):
                with self.assertRaises(RuntimeError):
                    controls.owned_test(root, Path(value))

    def test_symlinked_test_root_cannot_escape_the_mobile_copy(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "mobile").mkdir()
            (root / "outside").mkdir()
            (root / "outside/good_test.dart").write_text("// synthetic test")
            (root / "mobile/test").symlink_to(root / "outside", target_is_directory=True)
            with self.assertRaises(RuntimeError):
                controls.owned_test(root / "mobile", Path("test/good_test.dart"))

    def test_heap_forwarding_accepts_only_the_explicit_heap_flags(self):
        flags = "--old_gen_heap_size=384 --new_gen_semi_max_size=16"
        self.assertEqual(controls.heap_flags(flags), flags)
        for value in ("--packages=/private", "--old_gen_heap_size=384 ; command", "--old_gen_heap_size=384 --old_gen_heap_size=768"):
            with self.assertRaises(RuntimeError):
                controls.heap_flags(value)

    def test_client_cleanup_failure_still_stops_the_server(self):
        server = object()
        with mock.patch.object(controls, "stop_flutter", side_effect=RuntimeError("synthetic failure")), \
                mock.patch.object(controls, "stop_server") as stop:
            with self.assertRaises(RuntimeError):
                controls.cleanup_children(None, server, lambda: None)
            stop.assert_called_once_with(server)

    def test_exact_child_exit_race_does_not_fail_cleanup(self):
        process = mock.Mock()
        process.poll.return_value = None
        with mock.patch.object(controls.os, "killpg", side_effect=ProcessLookupError):
            controls.stop_flutter(process)
        process.wait.assert_called_once_with(timeout=10)

    def test_exited_flutter_leader_does_not_hide_live_descendants(self):
        process=mock.Mock()
        process.poll.return_value=0
        with mock.patch.object(controls.os,"killpg",side_effect=[None,None,ProcessLookupError]) as kill:
            controls.stop_flutter(process)
        self.assertEqual([call.args[1] for call in kill.call_args_list],
                         [signal.SIGTERM,signal.SIGKILL,0])

    def test_default_termination_unwinds_and_restores_handler(self):
        original=signal.getsignal(signal.SIGTERM)
        signal.signal(signal.SIGTERM,signal.SIG_DFL)
        cleaned=[]
        try:
            with self.assertRaises(KeyboardInterrupt):
                with controls.run_postgres.termination_for_cleanup():
                    try:
                        os.kill(os.getpid(),signal.SIGTERM)
                    finally:
                        with controls.run_postgres.cleanup_signals():
                            os.kill(os.getpid(),signal.SIGTERM)
                            cleaned.append(True)
            self.assertEqual(cleaned,[True])
            self.assertEqual(signal.getsignal(signal.SIGTERM),signal.SIG_DFL)
        finally:
            signal.signal(signal.SIGTERM,original)

    def test_private_fixture_custom_termination_handler_is_preserved(self):
        seen=[]
        callback=lambda *_: seen.append(True)
        original=signal.signal(signal.SIGTERM,callback)
        try:
            with controls.run_postgres.termination_for_cleanup():
                os.kill(os.getpid(),signal.SIGTERM)
                self.assertIs(signal.getsignal(signal.SIGTERM),callback)
            self.assertEqual(seen,[True])
            self.assertIs(signal.getsignal(signal.SIGTERM),callback)
        finally:
            signal.signal(signal.SIGTERM,original)


if __name__ == "__main__":
    unittest.main()

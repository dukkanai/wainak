"""Real subprocess controls for bounded CI output and owned-group cleanup."""
import os
from pathlib import Path
import signal
import sys
import tempfile
import unittest

from ci_process import run_bounded


class CommandControls(unittest.TestCase):
    def test_success_returns_bounded_output_and_reaps_child(self):
        result = run_bounded([sys.executable, '-c', 'print("synthetic")'], cwd=Path.cwd(), seconds=5)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), 'synthetic')

    def test_nonzero_fails_without_publishing_child_output(self):
        with self.assertRaisesRegex(RuntimeError, '^Host CI command failed with exit code 2$'):
            run_bounded([sys.executable, '-c', 'print("synthetic-private"); raise SystemExit(2)'],
                        cwd=Path.cwd(), seconds=5, check=True)

    def test_output_flood_is_rejected(self):
        with self.assertRaisesRegex(RuntimeError, 'output limit'):
            run_bounded([sys.executable, '-c', 'print("x" * 8192)'], cwd=Path.cwd(),
                        seconds=5, maximum=1024)

    def test_timeout_reaps_own_child_and_restores_signal_handler(self):
        handler = signal.getsignal(signal.SIGTERM)
        with tempfile.TemporaryDirectory(prefix='wainek-command-test-') as directory:
            path = Path(directory) / 'pid'
            source = 'import os,sys,time; open(sys.argv[1],"w").write(str(os.getpid())); os.close(1); os.close(2); time.sleep(60)'
            with self.assertRaises(TimeoutError):
                run_bounded([sys.executable, '-c', source, path], cwd=directory, seconds=.3)
            pid = int(path.read_text())
            with self.assertRaises(ProcessLookupError):
                os.kill(pid, 0)
        self.assertEqual(signal.getsignal(signal.SIGTERM), handler)

    def test_fixture_grace_allows_finally_cleanup_after_timeout(self):
        with tempfile.TemporaryDirectory(prefix='wainek-grace-test-') as directory:
            marker = Path(directory) / 'cleaned'
            source = '''import signal,sys,time
def cancel(*_):
    raise KeyboardInterrupt()
signal.signal(signal.SIGTERM,cancel)
try:
    time.sleep(60)
finally:
    time.sleep(.2)
    open(sys.argv[1],"w").write("cleaned")
'''
            with self.assertRaises(TimeoutError):
                run_bounded([sys.executable, '-c', source, marker], cwd=directory,
                            seconds=.3, cleanup_grace=2)
            self.assertEqual(marker.read_text(), 'cleaned')


if __name__ == '__main__':
    unittest.main()

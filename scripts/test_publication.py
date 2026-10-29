"""Publication checks must inspect the Git index, including forced ignored files."""
from contextlib import redirect_stderr, redirect_stdout
import importlib.util
import io
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location(
    'publication', Path(__file__).with_name('check_publication.py'))
publication = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(publication)


class PublicationTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='wainek-publication-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        subprocess.run(['git', 'init', '-q', str(self.root)], check=True)

    def stage(self, name, content):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        subprocess.run(['git', 'add', '-f', '--', name], cwd=self.root, check=True)
        return path

    def check(self):
        output = io.StringIO()
        with patch.object(publication, 'ROOT', self.root), redirect_stdout(output), redirect_stderr(output):
            result = publication.main()
        return result, output.getvalue()

    def test_staged_secret_cannot_be_hidden_by_clean_working_copy(self):
        token = ('gh' + 'p_' + 'a' * 36).encode()
        path = self.stage('sample.txt', token)
        path.write_text('clean working copy')
        result, output = self.check()
        self.assertTrue(result)
        self.assertIn('GitHub token pattern', output)
        self.assertNotIn(token.decode(), output)

    def test_unstaged_and_ignored_runtime_are_not_read(self):
        self.stage('source.py', b'pass\n')
        runtime = self.root / '.runtime'
        runtime.mkdir()
        (runtime / 'token').write_bytes(('gh' + 'p_' + 'b' * 36).encode())
        self.assertFalse(self.check()[0])

    def test_forced_artifacts_and_bundle_contents_are_rejected(self):
        for name in ['app.APK', 'app.aab', 'bridge.aar', 'app.ipa',
                     'App.xcarchive/Info.plist', 'Bridge.xcframework/Info.plist']:
            self.stage(name, b'fixture')
        result, output = self.check()
        self.assertTrue(result)
        self.assertEqual(output.count('excluded file is tracked'), 6)

    def test_generated_directories_are_rejected(self):
        for name in ['.ci-work/tmp', 'apps/mobile/build/file', '.gradle/cache',
                     '.venv/bin/python', '.runtime/value', 'backups/data.sql']:
            self.stage(name, b'fixture')
        result, output = self.check()
        self.assertTrue(result)
        self.assertEqual(output.count('excluded file is tracked'), 6)

    def test_forced_apple_material_rejected_without_inspecting_contents(self):
        names=['AuthKey.P8','app.mobileprovision','app.provisionprofile',
               'distribution.keychain-db','distribution.keychain','identity.P12']
        for name in names:self.stage(name,b'CANARY_SYNTHETIC_APPLE_MATERIAL')
        result,output=self.check()
        self.assertTrue(result)
        self.assertEqual(output.count('excluded file is tracked'),len(names))
        self.assertNotIn('CANARY',output)

    def test_source_migrations_fonts_and_icons_are_allowed(self):
        for name in ['backend/migrations/001.sql', 'assets/font.ttf',
                     'assets/icon.png', '.env.example', 'ci/native/build.py']:
            self.stage(name, b'fixture')
        self.assertFalse(self.check()[0])

    def test_tracked_symlink_is_rejected_without_reading_target(self):
        (self.root / 'link').symlink_to('/not/a/real/target')
        subprocess.run(['git', 'add', 'link'], cwd=self.root, check=True)
        result, output = self.check()
        self.assertTrue(result)
        self.assertIn('not a regular resolved source file', output)


if __name__ == '__main__':
    unittest.main()

"""Renaming may update current bytes, never silently replace the historical pin."""
import hashlib
import json
import plistlib
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET

from ci import rename_provenance as r


class ProductIdentityTests(unittest.TestCase):
    def test_display_bundle_and_native_channel_agree(self):
        root = Path(__file__).resolve().parents[2]
        mobile = root/'apps/mobile'
        info = plistlib.loads((mobile/'ios/Runner/Info.plist').read_bytes())
        self.assertEqual(info['CFBundleDisplayName'], 'wainek')
        self.assertEqual(info['CFBundleName'], 'wainek')
        manifest = ET.fromstring((mobile/'android/app/src/main/AndroidManifest.xml').read_text())
        self.assertEqual(manifest.find('application').get('{http://schemas.android.com/apk/res/android}label'), 'wainek')
        gradle = (mobile/'android/app/build.gradle.kts').read_text()
        self.assertIn('namespace = "com.nextaura.wainek"', gradle)
        self.assertIn('applicationId = "com.nextaura.wainek"', gradle)
        for name in ['lib/src/native_archive/channel.dart', 'ios/Runner/NativeArchivePlugin.swift',
                     'android/app/src/main/kotlin/com/nextaura/wainek/NativeArchiveChannel.kt']:
            self.assertIn('wainek/native_archive_v1', (mobile/name).read_text())
        self.assertIn('name: wainek_mobile', (mobile/'pubspec.yaml').read_text())
        web = json.loads((mobile/'web/manifest.json').read_text())
        self.assertEqual(web['name'], 'wainek')
        self.assertEqual(web['short_name'], 'wainek')
        self.assertIn('<title>wainek</title>', (mobile/'web/index.html').read_text())
        for name in ('app.dart', 'connected_app.dart', 'identity/app.dart'):
            self.assertIn("title: 'wainek',", (mobile/'lib/src'/name).read_text())

    def test_persisted_database_identity_is_preserved(self):
        root = Path(__file__).resolve().parents[2]
        source = (root/'backend/wainek_identity/apps.py').read_text()
        self.assertIn('name = "wainek_identity"', source)
        self.assertIn('label = "wainak_identity"', source)
        self.assertIn('AUTH_USER_MODEL="wainak_identity.User"',
                      (root/'backend/wainek_identity/bootstrap.py').read_text())
        self.assertIn('SCHEMA = "wainak_phase1_dev"', (root/'backend/wainek/migrations.py').read_text())
        compose = (root/'compose.yaml').read_text()
        self.assertTrue(compose.startswith('name: wainak\n'))
        self.assertIn('POSTGRES_USER: wainak_admin', compose)
        self.assertIn('POSTGRES_DB: wainak', compose)


class RenameProvenanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'ci').mkdir()
        (self.root / 'archive').mkdir()
        self.source = self.root / 'archive/go.mod'
        self.source.write_text('new module fixture')
        self.before = hashlib.sha256(b'old module fixture').hexdigest()
        self.row = {'path': 'archive/go.mod', 'before_sha256': self.before,
                    'after_sha256': hashlib.sha256(self.source.read_bytes()).hexdigest(),
                    'reason': 'Explicit identity rename'}
        self.data = {'schema': 1, 'base_commit': '9bb2aa7731911c1b9d16c76ec4f276ec599f7755',
                     'scope': 'identity', 'files': {'archive/go.mod': self.row}}
        self.save()

    def save(self):
        (self.root / 'ci/wainek-rename-provenance.json').write_text(json.dumps(self.data))

    def test_accepts_new_bytes_only_against_original_pin(self):
        self.assertTrue(r.source_matches(self.root, 'archive/go.mod', self.before))
        with self.assertRaises(r.RenameError):
            r.source_matches(self.root, 'archive/go.mod', '0' * 64)

    def test_source_tampering_does_not_pass(self):
        self.source.write_text('unreviewed replacement')
        self.assertFalse(r.source_matches(self.root, 'archive/go.mod', self.before))

    def test_redirects_and_scope_expansion_are_rejected(self):
        for target in ('../outside', '/tmp/outside', 'archive/other.mod'):
            self.row['path'] = target
            self.save()
            with self.subTest(target=target), self.assertRaises(r.RenameError):
                r.source_matches(self.root, 'archive/go.mod', self.before)

    def test_symlink_and_missing_source_are_rejected(self):
        self.source.unlink()
        with self.assertRaises(r.RenameError):
            r.source_matches(self.root, 'archive/go.mod', self.before)
        self.source.symlink_to(self.root / 'ci/wainek-rename-provenance.json')
        with self.assertRaises(r.RenameError):
            r.source_matches(self.root, 'archive/go.mod', self.before)

    def test_wrong_anchor_and_before_digest_rejected(self):
        self.row['before_sha256'] = 'a' * 64
        self.save()
        with self.assertRaises(r.RenameError):
            r.source_matches(self.root, 'archive/go.mod', self.before)
        self.data['base_commit'] = '0' * 40
        self.save()
        with self.assertRaises(r.RenameError):
            r.load(self.root)

    def test_absent_overlay_uses_original_bytes(self):
        (self.root / 'ci/wainek-rename-provenance.json').unlink()
        self.assertFalse(r.source_matches(self.root, 'archive/go.mod', self.before))
        self.source.write_text('old module fixture')
        self.assertTrue(r.source_matches(self.root, 'archive/go.mod', self.before))

"""Isolated public-fixture packaging tests; no browser, network or real secrets."""
import base64
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile
import package_preview as p

MARKER = 'PUBLIC_EXTERNAL_FIXTURE_MUST_NOT_BE_INCLUDED'

class PackagingTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name).resolve()
        self.prototype=self.root/'prototype';self.dist=self.prototype/'dist'
        (self.dist/'assets').mkdir(parents=True)
        self.releases=self.prototype/'releases'
        self.external=self.root/'external';self.external.mkdir()
        (self.external/'font-OFL.txt').write_text(MARKER)
        self.source_license=self.dist/'assets/font-OFL.txt'
        self.source_license.write_text('PUBLIC FONT LICENSE')
        (self.dist/'assets/font.woff2').write_bytes(b'PUBLICFONT')
        (self.dist/'index.html').write_text('<!doctype html><html><head><link rel="stylesheet" href="styles.css"></head><body><a href="assets/font-OFL.txt">License</a><script src="app.js"></script></body></html>')
        (self.dist/'styles.css').write_text('@font-face {font-family: public; src:url("assets/font.woff2");}')
        (self.dist/'app.js').write_text('window.syntheticOnly = true;')
        (self.prototype/'README.md').write_text('Use releases/wainak-preview.html')
        self.enterContext(patch.object(p,'ROOT',self.prototype))
        self.enterContext(patch.object(p,'DIST',self.dist))
        self.enterContext(patch.object(p,'RELEASES',self.releases))
    def package(self):
        with contextlib.redirect_stdout(io.StringIO()):p.main()
    def rejected(self):
        with self.assertRaises((ValueError,OSError)):self.package()
        if (self.releases/'wainak-preview.html').exists():
            self.assertNotIn(MARKER,(self.releases/'wainak-preview.html').read_text())
    def test_normal_offline_html_zip_notices_and_manifest(self):
        self.package()
        html=(self.releases/'wainak-preview.html').read_text()
        self.assertIn('PUBLIC FONT LICENSE',html)
        self.assertIn(base64.b64encode(b'PUBLIC FONT LICENSE').decode(),html)
        self.assertIn('window.syntheticOnly = true;',html)
        self.assertIn(base64.b64encode(b'PUBLICFONT').decode(),html)
        self.assertNotIn('src="app.js"',html)
        with zipfile.ZipFile(self.releases/'wainak-prototype.zip') as z:
            for relative in p.source_files(self.dist):
                self.assertEqual(z.read('wainak-prototype/'+relative),p.local_asset(relative))
            self.assertEqual(z.read('wainak-preview.html').decode(),html)
            self.assertIn(b'Use wainak-preview.html',z.read('README.md'))
        manifest=json.loads((self.releases/'manifest.json').read_text())
        for name,row in manifest.items():
            data=(self.releases/name).read_bytes()
            self.assertEqual(row,{'sha256':hashlib.sha256(data).hexdigest(),'bytes':len(data)})
    def test_external_license_link_is_rejected(self):
        self.source_license.unlink();self.source_license.symlink_to(self.external/'font-OFL.txt')
        self.rejected()
    def test_internal_license_link_is_also_rejected(self):
        self.source_license.rename(self.dist/'assets/original.txt')
        self.source_license.symlink_to('original.txt')
        self.rejected()
    def test_ancestor_directory_link_is_rejected(self):
        (self.dist/'assets').rename(self.dist/'saved-assets')
        (self.dist/'assets').symlink_to(self.external,target_is_directory=True)
        self.rejected()
    def test_dist_root_link_is_rejected(self):
        self.dist.rename(self.prototype/'saved-dist')
        self.dist.symlink_to(self.prototype/'saved-dist',target_is_directory=True)
        self.rejected()
    def test_unused_source_link_is_not_silently_omitted(self):
        (self.dist/'unused.txt').symlink_to(self.external/'font-OFL.txt')
        self.rejected()
    def test_readme_external_link_is_rejected(self):
        readme=self.prototype/'README.md';readme.unlink();readme.symlink_to(self.external/'font-OFL.txt')
        self.rejected()
    def test_real_link_swap_after_inventory_cannot_reopen_external_file(self):
        original=p.source_files
        def changed(root):
            names=original(root)
            self.source_license.unlink();self.source_license.symlink_to(self.external/'font-OFL.txt')
            return names
        with patch.object(p,'source_files',side_effect=changed):self.rejected()
    def test_real_ancestor_swap_before_open_is_rejected(self):
        original=p.os.open;swapped=False
        def changed(path,flags,*args,**kwargs):
            nonlocal swapped
            if path=='assets' and kwargs.get('dir_fd') is not None and not swapped:
                swapped=True
                (self.dist/'assets').rename(self.dist/'saved-assets')
                (self.dist/'assets').symlink_to(self.external,target_is_directory=True)
            return original(path,flags,*args,**kwargs)
        with patch.object(p.os,'open',side_effect=changed):
            with self.assertRaises(OSError):p.local_asset('assets/font-OFL.txt')
        self.assertTrue(swapped)
    def test_opened_descriptor_does_not_follow_later_link_swap(self):
        original=p.os.read;swapped=False
        def changed(fd,count):
            nonlocal swapped
            if not swapped:
                swapped=True
                self.source_license.unlink();self.source_license.symlink_to(self.external/'font-OFL.txt')
            return original(fd,count)
        with patch.object(p.os,'read',side_effect=changed):
            self.assertEqual(p.local_asset('assets/font-OFL.txt'),b'PUBLIC FONT LICENSE')
    def test_zip_inputs_use_same_nofollow_reader(self):
        extra=self.dist/'extra.txt';extra.write_text('PUBLIC ORIGINAL')
        original=p.zipfile.ZipFile
        def changed(*args,**kwargs):
            extra.unlink();extra.symlink_to(self.external/'font-OFL.txt')
            return original(*args,**kwargs)
        with patch.object(p.zipfile,'ZipFile',side_effect=changed):self.rejected()
    def test_fifo_is_rejected_without_blocking(self):
        fifo=self.dist/'fifo';os.mkfifo(fifo)
        with self.assertRaises(ValueError):p.local_asset('fifo')
        self.rejected()
    def test_asset_byte_bound_is_enforced(self):
        with patch.object(p,'MAX_ASSET_BYTES',8):
            with self.assertRaises(ValueError):p.local_asset('assets/font-OFL.txt')
    def test_permission_error_is_not_ignored(self):
        self.assertNotEqual(os.geteuid(),0,'run packaging tests as unprivileged user')
        (self.dist/'assets').chmod(0)
        try:self.rejected()
        finally:(self.dist/'assets').chmod(0o700)
    def test_unsafe_relative_names_rejected(self):
        for name in ('','.', '../external/font-OFL.txt','/etc/passwd','assets//font-OFL.txt','assets\\font-OFL.txt','assets/\nfile'):
            with self.assertRaises(ValueError):p.local_asset(name)
    def test_external_css_asset_rejected_without_network(self):
        for url in ('https://example.invalid/font','//example.invalid/font'):
            with self.assertRaises(ValueError):p.inline_css('a{src:url('+url+')}')
    def test_missing_readme_remains_optional(self):
        (self.prototype/'README.md').unlink();self.package()
        with zipfile.ZipFile(self.releases/'wainak-prototype.zip') as z:
            self.assertNotIn('README.md',z.namelist())
    def test_release_directory_link_is_rejected(self):
        self.releases.symlink_to(self.external,target_is_directory=True)
        self.rejected()
        self.assertEqual(sorted(path.name for path in self.external.iterdir()),['font-OFL.txt'])

    def output_names(self):
        return ('wainak-preview.html','wainak-prototype.zip','manifest.json')
    def assert_no_staging_files(self):
        self.assertEqual(list(self.releases.glob('.wainak-package-*')),[])
    def test_safe_existing_outputs_can_be_refreshed_without_truncation(self):
        self.package()
        unrelated=self.releases/'keep.txt';unrelated.write_text('KEEP')
        old=(self.releases/'wainak-preview.html').read_bytes()
        old_fd=os.open(self.releases/'wainak-preview.html',os.O_RDONLY)
        try:
            (self.dist/'app.js').write_text('window.syntheticOnly = "updated";')
            self.package()
            self.assertEqual(os.read(old_fd,len(old)+1),old)
        finally:os.close(old_fd)
        self.assertIn('"updated"',(self.releases/'wainak-preview.html').read_text())
        self.assertEqual(unrelated.read_text(),'KEEP')
        manifest=json.loads((self.releases/'manifest.json').read_text())
        for name,row in manifest.items():
            data=(self.releases/name).read_bytes()
            self.assertEqual(row,{'sha256':hashlib.sha256(data).hexdigest(),'bytes':len(data)})
        self.assert_no_staging_files()
    def test_each_output_leaf_symlink_is_rejected_without_external_overwrite(self):
        self.releases.mkdir(mode=0o700)
        for name in self.output_names():
            with self.subTest(name=name):
                leaf=self.releases/name;leaf.symlink_to(self.external/'font-OFL.txt')
                try:
                    with self.assertRaises(OSError):self.package()
                    self.assertTrue(leaf.is_symlink())
                    self.assertEqual((self.external/'font-OFL.txt').read_text(),MARKER)
                    self.assertEqual(sorted(x.name for x in self.releases.iterdir()),[name])
                finally:leaf.unlink()
    def test_each_output_fifo_is_rejected_without_open_wait(self):
        self.releases.mkdir(mode=0o700)
        for name in self.output_names():
            with self.subTest(name=name):
                leaf=self.releases/name;os.mkfifo(leaf)
                try:
                    with self.assertRaises(ValueError):self.package()
                    self.assertEqual(sorted(x.name for x in self.releases.iterdir()),[name])
                finally:leaf.unlink()
    def test_each_output_hardlink_is_rejected_without_modifying_shared_inode(self):
        self.releases.mkdir(mode=0o700)
        for name in self.output_names():
            with self.subTest(name=name):
                leaf=self.releases/name;os.link(self.external/'font-OFL.txt',leaf)
                try:
                    with self.assertRaises(ValueError):self.package()
                    self.assertEqual((self.external/'font-OFL.txt').read_text(),MARKER)
                    self.assertEqual(leaf.stat().st_nlink,2)
                    self.assertEqual(sorted(x.name for x in self.releases.iterdir()),[name])
                finally:leaf.unlink()
    def test_writable_by_others_output_directory_is_rejected(self):
        self.releases.mkdir(mode=0o700);self.releases.chmod(0o777)
        with self.assertRaises(ValueError):self.package()
        self.assertEqual(list(self.releases.iterdir()),[])
    def test_existing_leaf_changed_during_staging_is_rejected(self):
        self.package()
        leaf=self.releases/'wainak-preview.html'
        original=p.os.fsync;changed=False
        def mutate(fd):
            nonlocal changed
            if not changed:
                changed=True;leaf.write_text('CONCURRENT PUBLIC UPDATE')
            return original(fd)
        with patch.object(p.os,'fsync',side_effect=mutate):
            with self.assertRaises(ValueError):self.package()
        self.assertEqual(leaf.read_text(),'CONCURRENT PUBLIC UPDATE')
        self.assert_no_staging_files()
    def test_staging_failure_preserves_all_previous_outputs(self):
        self.package()
        before={name:(self.releases/name).read_bytes() for name in self.output_names()}
        with patch.object(p.os,'fsync',side_effect=OSError('injected fixture failure')):
            with self.assertRaises(OSError):self.package()
        self.assertEqual(before,{name:(self.releases/name).read_bytes() for name in self.output_names()})
        self.assert_no_staging_files()
    def test_output_directory_swapped_before_replace_cannot_write_external_directory(self):
        self.releases.mkdir(mode=0o700);original=p.os.replace;swapped=False
        moved=self.prototype/'moved-releases'
        def replace(*args,**kwargs):
            nonlocal swapped
            if not swapped:
                swapped=True;self.releases.rename(moved)
                self.releases.symlink_to(self.external,target_is_directory=True)
            return original(*args,**kwargs)
        with patch.object(p.os,'replace',side_effect=replace):
            with self.assertRaises((ValueError,OSError)):self.package()
        self.assertTrue(swapped)
        self.assertEqual(sorted(x.name for x in self.external.iterdir()),['font-OFL.txt'])
        self.assertEqual((self.external/'font-OFL.txt').read_text(),MARKER)
        self.assertEqual(list(moved.glob('.wainak-package-*')),[])
    def test_leaf_link_swap_at_replace_does_not_follow_external_target(self):
        original=p.os.replace;swapped=False
        def replace(source,destination,*args,**kwargs):
            nonlocal swapped
            if destination=='wainak-preview.html' and not swapped:
                swapped=True;(self.releases/destination).symlink_to(self.external/'font-OFL.txt')
            return original(source,destination,*args,**kwargs)
        with patch.object(p.os,'replace',side_effect=replace):self.package()
        self.assertTrue(swapped)
        self.assertEqual((self.external/'font-OFL.txt').read_text(),MARKER)
        self.assertFalse((self.releases/'wainak-preview.html').is_symlink())
        self.assert_no_staging_files()
    def test_replaced_staging_name_is_not_published_or_removed_as_owned(self):
        original=p.os.fsync;changed=False;replaced=None
        def mutate(fd):
            nonlocal changed,replaced
            if not changed:
                changed=True
                replaced=next(self.releases.glob('.wainak-package-*'))
                replaced.unlink();replaced.symlink_to(self.external/'font-OFL.txt')
            return original(fd)
        with patch.object(p.os,'fsync',side_effect=mutate):
            with self.assertRaises(ValueError):self.package()
        self.assertTrue(replaced.is_symlink())
        self.assertEqual((self.external/'font-OFL.txt').read_text(),MARKER)
        self.assertEqual(list(self.releases.glob('.wainak-package-*')),[replaced])
        self.assertFalse((self.releases/'wainak-preview.html').exists())
    def test_partial_publication_failure_does_not_publish_new_manifest(self):
        self.package()
        old_manifest=(self.releases/'manifest.json').read_bytes()
        (self.dist/'app.js').write_text('window.changed = true;')
        original=p.os.replace
        def fail_second(source,destination,*args,**kwargs):
            if destination=='wainak-prototype.zip':raise OSError('injected second replace failure')
            return original(source,destination,*args,**kwargs)
        with patch.object(p.os,'replace',side_effect=fail_second):
            with self.assertRaises(OSError):self.package()
        self.assertEqual((self.releases/'manifest.json').read_bytes(),old_manifest)
        self.assertIn('window.changed = true;',(self.releases/'wainak-preview.html').read_text())
        self.assert_no_staging_files()

if __name__=='__main__':unittest.main()

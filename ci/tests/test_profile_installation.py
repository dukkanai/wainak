"""Synthetic profile bytes only; real isolated filesystem, no Apple credentials."""
import errno
import hashlib
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest import mock
from types import SimpleNamespace

from ci.github import profile_installation as n, internal_policy as q, internal_testflight as driver
from ci.testflight import policy as p


class Profiles(unittest.TestCase):
    def setUp(self):
        previous=os.umask(0o077);self.addCleanup(os.umask,previous)
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name).resolve();self.home=self.root/'account';self.home.mkdir(mode=0o700)
        self.private=self.root/'private';self.private.mkdir(mode=0o700)
        self.data=b'\x30SYNTHETIC_CANARY_PROFILE'
        self.pins={'profile_uuid':'12345678-1234-1234-1234-123456789abc',
                   'profile_sha256':hashlib.sha256(self.data).hexdigest()}
        self.source=self.private/n.SOURCE;self.source.write_bytes(self.data);self.source.chmod(0o600)
        self.name=self.pins['profile_uuid']+'.mobileprovision'
        self.paths=[self.home/d/self.name for d in n.DIRECTORIES]
        patch=mock.patch.object(n,'native_home',return_value=self.home);patch.start();self.addCleanup(patch.stop)
        printing=mock.patch('builtins.print');self.printed=printing.start();self.addCleanup(printing.stop)

    def install(self):n.install(self.private,self.pins)
    def cleanup(self):n.cleanup(self.private,self.pins)

    def tearDown(self):
        self.assertNotIn('CANARY',str(self.printed.call_args_list))
        self.assertNotIn(str(self.home),str(self.printed.call_args_list))

    def test_happy_path_pinned_inode_permissions_cleanup_preserves_unrelated(self):
        directory=self.paths[0].parent;directory.mkdir(parents=True)
        other=directory/'unrelated.mobileprovision';other.write_bytes(b'OTHER')
        mode=directory.stat().st_mode
        self.install();n.verify(self.private,self.pins)
        for path in self.paths:
            self.assertEqual(path.read_bytes(),self.data);self.assertEqual(path.stat().st_ino,self.source.stat().st_ino)
            self.assertEqual(stat.S_IMODE(path.stat().st_mode),0o600)
        self.assertEqual(self.source.stat().st_nlink,3)
        self.cleanup();self.cleanup()
        self.assertTrue(all(not x.exists() for x in self.paths));self.assertTrue(self.source.exists())
        self.assertEqual(self.source.stat().st_nlink,1);self.assertFalse((self.private/n.JOURNAL).exists())
        self.assertEqual(other.read_bytes(),b'OTHER');self.assertEqual(directory.stat().st_mode,mode)
        self.assertNotIn('CANARY',str(self.printed.call_args_list));self.assertNotIn(str(self.home),str(self.printed.call_args_list))

    def test_existing_same_bytes_file_is_collision_and_never_removed(self):
        path=self.paths[1];path.parent.mkdir(parents=True);path.write_bytes(self.data);path.chmod(0o600)
        inode=path.stat().st_ino
        with self.assertRaisesRegex(p.PolicyError,'signed_native_collision'):self.install()
        self.cleanup();self.assertEqual(path.stat().st_ino,inode);self.assertFalse(self.paths[0].exists())

    def test_case_alias_and_symlink_leaf_are_collisions(self):
        for kind in ('alias','link'):
            with self.subTest(kind=kind):
                path=self.paths[0];path.parent.mkdir(parents=True,exist_ok=True)
                collision=path.with_name(self.name.upper()) if kind=='alias' else path
                if kind=='alias':collision.write_bytes(b'OTHER')
                else:collision.symlink_to(self.source)
                with self.assertRaises(p.PolicyError):self.install()
                self.cleanup();self.assertTrue(os.path.lexists(collision));collision.unlink()

    def test_ancestor_symlink_or_writable_directory_rejected(self):
        outside=self.root/'outside';outside.mkdir()
        (self.home/'Library').symlink_to(outside,target_is_directory=True)
        with self.assertRaises(p.PolicyError):self.install()
        self.assertEqual(list(outside.iterdir()),[])
        (self.home/'Library').unlink();(self.home/'Library').mkdir(mode=0o777);(self.home/'Library').chmod(0o777)
        with self.assertRaisesRegex(p.PolicyError,'signed_native_ownership'):self.install()

    def test_bad_source_hash_mode_symlink_and_extra_hardlink_rejected(self):
        for kind in ('hash','mode','symlink','hardlink'):
            with self.subTest(kind=kind):
                self.source.unlink();self.source.write_bytes(self.data);self.source.chmod(0o600)
                other=self.private/'other'
                if kind=='hash':self.source.write_bytes(b'bad')
                elif kind=='mode':self.source.chmod(0o644)
                elif kind=='symlink':self.source.rename(other);self.source.symlink_to(other)
                else:os.link(self.source,other)
                with self.assertRaises(p.PolicyError):self.install()
                self.assertFalse((self.private/n.JOURNAL).exists())
                if other.exists():other.unlink()

    def test_foreign_directory_owner_rejected(self):
        value=SimpleNamespace(st_mode=stat.S_IFDIR|0o700,st_uid=os.getuid()+1)
        with self.assertRaisesRegex(p.PolicyError,'signed_native_ownership'):n.directory_ok(value)

    def test_native_home_requires_foundation_and_account_agreement(self):
        # Stop only the per-test home substitution for the native resolver.
        resolver=Profiles.native_resolver
        with mock.patch.object(n.signing_discovery,'foundation_home',return_value=self.home), \
             mock.patch.object(n.pwd,'getpwuid',return_value=SimpleNamespace(pw_dir=str(self.home))):
            self.assertEqual(resolver(),self.home)
        for value in (None,Path('/'),Path('relative'),self.home/'..'/'elsewhere'):
            with mock.patch.object(n.signing_discovery,'foundation_home',return_value=value), \
                 mock.patch.object(n.pwd,'getpwuid',return_value=SimpleNamespace(pw_dir=str(self.home))),self.assertRaises(p.PolicyError):resolver()

    def test_no_journal_never_authorizes_removal(self):
        for path in self.paths:path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(self.data)
        self.cleanup();self.assertTrue(all(path.exists() for path in self.paths))

    def test_missing_journal_after_successful_install_cannot_claim_cleanup(self):
        self.install();journal=self.private/n.JOURNAL;saved=journal.read_bytes();journal.unlink()
        with self.assertRaisesRegex(p.PolicyError,'signed_native_cleanup'):
            n.cleanup(self.private,self.pins,required=True)
        with mock.patch.multiple(driver,WORK=self.root,PRIVATE=self.private),self.assertRaises(p.PolicyError):
            driver.cleanup(mock.Mock(),self.pins,native_required=True)
        self.assertTrue(self.source.exists());self.assertTrue(all(path.exists() for path in self.paths))
        journal.write_bytes(saved);journal.chmod(0o600);self.cleanup()
        with mock.patch.multiple(driver,WORK=self.root,PRIVATE=self.root/'missing'),self.assertRaises(p.PolicyError):
            driver.cleanup(mock.Mock(),self.pins,native_required=True)

    def test_partial_link_failure_keeps_recoverable_journal_and_no_fallback(self):
        link=os.link;calls=0
        def failing(*args,**kwargs):
            nonlocal calls
            calls+=1
            if calls==2:raise PermissionError(errno.EPERM,'CANARY')
            return link(*args,**kwargs)
        with mock.patch.object(n.os,'link',side_effect=failing),self.assertRaisesRegex(p.PolicyError,'signed_native_io'):self.install()
        self.assertTrue((self.private/n.JOURNAL).exists());self.assertTrue(self.paths[0].exists())
        self.cleanup();self.assertTrue(all(not x.exists() for x in self.paths))
        with mock.patch.object(n.os,'link',side_effect=OSError(errno.EXDEV,'CANARY')),self.assertRaises(p.PolicyError):self.install()
        self.cleanup();self.assertTrue(all(not x.exists() for x in self.paths))

    def test_interrupt_immediately_after_link_recovers_using_durable_intent(self):
        link=os.link
        def interrupted(*args,**kwargs):link(*args,**kwargs);raise KeyboardInterrupt('CANARY')
        with mock.patch.object(n.os,'link',side_effect=interrupted),self.assertRaises(KeyboardInterrupt):self.install()
        self.assertTrue(self.paths[0].exists());self.assertTrue((self.private/n.JOURNAL).exists())
        self.cleanup();self.assertTrue(all(not x.exists() for x in self.paths))

    def test_interrupt_after_journal_before_any_link_is_recoverable(self):
        write=n.write_journal
        def interrupted(*args,**kwargs):write(*args,**kwargs);raise KeyboardInterrupt('CANARY')
        with mock.patch.object(n,'write_journal',side_effect=interrupted),self.assertRaises(KeyboardInterrupt):self.install()
        self.assertTrue((self.private/n.JOURNAL).exists());self.assertTrue(all(not path.exists() for path in self.paths))
        self.cleanup();self.assertFalse((self.private/n.JOURNAL).exists())

    def test_journal_symlink_or_wrong_types_are_rejected(self):
        self.install();journal=self.private/n.JOURNAL;saved=journal.read_bytes()
        value=json.loads(saved);value['version']=True;journal.write_text(json.dumps(value))
        with self.assertRaises(p.PolicyError):self.cleanup()
        journal.unlink();other=self.private/'other-journal';other.write_bytes(saved);other.chmod(0o600);journal.symlink_to(other)
        with self.assertRaises(p.PolicyError):self.cleanup()
        self.assertTrue(all(path.exists() for path in self.paths))
        journal.unlink();journal.write_bytes(saved);journal.chmod(0o600);self.cleanup()

    def test_interrupt_or_eperm_during_cleanup_preserves_retry_authority(self):
        for error in (PermissionError(errno.EPERM,'CANARY'),KeyboardInterrupt('CANARY')):
            self.install();unlink=os.unlink;failed=False
            def interrupted(name,*args,**kwargs):
                nonlocal failed
                if name==self.name and not failed:failed=True;raise error
                return unlink(name,*args,**kwargs)
            with mock.patch.object(n.os,'unlink',side_effect=interrupted),self.assertRaisesRegex(p.PolicyError,'signed_native_cleanup'):self.cleanup()
            self.assertTrue((self.private/n.JOURNAL).exists());self.assertTrue(self.source.exists())
            self.assertTrue(self.paths[0].exists());self.assertFalse(self.paths[1].exists())
            self.cleanup();self.assertTrue(all(not x.exists() for x in self.paths))

    def test_interruption_after_unlink_is_idempotently_recoverable(self):
        self.install();unlink=os.unlink;failed=False
        def interrupted(name,*args,**kwargs):
            nonlocal failed
            result=unlink(name,*args,**kwargs)
            if name==self.name and not failed:failed=True;raise KeyboardInterrupt('CANARY')
            return result
        with mock.patch.object(n.os,'unlink',side_effect=interrupted),self.assertRaises(p.PolicyError):self.cleanup()
        self.assertTrue((self.private/n.JOURNAL).exists());self.cleanup()
        self.assertFalse((self.private/n.JOURNAL).exists())

    def test_replaced_target_same_bytes_is_preserved_and_cleanup_fails(self):
        self.install();path=self.paths[0];path.unlink();path.write_bytes(self.data);path.chmod(0o600)
        inode=path.stat().st_ino
        with self.assertRaises(p.PolicyError):self.cleanup()
        self.assertEqual(path.stat().st_ino,inode);self.assertFalse(self.paths[1].exists())
        self.assertTrue((self.private/n.JOURNAL).exists())
        path.unlink();self.cleanup()

    def test_replaced_private_source_cannot_claim_existing_links(self):
        self.install();held=self.private/'held-source';self.source.rename(held)
        self.source.write_bytes(self.data);self.source.chmod(0o600)
        with self.assertRaises(p.PolicyError):self.cleanup()
        self.assertTrue(all(path.exists() for path in self.paths))
        self.source.unlink();held.rename(self.source);self.cleanup()

    def test_replaced_directory_or_home_identity_rejected(self):
        self.install();parent=self.paths[0].parent;parent.rename(parent.with_name('held'))
        parent.mkdir()
        with self.assertRaises(p.PolicyError):self.cleanup()
        self.assertTrue(self.paths[1].exists())
        parent.rmdir();parent.with_name('held').rename(parent);self.cleanup()

    def test_mutated_profile_or_journal_cannot_authorize_cleanup(self):
        self.install();self.source.write_bytes(b'MODIFIED')
        with self.assertRaisesRegex(p.PolicyError,'signed_native_pin'):n.verify(self.private,self.pins)
        with self.assertRaises(p.PolicyError):self.cleanup()
        self.assertTrue(all(path.exists() for path in self.paths));self.source.write_bytes(self.data)
        journal=self.private/n.JOURNAL;saved=journal.read_bytes()
        for contents in (b'CANARY_INVALID',b'{"version":1,"version":1}',b'{}'):
            journal.write_bytes(contents)
            with self.assertRaises(p.PolicyError):self.cleanup()
            self.assertTrue(all(path.exists() for path in self.paths))
        journal.write_bytes(saved);self.cleanup()

    def test_driver_cleanup_retains_source_on_external_failure_and_still_cleans_other_material(self):
        self.install();p12=self.private/'distribution.p12';p12.write_bytes(b'SYNTHETIC')
        with mock.patch.multiple(driver,WORK=self.root,PRIVATE=self.private), \
             mock.patch.object(n,'cleanup',side_effect=p.PolicyError('signed_native_cleanup')), \
             self.assertRaisesRegex(p.PolicyError,'signed_cleanup'):
            driver.cleanup(mock.Mock(),self.pins)
        self.assertFalse(p12.exists());self.assertTrue(self.source.exists());self.assertTrue((self.private/n.JOURNAL).exists())
        with mock.patch.multiple(driver,WORK=self.root,PRIVATE=self.private):driver.cleanup(mock.Mock(),self.pins)
        self.assertFalse(self.source.exists());self.assertFalse((self.private/n.JOURNAL).exists())

    def test_all_reasons_are_safe_allowlisted(self):
        self.assertLessEqual(n.REASONS,q.REASONS)

    native_resolver=staticmethod(n.native_home)

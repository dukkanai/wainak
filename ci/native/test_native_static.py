"""Source-preparation tests only. No Go, Apple, native or network execution."""
import copy
import hashlib
import io
import json
from pathlib import Path
import runpy
import shutil
import struct
import sys
import tarfile
import tempfile
import unittest
from unittest import mock
import artifact_static as artifact
import check_static as static
import native_runtime as runtime

HERE=Path(__file__).resolve().parent

class StaticTests(unittest.TestCase):
    def setUp(self): self.lock=static.read_json(HERE/'lock.json')
    def test_frozen_lock_and_retained_proof_notice_bytes(self): static.validate_lock(self.lock,HERE)
    def test_well_formed_changed_checksum_rejected(self):
        self.lock['input_modules'][0]['sum']='h1:'+__import__('base64').b64encode(b'x'*32).decode()
        with self.assertRaises(static.InvalidRecipe): static.validate_lock(self.lock,HERE)
    def test_noncritical_version_rejected(self):
        for row in self.lock['input_modules']:
            if row['path']=='github.com/google/go-cmp':row['version']='v0.7.0'
        with self.assertRaises(static.InvalidRecipe): static.validate_lock(self.lock,HERE)
    def test_extra_target_metadata_rejected(self):
        row=copy.deepcopy(self.lock['auxiliary_modules'][0]);row['version']='v0.0.0-other'
        self.lock['auxiliary_modules'].append(row)
        with self.assertRaises(static.InvalidRecipe): static.validate_lock(self.lock,HERE)
    def test_auxiliary_source_scope_rejected(self):
        self.lock['auxiliary_modules'][0]['metadata_only']=not self.lock['auxiliary_modules'][0]['metadata_only']
        with self.assertRaises(static.InvalidRecipe): static.validate_lock(self.lock,HERE)
    def test_license_exception_cannot_escape(self):
        self.lock['license_path_exceptions'][0]['file']='../secret'
        with self.assertRaises(static.InvalidRecipe): static.validate_lock(self.lock,HERE)
    def test_wrong_go_artifact(self):
        self.lock['go']['sha256']='0'*64
        with self.assertRaises(static.InvalidRecipe): static.validate_lock(self.lock,HERE)
    def test_unknown_target(self):
        self.lock['apple']['targets'].append('iossimulator/amd64')
        with self.assertRaises(static.InvalidRecipe): static.validate_lock(self.lock,HERE)
    def test_unreviewed_runtime_version(self):
        for row in self.lock['input_modules']:
            if row['path']=='golang.org/x/crypto':row['version']='v0.99.0'
        with self.assertRaises(static.InvalidRecipe): static.validate_lock(self.lock,HERE)
    def test_duplicate_module(self):
        self.lock['input_modules'][1]=copy.deepcopy(self.lock['input_modules'][0])
        with self.assertRaises(static.InvalidRecipe): static.validate_lock(self.lock,HERE)
    def test_private_public_acquisition_identity(self):
        row=self.lock['input_modules'][0];row['path']='wainak.local/private'
        with self.assertRaises(static.InvalidRecipe): static.module_id(row)
    def test_shell_version_injection(self):
        row=self.lock['input_modules'][0];row['version']='v1.0.0;echo bad'
        with self.assertRaises(static.InvalidRecipe): static.module_id(row)
    def test_auxiliary_metadata_mutation(self):
        self.lock['auxiliary_modules'][0]['go_mod']+='//changed\n'
        with self.assertRaises(static.InvalidRecipe): static.validate_lock(self.lock,HERE)
    def test_duplicate_json(self):
        with tempfile.TemporaryDirectory() as name:
            p=Path(name)/'x';p.write_text('{"a":1,"a":2}')
            with self.assertRaises(static.InvalidRecipe): static.read_json(p)
    def test_nonfinite_json(self):
        with tempfile.TemporaryDirectory() as name:
            p=Path(name)/'x';p.write_text('{"a":NaN}')
            with self.assertRaises(static.InvalidRecipe): static.read_json(p)
    def test_symlink_input(self):
        with tempfile.TemporaryDirectory() as name:
            r=Path(name);(r/'real').write_text('x');(r/'link').symlink_to(r/'real')
            with self.assertRaises((static.InvalidRecipe,OSError)): static.read_regular(r/'link')
    def test_size_bound(self):
        with tempfile.TemporaryDirectory() as name:
            p=Path(name)/'x';p.write_bytes(b'12345')
            with self.assertRaises(static.InvalidRecipe): static.read_regular(p,4)
    def test_pure_check_path_never_loads_runtime_or_tools(self):
        with tempfile.TemporaryDirectory() as name:
            root=Path(name);native=root/'ci/native';shutil.copytree(HERE,native,ignore=shutil.ignore_patterns('__pycache__'))
            lock=copy.deepcopy(self.lock)
            for rel in ('archive/go.mod','archivebridge/go.mod'):
                path=root/rel;path.parent.mkdir(exist_ok=True)
                text='module wainak.local/test\n\ngo 1.27.3\nrequire (\nfilippo.io/age v1.3.2\ngolang.org/x/crypto v0.58.0\ngolang.org/x/sys v0.49.0\n)\n'
                if rel.startswith('archivebridge/'):text+='replace wainak.local/historyarchive => ../archive\n'
                path.write_text(text)
            (native/'lock.json').write_text(json.dumps(lock))
            with mock.patch.object(static,'validate_sources',return_value={'status':'fixture'}), mock.patch.object(sys,'argv',[str(native/'build.py'),'--check']), mock.patch('subprocess.Popen',side_effect=AssertionError('no subprocess')),mock.patch('urllib.request.urlopen',side_effect=AssertionError('no network')),mock.patch('sys.stdout',new=io.StringIO()):
                runpy.run_path(str(native/'build.py'),run_name='__main__')
    def test_source_runtime_pin_fail_closed(self):
        with tempfile.TemporaryDirectory() as name:
            root=Path(name);lock=copy.deepcopy(self.lock);lock['source_hashes']={}
            for rel in ('archive/go.mod','archivebridge/go.mod'):
                p=root/rel;p.parent.mkdir(exist_ok=True);p.write_text('go 1.27.3\nrequire golang.org/x/crypto v0.55.0\n')
            with self.assertRaises((static.InvalidRecipe,OSError)): static.validate_sources(root,lock)

class ArtifactTests(unittest.TestCase):
    def fat(self, wide=False, endian='>'):
        magic=(b'\xca\xfe\xba\xbf' if wide else b'\xca\xfe\xba\xbe') if endian=='>' else (b'\xbf\xba\xfe\xca' if wide else b'\xbe\xba\xfe\xca')
        data=magic+struct.pack(endian+'I',1)
        data+=struct.pack(endian+('IIQQII' if wide else 'IIIII'),0x0100000c,0,64,8,6,*([0] if wide else []))
        return data.ljust(64,b'\0')+b'!<arch>\n'
    def test_static_thin_and_fat_forms(self):
        self.assertEqual(artifact.static_arm64_container_bytes(b'!<arch>\n'),'thin-static-ar')
        for wide in (False,True):
            for endian in ('>','<'):
                self.assertIn('static-ar',artifact.static_arm64_container_bytes(self.fat(wide,endian)))
    def test_dynamic_macho_rejected(self):
        with self.assertRaises(static.InvalidRecipe):artifact.static_arm64_container_bytes(b'\xcf\xfa\xed\xfe'+b'\0'*64)
    def test_fat_dynamic_payload_rejected(self):
        data=self.fat()[:-8]+b'\xcf\xfa\xed\xfe'+b'\0'*4
        with self.assertRaises(static.InvalidRecipe):artifact.static_arm64_container_bytes(data)
    def test_fat_wrong_cpu(self):
        data=bytearray(self.fat());struct.pack_into('>I',data,8,0x01000007)
        with self.assertRaises(static.InvalidRecipe):artifact.static_arm64_container_bytes(data)
    def test_fat_offset_bounds(self):
        data=bytearray(self.fat());struct.pack_into('>I',data,16,4096)
        with self.assertRaises(static.InvalidRecipe):artifact.static_arm64_container_bytes(data)
    def test_fat_trailing_bytes_rejected(self):
        with self.assertRaises(static.InvalidRecipe):artifact.static_arm64_container_bytes(self.fat()+b'x')
    def test_exact_modulemap_not_umbrella_guess(self):
        headers=['ref.h','Archivebridge.objc.h','Universe.objc.h','Archivebridge.h']
        text='framework module "Archivebridge" {\n'+''.join('header "'+h+'"\n' for h in headers)+'export *\n}'
        artifact.validate_modulemap(text,headers)
        with self.assertRaises(static.InvalidRecipe):artifact.validate_modulemap(text.replace('header "Archivebridge.h"','umbrella header "Archivebridge.h"'),headers)

class LoadCommandTests(unittest.TestCase):
    def record(self, platform='IOS', minimum='15.0'):
        return 'member.o:\nLoad command 1\n cmd LC_BUILD_VERSION\n cmdsize 24\n platform '+platform+'\n minos '+minimum+'\n sdk 26.4\n'
    def test_numeric_and_symbolic_platforms(self):
        for p in ('2','IOS','PLATFORM_IOS'):
            self.assertEqual(artifact.validate_apple_load_commands(self.record(p),'device')['platform_id'],2)
        for p in ('7','IOSSIMULATOR','IOS_SIMULATOR','PLATFORM_IOSSIMULATOR'):
            self.assertEqual(artifact.validate_apple_load_commands(self.record(p),'simulator')['platform_id'],7)
    def test_wrong_actual_platform_rejected(self):
        with self.assertRaises(static.InvalidRecipe):artifact.validate_apple_load_commands(self.record('IOS'),'simulator')
    def test_legacy_minimum_is_not_platform_proof(self):
        legacy='Load command 1\n cmd LC_VERSION_MIN_IPHONEOS\n cmdsize 16\n version 15.0\n sdk 26.4\n'
        with self.assertRaises(static.InvalidRecipe):artifact.validate_apple_load_commands(legacy,'device')
    def test_conflicting_member_platform_rejected(self):
        with self.assertRaises(static.InvalidRecipe):artifact.validate_apple_load_commands(self.record('IOS')+self.record('IOSSIMULATOR'),'device')
    def test_missing_and_wrong_minimum_rejected(self):
        for text in (self.record().replace(' platform IOS\n',''),self.record(minimum='14.0')):
            with self.assertRaises(static.InvalidRecipe):artifact.validate_apple_load_commands(text,'device')
    def test_members_without_records_are_not_claimed(self):
        result=artifact.validate_apple_load_commands('go.o:\n'+self.record(),'device')
        self.assertEqual(result['platform_record_count'],1)
        self.assertIs(result['all_archive_members_platform_proven'],False)

class AcquisitionGuardTests(unittest.TestCase):
    def test_owned_path_rejects_escape(self):
        with tempfile.TemporaryDirectory() as name:
            root=Path(name)
            with self.assertRaises(static.InvalidRecipe):runtime.safe_child(root,root/'../outside')
    def test_owned_path_rejects_symlink(self):
        with tempfile.TemporaryDirectory() as name:
            root=Path(name);(root/'link').symlink_to(root)
            with self.assertRaises(static.InvalidRecipe):runtime.safe_child(root,root/'link/child')
    def test_explicit_group_required_before_work(self):
        with mock.patch('platform.system',return_value='Darwin'),mock.patch('platform.machine',return_value='arm64'),mock.patch('os.getpgrp',return_value=123),mock.patch('os.getpid',return_value=456):
            with self.assertRaises(static.InvalidRecipe):runtime.build_ios(Path('/not-created'),HERE,{},Path('/not-created/.ci-work/native'),Path('/not-created/.ci-work/native/Archivebridge.xcframework'))
    def test_foreign_host_rejected(self):
        with mock.patch('platform.system',return_value='Linux'):
            with self.assertRaises(static.InvalidRecipe):runtime.build_ios(Path('/not-created'),HERE,{},Path('/not-created/x'),Path('/not-created/y'))
    def test_tar_traversal_and_symlink_fail_before_extract(self):
        class Fake:
            def guard(self):pass
        for member in ('../escape','go/link'):
            with tempfile.TemporaryDirectory() as name:
                root=Path(name);archive=root/'go.tar.gz'
                with tarfile.open(archive,'w:gz') as tar:
                    info=tarfile.TarInfo(member)
                    if member=='go/link':info.type=tarfile.SYMTYPE;info.linkname='/outside'
                    tar.addfile(info)
                with self.assertRaises(static.InvalidRecipe):runtime.extract_go(Fake(),archive,root/'out',1024)
                self.assertFalse((root/'escape').exists())
    def test_tar_expansion_bound(self):
        class Fake:
            def guard(self):pass
        with tempfile.TemporaryDirectory() as name:
            root=Path(name);archive=root/'go.tar.gz'
            with tarfile.open(archive,'w:gz') as tar:
                info=tarfile.TarInfo('go/file');info.size=5;tar.addfile(info,io.BytesIO(b'12345'))
            with self.assertRaises(static.InvalidRecipe):runtime.extract_go(Fake(),archive,root/'out',4)
    def test_sanitized_env_no_credentials_or_automatic_toolchain(self):
        env=runtime.make_env(Path('/tmp/owned'),Path('/tmp/owned/go/bin/go'),'/Applications/Xcode.app/Contents/Developer')
        self.assertEqual(env['GOTOOLCHAIN'],'local');self.assertEqual(env['GOPROXY'],'off')
        self.assertEqual(env['GOSUMDB'],'off');self.assertNotIn('SSH_AUTH_SOCK',env);self.assertNotIn('CM_BUILD_DIR',env)

if __name__=='__main__':unittest.main()

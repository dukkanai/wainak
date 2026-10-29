"""Synthetic filesystem/config tests only. No Xcode/Flutter/tool subprocess."""
import importlib.util
import json
from pathlib import Path
import plistlib
import tempfile
import struct
import unittest

SPEC = importlib.util.spec_from_file_location('ios_verify', Path(__file__).resolve().parents[1] / 'ios/verify.py')
v = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(v)

class IOSRecipeChecks(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'Archivebridge.xcframework'
        self.root.mkdir()
        libraries = []
        for identifier, variant in [('ios-arm64', None), ('ios-arm64-simulator', 'simulator')]:
            fw = self.root / identifier / 'Archivebridge.framework'
            (fw / 'Headers').mkdir(parents=True)
            (fw / 'Modules').mkdir()
            (fw / 'Archivebridge').write_bytes(b'!<arch>\nPUBLIC STRUCTURAL FIXTURE NOT MACH-O')
            (fw / 'Headers/Archivebridge.h').write_text('#include "Archivebridge.objc.h"\n#include "Universe.objc.h"\n')
            (fw / 'Headers/Archivebridge.objc.h').write_text('\n'.join(v.read_json(Path(v.__file__).with_name('native-abi.json'))['declarations']))
            (fw / 'Headers/Universe.objc.h').write_text('// public fixture')
            (fw / 'Headers/ref.h').write_text('// public fixture')
            (fw / 'Modules/module.modulemap').write_text('framework module "Archivebridge" {\n' + '\n'.join('header "' + name + '"' for name in ('ref.h', 'Archivebridge.objc.h', 'Universe.objc.h', 'Archivebridge.h')) + '\nexport *\n}')
            lib = {'LibraryIdentifier': identifier, 'LibraryPath': 'Archivebridge.framework', 'SupportedPlatform': 'ios', 'SupportedArchitectures': ['arm64']}
            if variant:
                lib['SupportedPlatformVariant'] = variant
            libraries.append(lib)
        self.plist = {'XCFrameworkFormatVersion': '1.0', 'AvailableLibraries': libraries}
        self.save()

    def save(self):
        (self.root / 'Info.plist').write_bytes(plistlib.dumps(self.plist))

    def test_exact_two_static_slices_and_config(self):
        slices = v.framework_slices(self.root)
        self.assertEqual(set(slices), {'device', 'simulator'})
        config = v.xcconfig(slices)
        self.assertIn('WAINEK_ARCHIVE_BRIDGE=1', config)
        self.assertNotIn('Embed', config)
        self.assertIn('CODE_SIGNING_ALLOWED = NO', config)

    def test_umbrella_not_prototype_source(self):
        p = self.root / 'ios-arm64/Archivebridge.framework/Headers/Archivebridge.objc.h'
        p.write_text('// prototypes absent')
        with self.assertRaises(v.GateError): v.framework_slices(self.root)

    def test_same_name_changed_signature_rejected(self):
        p = self.root / 'ios-arm64/Archivebridge.framework/Headers/Archivebridge.objc.h'
        p.write_text(p.read_text().replace('int64_t handle', 'int32_t handle', 1))
        with self.assertRaises(v.GateError): v.framework_slices(self.root)

    def test_oversized_header_rejected(self):
        p = self.root / 'ios-arm64/Archivebridge.framework/Headers/Archivebridge.objc.h'
        p.write_text(p.read_text() + ' ' * 65536)
        with self.assertRaises(v.GateError): v.framework_slices(self.root)

    def test_non_ios_variant(self):
        self.plist['AvailableLibraries'][0]['SupportedPlatform'] = 'macos'
        self.save()
        with self.assertRaises(v.GateError): v.framework_slices(self.root)

    def test_duplicate_device_slice(self):
        self.plist['AvailableLibraries'][1].pop('SupportedPlatformVariant')
        self.save()
        with self.assertRaises(v.GateError): v.framework_slices(self.root)

    def test_unexpected_architecture(self):
        self.plist['AvailableLibraries'][0]['SupportedArchitectures'].append('x86_64')
        self.save()
        with self.assertRaises(v.GateError): v.framework_slices(self.root)

    def test_library_escape(self):
        self.plist['AvailableLibraries'][0]['LibraryIdentifier'] = '../outside'
        self.save()
        with self.assertRaises(v.GateError): v.framework_slices(self.root)

    def test_single_arm64_lipo_static_archive(self):
        p = self.root / 'ios-arm64/Archivebridge.framework/Archivebridge'
        body = p.read_bytes()
        p.write_bytes(struct.pack('>IIIIIII', 0xcafebabe, 1, 0x0100000c, 0, 32, len(body), 4) + b'\0' * 4 + body)
        v.framework_slices(self.root)

    def test_lipo_dynamic_slice_rejected(self):
        p = self.root / 'ios-arm64/Archivebridge.framework/Archivebridge'
        body = b'\xcf\xfa\xed\xfe' + b'\0' * 28
        p.write_bytes(struct.pack('>IIIIIII', 0xcafebabe, 1, 0x0100000c, 0, 32, len(body), 4) + b'\0' * 4 + body)
        with self.assertRaises(v.GateError): v.framework_slices(self.root)

    def test_dynamic_binary_rejected(self):
        (self.root / 'ios-arm64/Archivebridge.framework/Archivebridge').write_bytes(b'\xcf\xfa\xed\xfe')
        with self.assertRaises(v.GateError): v.framework_slices(self.root)

    def test_symlink_header_rejected(self):
        p = self.root / 'ios-arm64/Archivebridge.framework/Headers/ref.h'
        p.unlink(); p.symlink_to('/dev/null')
        with self.assertRaises(v.GateError): v.framework_slices(self.root)

    def test_artifact_inventory_detects_byte_change(self):
        before = v.inventory(self.root)
        (self.root / 'ios-arm64/Archivebridge.framework/Headers/ref.h').write_text('changed')
        self.assertNotEqual(before, v.inventory(self.root))

    def test_config_injection_rejected(self):
        with self.assertRaises(v.GateError):
            v.xcconfig({'device': Path('/a/$(UNTRUSTED)'), 'simulator': Path('/b')})

    def settings(self):
        return [{'target': 'Runner', 'buildSettings': {'CODE_SIGNING_ALLOWED': 'NO', 'CODE_SIGNING_REQUIRED': 'NO', 'CODE_SIGN_IDENTITY': '', 'DEVELOPMENT_TEAM': '', 'CONFIGURATION': 'Debug', 'PLATFORM_NAME': 'iphoneos', 'IPHONEOS_DEPLOYMENT_TARGET': '15.0', 'ARCHS': 'arm64', 'SWIFT_ACTIVE_COMPILATION_CONDITIONS': 'DEBUG WAINEK_ARCHIVE_BRIDGE', 'GCC_PREPROCESSOR_DEFINITIONS': 'WAINEK_ARCHIVE_BRIDGE=1', 'OTHER_LDFLAGS': '-framework Archivebridge'}}]

    def test_effective_unsigned_settings(self):
        v.unsigned_settings(self.settings(), 'iphoneos')

    def test_signing_enabled_rejected(self):
        value = self.settings(); value[0]['buildSettings']['CODE_SIGNING_ALLOWED'] = 'YES'
        with self.assertRaises(v.GateError): v.unsigned_settings(value, 'iphoneos')

    def test_team_even_without_signing_rejected(self):
        value = self.settings(); value[0]['buildSettings']['DEVELOPMENT_TEAM'] = 'PUBLICFIXTURE'
        with self.assertRaises(v.GateError): v.unsigned_settings(value, 'iphoneos')

    def test_disabled_native_engine_rejected(self):
        value = self.settings(); value[0]['buildSettings']['SWIFT_ACTIVE_COMPILATION_CONDITIONS'] = 'DEBUG'
        with self.assertRaises(v.GateError): v.unsigned_settings(value, 'iphoneos')

    def test_release_rejected(self):
        value = self.settings(); value[0]['buildSettings']['CONFIGURATION'] = 'Release'
        with self.assertRaises(v.GateError): v.unsigned_settings(value, 'iphoneos')

    def test_wrong_sdk_rejected(self):
        with self.assertRaises(v.GateError): v.unsigned_settings(self.settings(), 'iphonesimulator')

    def test_json_duplicate_rejected(self):
        path = Path(self.temp.name) / 'bad.json'; path.write_text('{"a":1,"a":2}')
        with self.assertRaises(v.GateError): v.read_json(path)


if __name__ == '__main__': unittest.main()

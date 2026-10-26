"""Pure-stdlib checks. No tool execution, network, signing or device access."""
from __future__ import annotations
import hashlib
import json
import plistlib
import re
import struct
from pathlib import Path, PurePosixPath

class GateError(ValueError):
    pass

def require(value, label):
    if not value:
        raise GateError(label)

def pairs(items):
    result = {}
    for key, value in items:
        require(key not in result, 'duplicate_json_key')
        result[key] = value
    return result

def read_json(path, maximum=4 * 1024 * 1024):
    path = Path(path)
    require(path.is_file() and not path.is_symlink(), 'not_regular_json')
    require(path.stat().st_size <= maximum, 'json_size')
    return json.loads(path.read_text(encoding='utf-8'), object_pairs_hook=pairs)

def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as source:
        while block := source.read(1024 * 1024):
            h.update(block)
    return h.hexdigest()

def inside(root, relative):
    root = Path(root).resolve(strict=True)
    p = PurePosixPath(relative)
    require(not p.is_absolute() and '..' not in p.parts and p.parts and str(p) == relative, 'unsafe_relative_path')
    current = root
    for part in p.parts:
        current /= part
        require(not current.is_symlink(), 'symlink_path')
    require(current.resolve(strict=True).is_relative_to(root), 'outside_root')
    return current

def inventory(root):
    root = Path(root)
    require(root.is_dir() and not root.is_symlink(), 'artifact_root')
    result = {}
    total = 0
    for p in sorted(root.rglob('*')):
        require(not p.is_symlink(), 'artifact_symlink')
        if p.is_dir():
            continue
        require(p.is_file(), 'artifact_special_file')
        total += p.stat().st_size
        require(total <= 2 * 1024 ** 3 and len(result) < 2000, 'artifact_bound')
        result[p.relative_to(root).as_posix()] = digest(p)
    require(result, 'empty_artifact')
    return result

def static_arm64_archive(path):
    """Accept thin ar or one arm64 ar slice in a lipo wrapper; never a dylib."""
    path = Path(path)
    total = path.stat().st_size
    require(8 <= total <= 2 * 1024 ** 3, 'archive_size')
    with path.open('rb') as source:
        head = source.read(8)
        if head == b'!<arch>\n':
            return
        magic, count = struct.unpack('>II', head)
        require(magic in (0xcafebabe, 0xcafebabf) and count == 1, 'not_static_arm64_archive')
        width = 20 if magic == 0xcafebabe else 32
        row = source.read(width)
        require(len(row) == width, 'fat_header_truncated')
        if width == 20:
            cpu, subtype, offset, length, align = struct.unpack('>IIIII', row)
        else:
            cpu, subtype, offset, length, align, reserved = struct.unpack('>IIQQII', row)
            require(reserved == 0, 'fat_reserved')
        require(cpu == 0x0100000c and subtype & 0x00ffffff == 0, 'fat_architecture')
        require(align <= 30 and offset >= 8 + width and offset % (1 << align) == 0, 'fat_offset')
        require(length >= 8 and offset + length == total, 'fat_extent')
        source.seek(offset)
        require(source.read(8) == b'!<arch>\n', 'fat_slice_not_static')


def framework_slices(root, expected_abi=None):
    """Structural validation only; native recipe separately checks Mach-O minima/ABI."""
    root = Path(root).resolve(strict=True)
    if expected_abi is None:
        expected_abi = read_json(Path(__file__).with_name('native-abi.json'))['declarations']
    require(len(expected_abi) == 7, 'abi_policy')
    info = inside(root, 'Info.plist')
    require(info.stat().st_size <= 1024 * 1024, 'plist_size')
    value = plistlib.loads(info.read_bytes())
    require(value.get('XCFrameworkFormatVersion') == '1.0', 'xcframework_version')
    libraries = value.get('AvailableLibraries')
    require(isinstance(libraries, list) and len(libraries) == 2, 'slice_count')
    result = {}
    for lib in libraries:
        require(lib.get('SupportedPlatform') == 'ios' and lib.get('SupportedArchitectures') == ['arm64'], 'slice_architecture')
        variant = lib.get('SupportedPlatformVariant', 'device')
        require(variant in ('device', 'simulator') and variant not in result, 'slice_variant')
        require(lib.get('LibraryPath') == 'Archivebridge.framework', 'framework_name')
        folder = inside(root, lib['LibraryIdentifier'])
        fw = inside(folder, lib['LibraryPath'])
        require(fw.is_dir(), 'framework_directory')
        binary = inside(fw, 'Archivebridge')
        static_arm64_archive(binary)
        umbrella_path = inside(fw, 'Headers/Archivebridge.h')
        require(umbrella_path.stat().st_size <= 65536, 'umbrella_size')
        umbrella = umbrella_path.read_text(encoding='utf-8')
        require('Archivebridge.objc.h' in umbrella and 'Universe.objc.h' in umbrella, 'umbrella_includes')
        header_path = inside(fw, 'Headers/Archivebridge.objc.h')
        require(header_path.stat().st_size <= 65536, 'header_size')
        header = header_path.read_text(encoding='utf-8')
        declarations = [re.sub(r'\s+', ' ', d).strip() for d in re.findall(r'FOUNDATION_EXPORT[^;]+;', header) if '(' in d]
        require(declarations == expected_abi, 'native_abi_changed')
        module_path = inside(fw, 'Modules/module.modulemap')
        require(module_path.stat().st_size <= 8192, 'module_size')
        module = module_path.read_text(encoding='utf-8')
        require('framework module "Archivebridge"' in module and 'export *' in module, 'module_shape')
        for name in ('ref.h', 'Archivebridge.objc.h', 'Universe.objc.h', 'Archivebridge.h'):
            require('header "' + name + '"' in module, 'module_header')
            require(inside(fw, 'Headers/' + name).is_file(), 'module_header_file')
        # Upstream static framework's MinimumOSVersion=100.0 is NOT evidence
        # of the object deployment target and must not be rewritten here.
        result[variant] = folder
    return result

def xcconfig(slices):
    require(set(slices) == {'device', 'simulator'}, 'missing_slices')
    for path in slices.values():
        require(not any(c in str(path) for c in '\n\r"$\\'), 'unsafe_xcconfig_path')
    return '\n'.join([
        '// Generated only after native artifact verification; static link, never embed.',
        'SWIFT_ACTIVE_COMPILATION_CONDITIONS = $(inherited) DEBUG WAINAK_ARCHIVE_BRIDGE',
        'GCC_PREPROCESSOR_DEFINITIONS = $(inherited) WAINAK_ARCHIVE_BRIDGE=1',
        'FRAMEWORK_SEARCH_PATHS[sdk=iphoneos*] = $(inherited) "' + str(slices['device']) + '"',
        'FRAMEWORK_SEARCH_PATHS[sdk=iphonesimulator*] = $(inherited) "' + str(slices['simulator']) + '"',
        'OTHER_LDFLAGS = $(inherited) -framework Archivebridge -framework Foundation',
        'CODE_SIGNING_ALLOWED = NO', 'CODE_SIGNING_REQUIRED = NO', 'CODE_SIGN_IDENTITY =',
        'DEVELOPMENT_TEAM =', 'PROVISIONING_PROFILE_SPECIFIER =', 'PROVISIONING_PROFILE =',
        'IPHONEOS_DEPLOYMENT_TARGET = 15.0', '',
    ])

def unsigned_settings(items, sdk):
    require(isinstance(items, list) and items, 'empty_build_settings')
    runner = [x for x in items if x.get('target') == 'Runner']
    require(len(runner) == 1, 'runner_settings')
    for item in items:
        b = item.get('buildSettings', {})
        require(b.get('CODE_SIGNING_ALLOWED') == 'NO' and b.get('CODE_SIGNING_REQUIRED') == 'NO', 'signing_enabled')
        for key in ('CODE_SIGN_IDENTITY', 'DEVELOPMENT_TEAM', 'PROVISIONING_PROFILE', 'PROVISIONING_PROFILE_SPECIFIER'):
            require(not b.get(key), 'signing_identity_or_profile')
    b = runner[0]['buildSettings']
    require(b.get('CONFIGURATION') == 'Debug' and b.get('PLATFORM_NAME') == sdk, 'wrong_configuration')
    require(b.get('IPHONEOS_DEPLOYMENT_TARGET') == '15.0', 'deployment_target')
    require(b.get('ARCHS') == 'arm64', 'runner_architecture')
    require('WAINAK_ARCHIVE_BRIDGE' in b.get('SWIFT_ACTIVE_COMPILATION_CONDITIONS', '').split(), 'native_swift_disabled')
    require('WAINAK_ARCHIVE_BRIDGE=1' in b.get('GCC_PREPROCESSOR_DEFINITIONS', '').split(), 'native_objc_disabled')
    require('-framework Archivebridge' in b.get('OTHER_LDFLAGS', ''), 'native_link_disabled')
    return b


UNCACHED_SETTINGS = ('COMPILATION_CACHE_ENABLE_CACHING', 'CLANG_ENABLE_COMPILE_CACHE',
                     'SWIFT_ENABLE_COMPILE_CACHE')


def uncached_settings(items, sdk):
    """Require explicit command-scoped cache-off values for every planned target."""
    require(sdk in ('iphoneos', 'iphonesimulator'), 'cache_policy_sdk')
    require(type(items) is list and items, 'cache_policy_settings')
    names = []
    for item in items:
        require(type(item) is dict and type(item.get('target')) is str, 'cache_policy_settings')
        names.append(item['target'])
        settings = item.get('buildSettings')
        require(type(settings) is dict, 'cache_policy_settings')
        require(all(settings.get(key) == 'NO' for key in UNCACHED_SETTINGS), 'compile_cache_enabled_or_unknown')
    require(len(names) == len(set(names)) and names.count('Runner') == 1, 'cache_policy_targets')
    if sdk == 'iphonesimulator':
        require(names.count('RunnerTests') == 1, 'cache_policy_test_target_missing')
    return {'targets_checked': len(items), 'settings': {key: 'NO' for key in UNCACHED_SETTINGS}}

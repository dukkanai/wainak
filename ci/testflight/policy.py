"""Pure policy for the one owner-approved internal UI build; no tool execution."""
import base64
import datetime
import re

BUNDLE = 'com.nextaura.wainek'
TEAM = '9G7GPBG7FB'
INTEGRATION = 'Codemagic Wainak'
CERTIFICATE = 'nextaura_apple_distribution'
PROFILE = 'wainek_app_store'
ASC_APP_ID = '6828249128'
ARTIFACT = '.ci-work/testflight/verified/wainek-internal.ipa'
DEFINES = ['--dart-define=WAINEK_DEV_MODE=true', '--dart-define=WAINEK_REPOSITORY=fake']
SIGNING_CONFIG = '''// Used only by the explicit TestFlight driver, never the unsigned recipe.
CODE_SIGNING_ALLOWED = YES
CODE_SIGNING_REQUIRED = YES
CODE_SIGN_STYLE = Manual
CODE_SIGN_IDENTITY = Apple Distribution
CODE_SIGN_IDENTITY[sdk=iphoneos*] = Apple Distribution
DEVELOPMENT_TEAM = 9G7GPBG7FB
'''
CUSTOM_EXPORT = {
    'method': 'app-store', 'destination': 'export', 'teamID': TEAM,
    'signingStyle': 'manual', 'testFlightInternalTestingOnly': True,
    'manageAppVersionAndBuildNumber': False,
}

class PolicyError(ValueError):
    pass

def require(ok, reason):
    if not ok:
        raise PolicyError(reason)

def workflow():
    return {
        'name': 'iOS TestFlight — internal fake UI and VoiceOver only',
        'instance_type': 'mac_mini_m2', 'max_build_duration': 45,
        'integrations': {'app_store_connect': INTEGRATION},
        'environment': {
            'xcode': '26.4.1', 'flutter': '3.47.8',
            'ios_signing': {'provisioning_profiles': [PROFILE], 'certificates': [CERTIFICATE]},
        },
        'scripts': [
            {'name': 'Source and publication gates', 'script': 'python3 ci/check_preparation.py && python3 scripts/check_publication.py'},
            {'name': 'Unsigned and signed policy regressions', 'script': "python3 -m unittest discover -s ci/tests -p 'test_*.py' -v"},
            {'name': 'Build and verify internal UI IPA', 'script': 'python3 ci/testflight/build.py --build-internal'},
        ],
        'artifacts': [ARTIFACT],
        'publishing': {'app_store_connect': {
            'auth': 'integration', 'submit_to_testflight': False, 'submit_to_app_store': False,
        }},
    }

def validate_workflow(value):
    # Exact, type-sensitive schema: no extra commands, triggers, groups, secrets,
    # external beta groups, public release, broad artifact globs or auto-expiry.
    import json
    require(json.dumps(value, sort_keys=True) == json.dumps(workflow(), sort_keys=True), 'testflight_workflow_policy')

def validate_export(value):
    require(isinstance(value, dict), 'export_options_type')
    for key, expected in CUSTOM_EXPORT.items():
        require(type(value.get(key)) is type(expected) and value[key] == expected, 'export_' + key)
    profiles = value.get('provisioningProfiles')
    require(isinstance(profiles, dict) and set(profiles) == {BUNDLE}, 'export_profiles')
    require(isinstance(profiles[BUNDLE], str) and bool(profiles[BUNDLE].strip()), 'export_profile_empty')

def build_number(value):
    require(isinstance(value, str) and re.fullmatch(r'[1-9][0-9]{0,8}', value) is not None, 'build_number')
    return value

def validate_settings(items):
    require(isinstance(items, list), 'settings_type')
    runner = [x.get('buildSettings', {}) for x in items if x.get('target') == 'Runner']
    require(len(runner) == 1, 'runner_settings')
    b = runner[0]
    for key, expected in {
        'PRODUCT_BUNDLE_IDENTIFIER': BUNDLE, 'DEVELOPMENT_TEAM': TEAM,
        'CONFIGURATION': 'Release', 'PLATFORM_NAME': 'iphoneos',
        'CODE_SIGNING_ALLOWED': 'YES', 'CODE_SIGNING_REQUIRED': 'YES',
        'CODE_SIGN_STYLE': 'Manual', 'CODE_SIGN_IDENTITY': 'Apple Distribution',
    }.items():
        require(b.get(key) == expected, 'settings_' + key)
    require(bool(b.get('PROVISIONING_PROFILE_SPECIFIER') or b.get('PROVISIONING_PROFILE')), 'missing_profile')
    for key in ('SWIFT_ACTIVE_COMPILATION_CONDITIONS', 'GCC_PREPROCESSOR_DEFINITIONS', 'OTHER_LDFLAGS', 'FRAMEWORK_SEARCH_PATHS'):
        require('WAINEK_ARCHIVE_BRIDGE' not in str(b.get(key, '')) and 'archivebridge' not in str(b.get(key, '')).lower(), 'native_archive_enabled')
    values = {}
    for item in b.get('DART_DEFINES', '').split(','):
        require(bool(item), 'missing_dart_defines')
        try:
            value = base64.b64decode(item, validate=True).decode('utf-8')
        except (ValueError, UnicodeError):
            raise PolicyError('invalid_dart_define') from None
        key, sep, val = value.partition('=')
        require(sep and key not in values, 'duplicate_or_invalid_define')
        values[key] = val
    require({k: v for k, v in values.items() if k.startswith('WAINEK_')} ==
            {'WAINEK_DEV_MODE': 'true', 'WAINEK_REPOSITORY': 'fake'}, 'wrong_ui_mode')

def validate_profile(profile, entitlements, info, number, now=None):
    require(info.get('CFBundleIdentifier') == BUNDLE and info.get('CFBundleVersion') == number, 'app_identity')
    require(info.get('DTPlatformName') == 'iphoneos', 'app_platform')
    require(profile.get('TeamIdentifier') == [TEAM], 'profile_team')
    require('ProvisionedDevices' not in profile and not profile.get('ProvisionsAllDevices', False), 'not_app_store_profile')
    expires = profile.get('ExpirationDate')
    require(isinstance(expires, datetime.datetime), 'profile_expiry_missing')
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=datetime.timezone.utc)
    require(expires > (now or datetime.datetime.now(datetime.timezone.utc)), 'profile_expired')
    p = profile.get('Entitlements', {})
    for values in (p, entitlements):
        require(values.get('application-identifier') == TEAM + '.' + BUNDLE, 'application_identifier')
        require(values.get('com.apple.developer.team-identifier') == TEAM, 'entitlement_team')
        require(values.get('get-task-allow') is False, 'debug_entitlement')
        require(values.get('beta-reports-active') is True, 'not_beta_distribution')

"""Internal distribution negative controls; no Apple, cloud or compiler calls."""
import base64
import copy
import datetime as dt
import json
from itertools import product
import plistlib
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock
import zipfile

from ci import check_preparation as prep
from ci.testflight import policy as p
from ci.testflight import build as b


def settings():
    values = {'PRODUCT_BUNDLE_IDENTIFIER': p.BUNDLE, 'DEVELOPMENT_TEAM': p.TEAM,
              'CONFIGURATION': 'Release', 'PLATFORM_NAME': 'iphoneos',
              'CODE_SIGNING_ALLOWED': 'YES', 'CODE_SIGNING_REQUIRED': 'YES',
              'CODE_SIGN_STYLE': 'Manual', 'CODE_SIGN_IDENTITY': 'Apple Distribution',
              'PROVISIONING_PROFILE_SPECIFIER': 'public-fixture-profile',
              'DART_DEFINES': ','.join(base64.b64encode(x.encode()).decode() for x in
                                      ['WAINEK_DEV_MODE=true', 'WAINEK_REPOSITORY=fake'])}
    return [{'target': 'Runner', 'buildSettings': values}]


def export():
    return {**p.CUSTOM_EXPORT, 'provisioningProfiles': {p.BUNDLE: 'public-fixture-profile'}}


def signed_values():
    ent = {'application-identifier': p.TEAM+'.'+p.BUNDLE,
           'com.apple.developer.team-identifier': p.TEAM,
           'get-task-allow': False, 'beta-reports-active': True}
    return ({'TeamIdentifier': [p.TEAM], 'ExpirationDate': dt.datetime(2099, 1, 1),
             'Entitlements': copy.deepcopy(ent)}, ent,
            {'CFBundleIdentifier': p.BUNDLE, 'CFBundleVersion': '7', 'DTPlatformName': 'iphoneos'})


class TestFlightWorkflow(unittest.TestCase):
    def test_exact_signed_workflow_and_original_unsigned_workflows(self):
        config = prep.read_json(prep.ROOT / 'codemagic.yaml')
        prep.validate_workflow(config)
        p.validate_workflow(config['workflows']['ios-testflight'])
        self.assertEqual((prep.ROOT/'ci/testflight/Signing.xcconfig').read_text(), p.SIGNING_CONFIG)

    def test_publish_and_execution_escape_matrix(self):
        changes = [
            lambda w: w.update(triggering={'events': ['push']}),
            lambda w: w.update(cache={'cache_paths': ['.ci-work']}),
            lambda w: w.update(artifacts=['**/*.ipa']),
            lambda w: w.update(instance_type='mac_mini_m4'),
            lambda w: w.update(max_build_duration=True),
            lambda w: w['environment'].update(groups=['secrets']),
            lambda w: w['environment']['ios_signing'].update(distribution_type='ad_hoc'),
            lambda w: w['environment']['ios_signing'].update(bundle_identifier='com.other.app'),
            lambda w: w['environment']['ios_signing'].update(certificates=['other']),
            lambda w: w['environment']['ios_signing'].update(provisioning_profiles=['other']),
            lambda w: w['integrations'].update(app_store_connect='Other account'),
            lambda w: w['publishing']['app_store_connect'].update(submit_to_app_store=True),
            lambda w: w['publishing']['app_store_connect'].update(submit_to_testflight=True),
            lambda w: w['publishing']['app_store_connect'].update(submit_to_testflight=0),
            lambda w: w['publishing']['app_store_connect'].update(beta_groups=['External']),
            lambda w: w['publishing']['app_store_connect'].update(release_type='AFTER_APPROVAL'),
            lambda w: w['publishing']['app_store_connect'].update(api_key='synthetic-disallowed-value'),
            lambda w: w['publishing'].update(email={'recipients': ['fixture@example.invalid']}),
            lambda w: w['scripts'].append({'name': 'Create key', 'script': 'app-store-connect fetch-signing-files --create'}),
            lambda w: w['scripts'][-1].update(script='flutter build ipa'),
        ]
        for change in changes:
            value = p.workflow(); change(value)
            with self.subTest(change=changes.index(change)), self.assertRaises(p.PolicyError):
                p.validate_workflow(value)

    def test_unsigned_cannot_inherit_signed_environment(self):
        value = prep.read_json(prep.ROOT/'codemagic.yaml')
        for key in ('ios-unsigned-archive', 'ios-unsigned-40gib-experiment'):
            changed = copy.deepcopy(value)
            changed['workflows'][key]['environment'].update(ios_signing=p.workflow()['environment']['ios_signing'])
            with self.assertRaises(prep.InvalidPreparation):prep.validate_workflow(changed)

    def test_unsigned_defaults_stay_disabled_with_new_identifiers(self):
        source = (prep.ROOT/'apps/mobile/ios/Runner.xcodeproj/project.pbxproj').read_text()
        self.assertEqual(source.count('CODE_SIGNING_ALLOWED = NO;'), 9)
        self.assertNotIn('CODE_SIGNING_ALLOWED = YES;', source)
        self.assertNotIn('invalid.example.wainek.wainekMobile', source)
        self.assertEqual(source.count('PRODUCT_BUNDLE_IDENTIFIER = '+p.BUNDLE+';'), 3)
        self.assertEqual(source.count('PRODUCT_BUNDLE_IDENTIFIER = '+p.BUNDLE+'.RunnerTests;'), 3)


class ExportAndSettings(unittest.TestCase):
    def test_accept_known_export(self):p.validate_export(export())

    def test_export_scope_negative_matrix(self):
        cases = [('method', 'ad-hoc'), ('method', 'enterprise'), ('method', 'development'),
                 ('destination', 'upload'), ('teamID', 'WRONGTEAM1'),
                 ('signingStyle', 'automatic'), ('testFlightInternalTestingOnly', False),
                 ('testFlightInternalTestingOnly', 1), ('testFlightInternalTestingOnly', 'true'),
                 ('manageAppVersionAndBuildNumber', True),
                 ('provisioningProfiles', {p.BUNDLE: ''}),
                 ('provisioningProfiles', {'*': 'public'}),
                 ('provisioningProfiles', {p.BUNDLE:'public','com.other.app':'public'})]
        for key,value in cases:
            with self.subTest(key=key,value=value), self.assertRaises(p.PolicyError):
                p.validate_export({**export(),key:value})
        for key in p.CUSTOM_EXPORT:
            value=export();value.pop(key)
            with self.subTest(missing=key), self.assertRaises(p.PolicyError):p.validate_export(value)

    def test_accept_known_settings(self):p.validate_settings(settings())

    def test_settings_negative_matrix(self):
        cases = [('PRODUCT_BUNDLE_IDENTIFIER','com.other.app'),('DEVELOPMENT_TEAM','OTHER'),
                 ('CONFIGURATION','Debug'),('PLATFORM_NAME','iphonesimulator'),
                 ('CODE_SIGNING_ALLOWED','NO'),('CODE_SIGN_IDENTITY','-'),
                 ('PROVISIONING_PROFILE_SPECIFIER',''),
                 ('SWIFT_ACTIVE_COMPILATION_CONDITIONS','WAINEK_ARCHIVE_BRIDGE'),
                 ('OTHER_LDFLAGS','-framework Archivebridge'),('DART_DEFINES','!invalid!')]
        for key,value in cases:
            candidate=settings();candidate[0]['buildSettings'][key]=value
            with self.subTest(key=key), self.assertRaises(p.PolicyError):p.validate_settings(candidate)
        for mode in ['api','identity','native_archive','local_cards']:
            candidate=settings();candidate[0]['buildSettings']['DART_DEFINES']=','.join(
                base64.b64encode(x.encode()).decode() for x in ['WAINEK_DEV_MODE=true','WAINEK_REPOSITORY='+mode])
            with self.subTest(mode=mode), self.assertRaises(p.PolicyError):p.validate_settings(candidate)

    def test_duplicate_and_extra_wainek_defines_rejected(self):
        for extra in ['WAINEK_REPOSITORY=fake','WAINEK_API_BASE_URL=http://127.0.0.1','WAINEK_IOS_ARCHIVE_PREVIEW=true']:
            value=settings();value[0]['buildSettings']['DART_DEFINES']+=','+base64.b64encode(extra.encode()).decode()
            with self.subTest(extra=extra), self.assertRaises(p.PolicyError):p.validate_settings(value)

    def test_profile_positive(self):p.validate_profile(*signed_values(),'7')

    def test_profile_rejects_wrong_distribution_identity_and_expiry(self):
        changes=[lambda v:v[0].update(ProvisionedDevices=['public-fixture']),
                 lambda v:v[0].update(ProvisionsAllDevices=True),
                 lambda v:v[0].update(ExpirationDate=dt.datetime(2000,1,1)),
                 lambda v:v[0].update(TeamIdentifier=['OTHER']),
                 lambda v:v[1].update({'application-identifier':p.TEAM+'.*'}),
                 lambda v:v[1].update({'get-task-allow':True}),
                 lambda v:v[0]['Entitlements'].update({'get-task-allow':True}),
                 lambda v:v[1].pop('beta-reports-active'),
                 lambda v:v[2].update(CFBundleVersion='6'),
                 lambda v:v[2].update(CFBundleIdentifier='com.other.app'),
                 lambda v:v[2].update(DTPlatformName='iphonesimulator')]
        for change in changes:
            value=signed_values();change(value)
            with self.subTest(change=changes.index(change)), self.assertRaises(p.PolicyError):p.validate_profile(*value,'7')


class DriverGuards(unittest.TestCase):
    def env(self):
        return {'CM_PROJECT_ID':'6add6ea46576d8df9a1d3f59','CM_WORKFLOW_NAME':'ios-testflight',
                'CM_TRIGGER_SOURCE':'api','CM_PULL_REQUEST':'false','CM_BUILD_DIR':str(b.ROOT),
                'CM_COMMIT':'a'*40,'PROJECT_BUILD_NUMBER':'6'}

    def test_preflight_and_increasing_project_counter(self):
        self.assertEqual(b.preflight(self.env(),'darwin','arm64',b.ROOT),'7')

    def test_preflight_resolves_checkout_alias_but_rejects_other_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve(strict=True)
            alias = root/'checkout-alias'
            alias.symlink_to(root, target_is_directory=True)
            other = root/'other-checkout'
            other.mkdir()
            other_alias = root/'other-alias'
            other_alias.symlink_to(other, target_is_directory=True)
            self.assertNotEqual(alias, alias.resolve(strict=True))
            for checkout in (root, alias):
                with self.subTest(checkout=checkout.name):
                    env = {**self.env(), 'CM_BUILD_DIR': str(checkout)}
                    self.assertEqual(b.preflight(env, 'darwin', 'arm64', root), '7')
            for checkout in (other, other_alias):
                with self.subTest(wrong_checkout=checkout.name):
                    env = {**self.env(), 'CM_BUILD_DIR': str(checkout)}
                    with self.assertRaisesRegex(p.PolicyError, '^wrong_checkout$'):
                        b.preflight(env, 'darwin', 'arm64', root)
            # Reproduce the old fixture bug even on Linux: production ROOT is
            # canonical, so substituting an unresolved ROOT must still fail.
            with self.assertRaisesRegex(p.PolicyError, '^wrong_checkout$'):
                b.preflight({**self.env(), 'CM_BUILD_DIR': str(alias)}, 'darwin', 'arm64', alias)

    def test_preflight_rejects_local_wrong_project_and_automatic_runs(self):
        cases = [('CM_PROJECT_ID', 'other', 'wrong_codemagic_project'),
                 ('CM_WORKFLOW_NAME', 'ios-unsigned-archive', 'wrong_workflow'),
                 ('CM_TRIGGER_SOURCE', 'webhook', 'manual_non_pr_required'),
                 ('CM_TRIGGER_SOURCE', 'schedule', 'manual_non_pr_required'),
                 ('CM_PULL_REQUEST', 'true', 'manual_non_pr_required'),
                 ('CM_COMMIT', 'bad', 'missing_source_commit'),
                 ('CM_BUILD_DIR', '/tmp', 'wrong_checkout'),
                 ('PROJECT_BUILD_NUMBER', '-1', 'project_build_number'),
                 ('PROJECT_BUILD_NUMBER', '1;echo injected', 'project_build_number')]
        for key,value,reason in cases:
            with self.subTest(key=key,value=value), self.assertRaisesRegex(p.PolicyError, '^'+reason+'$'):
                b.preflight({**self.env(),key:value},'darwin','arm64',b.ROOT)
        with self.assertRaisesRegex(p.PolicyError, '^codemagic_macos_required$'):
            b.preflight(self.env(),'linux','x86_64',b.ROOT)

    def test_real_local_execution_stops_before_any_child(self):
        with mock.patch.object(b.sys,'platform','linux'),mock.patch.object(b,'run_bounded') as run:
            with self.assertRaises(p.PolicyError):b.execute()
            run.assert_not_called()

    def test_secrets_and_injected_xcconfig_not_in_child_environment(self):
        env=b.child_environment({'PATH':'/usr/bin','HOME':'/tmp/public-fixture',
            'APP_STORE_CONNECT_PRIVATE_KEY':'synthetic-not-a-key','CM_API_TOKEN':'synthetic',
            'XCODE_XCCONFIG_FILE':'/tmp/override','DART_DEFINES':'injected'})
        self.assertNotIn('APP_STORE_CONNECT_PRIVATE_KEY',env)
        self.assertNotIn('CM_API_TOKEN',env)
        self.assertNotIn('XCODE_XCCONFIG_FILE',env)
        self.assertNotIn('DART_DEFINES',env)

    def test_zip_rejects_escape_symlinks_duplicates_and_other_apps_before_extract(self):
        for kind in ('escape','symlink','duplicate','other-app','extension','native-archive'):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as directory:
                root=Path(directory);ipa=root/'fixture.ipa'
                with zipfile.ZipFile(ipa,'w') as z:
                    z.writestr('Payload/Runner.app/Info.plist','public structural fixture')
                    names={'escape':'../outside','other-app':'Payload/Other.app/Info.plist',
                           'extension':'Payload/Runner.app/PlugIns/Extra.appex/',
                           'native-archive':'Payload/Runner.app/Frameworks/Archivebridge.framework/'}
                    if kind=='symlink':
                        item=zipfile.ZipInfo('Payload/Runner.app/link');item.external_attr=0o120777<<16;z.writestr(item,'../../outside')
                    elif kind=='duplicate':
                        import warnings
                        with warnings.catch_warnings():
                            warnings.simplefilter('ignore');z.writestr('Payload/Runner.app/Info.plist','duplicate')
                    else:z.writestr(names[kind],'public')
                with self.assertRaises(p.PolicyError):b.safe_unpack(ipa,root/'inspect')
                self.assertFalse((root/'inspect').exists())

    def test_zip_valid_layout_and_size_bound(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);ipa=root/'fixture.ipa'
            with zipfile.ZipFile(ipa,'w') as z:z.writestr('Payload/Runner.app/Info.plist','fixture')
            self.assertTrue((b.safe_unpack(ipa,root/'inspect')/'Info.plist').is_file())
            with mock.patch.object(zipfile.ZipFile,'infolist') as entries:
                item=zipfile.ZipInfo('Payload/Runner.app/Info.plist');item.file_size=3*1024**3;entries.return_value=[item]
                with self.assertRaises(p.PolicyError):b.safe_unpack(ipa,root/'too-large')

    def test_complete_driver_and_failed_verification_never_publish(self):
        # Execute the real orchestration against synthetic subprocess outputs.
        # No signing tools, providers, network, or real credentials are involved.
        for via_alias, failure in product((False, True), (None, 'profile', 'codesign', 'export', 'architecture')):
            with self.subTest(via_alias=via_alias, failure=failure), tempfile.TemporaryDirectory() as directory:
                root = Path(directory).resolve(strict=True)
                checkout = root
                if via_alias:
                    checkout = root/'checkout-alias'
                    checkout.symlink_to(root, target_is_directory=True)
                (root/'apps/mobile').mkdir(parents=True)
                (root/'ci').mkdir()
                pins = json.loads((b.ROOT/'ci/ios-host-pins.json').read_text())
                (root/'ci/ios-host-pins.json').write_text(json.dumps(pins))
                env = {**self.env(), 'CM_BUILD_DIR': str(checkout)}
                profile, ent, info = signed_values()
                info['CFBundleExecutable'] = 'Runner'
                if failure == 'profile':
                    profile['TeamIdentifier'] = ['OTHER']
                calls = []

                def command_result(command, **kwargs):
                    cmd = [str(x) for x in command]
                    calls.append(cmd)
                    output = ''
                    if cmd[:3] == ['git', 'rev-parse', 'HEAD']:
                        output = env['CM_COMMIT']
                    elif cmd[:2] == ['flutter', '--version']:
                        output = json.dumps({field: pins['flutter'][key] for field, key in
                            [('frameworkVersion', 'version'), ('frameworkRevision', 'framework_revision'),
                             ('engineRevision', 'engine_revision'), ('dartSdkVersion', 'dart_version')]})
                    elif cmd == ['xcodebuild', '-version']:
                        output = 'Xcode 26.4.1\nBuild version 17E202\n'
                    elif cmd[:2] == ['xcode-project', 'use-profiles']:
                        options = export()
                        if failure == 'export':options['testFlightInternalTestingOnly'] = False
                        Path(cmd[cmd.index('--export-options-plist')+1]).write_bytes(plistlib.dumps(options))
                    elif '-showBuildSettings' in cmd:
                        output = json.dumps(settings())
                    elif cmd[:3] == ['flutter', 'build', 'ipa']:
                        target = root/'apps/mobile/build/ios/ipa'
                        target.mkdir(parents=True)
                        with zipfile.ZipFile(target/'fixture.ipa', 'w') as z:
                            z.writestr('Payload/Runner.app/Info.plist', plistlib.dumps(info))
                            z.writestr('Payload/Runner.app/Runner', b'public executable fixture')
                    elif cmd[:2] == ['codesign', '--verify'] and failure == 'codesign':
                        raise subprocess.CalledProcessError(1, 'codesign')
                    elif cmd[:2] == ['codesign', '-d']:
                        output = plistlib.dumps(ent).decode()
                    elif cmd[:2] == ['security', 'cms']:
                        output = plistlib.dumps(profile).decode()
                    elif cmd[:2] == ['lipo', '-archs']:
                        output = 'x86_64' if failure == 'architecture' else 'arm64'
                    return subprocess.CompletedProcess(cmd, 0, output, '')

                with mock.patch.object(b, 'ROOT', root), mock.patch.dict(b.os.environ, env, clear=True), \
                     mock.patch.object(b.sys, 'platform', 'darwin'), mock.patch.object(b.platform, 'machine', return_value='arm64'), \
                     mock.patch.object(b, 'run_bounded', side_effect=command_result), \
                     mock.patch.object(b.shutil, 'disk_usage', return_value=mock.Mock(free=8*1024**3)), \
                     mock.patch('builtins.print') as printed:
                    if failure is None:
                        b.execute()
                    elif failure == 'codesign':
                        with self.assertRaises(subprocess.CalledProcessError) as caught:
                            b.execute()
                        self.assertEqual(caught.exception.cmd, 'codesign')
                        self.assertEqual(caught.exception.returncode, 1)
                    else:
                        reason = {'profile': 'profile_team',
                                  'export': 'export_testFlightInternalTestingOnly',
                                  'architecture': 'device_architecture'}[failure]
                        with self.assertRaisesRegex(p.PolicyError, '^'+reason+'$'):
                            b.execute()
                self.assertEqual(printed.call_count, 1)
                report = json.loads(printed.call_args.args[0])
                if failure is None:
                    self.assertEqual(report['status'], 'VERIFIED_INTERNAL_IPA')
                else:
                    self.assertEqual(report, {
                        'status': 'FAILED_CLOSED', 'artifact_eligible': False,
                        'stage': 'profiles_and_export_policy' if failure == 'export' else 'verify_signed_payload',
                    })
                expected_last = {'export': ['xcode-project', 'use-profiles'],
                                 'codesign': ['codesign', '--verify'],
                                 'profile': ['security', 'cms']}.get(failure, ['lipo', '-archs'])
                self.assertEqual(calls[-1][:2], expected_last)
                if failure == 'export':
                    self.assertFalse(any(cmd[:3] == ['flutter', 'build', 'ipa'] for cmd in calls))
                else:
                    self.assertTrue(any(cmd[:3] == ['flutter', 'build', 'ipa'] for cmd in calls))
                self.assertEqual((root/p.ARTIFACT).is_file(), failure is None)
                self.assertFalse(any('app-store-connect' in c or '--create' in c for c in calls))

if __name__=='__main__':unittest.main()

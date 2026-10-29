"""Dormant GitHub internal-distribution contract. No credential or network access."""
import json
import re
from pathlib import Path
from ci.testflight import policy as p

ROOT = Path(__file__).resolve().parents[2]
BRANCH = 'dev/ios-testflight-internal-20261029'
ENVIRONMENT = 'wainek-internal-testflight'
PIN_FILE = ROOT / 'ci/github/internal-signing-pins.json'
CHECKOUT = 'actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1'
PYTHON = 'actions/setup-python@6d4fd22b20465ccc0f7354476588e8df7c9ca0e0'
SIGNING_SECRETS = ('WAINEK_DISTRIBUTION_P12_B64', 'WAINEK_DISTRIBUTION_P12_PASSWORD', 'WAINEK_APP_STORE_PROFILE_B64')
UPLOAD_SECRETS = ('WAINEK_ASC_PRIVATE_KEY_B64',)
PIN_FIELDS = {'enabled', 'certificate_sha256', 'certificate_sha1', 'profile_sha256', 'profile_uuid', 'asc_key_id', 'asc_issuer_id'}
REASONS = frozenset({'signed_disabled','signed_pin_schema','signed_pin_value','signed_context','signed_input',
    'signed_environment','signed_template','signed_profile_hash','signed_profile_identity','signed_certificate',
    'signed_secret_encoding','signed_secret_bound','signed_existing_path','signed_path','signed_export',
    'signed_source_drift','signed_receipt','signed_ipa_hash','signed_identity_count','signed_settings',
    'signed_cleanup','signed_upload_ambiguous','signed_no_ipa','signed_debug_logging','signed_p8_shape'})
# Fixed codes from the reused signing/ZIP policy, never exception text from tools.
REASONS |= frozenset({'build_number','app_identity','app_platform','profile_team','not_app_store_profile',
    'profile_expiry_missing','profile_expired','application_identifier','entitlement_team','debug_entitlement',
    'not_beta_distribution','settings_type','runner_settings','missing_profile','native_archive_enabled',
    'missing_dart_defines','invalid_dart_define','duplicate_or_invalid_define','wrong_ui_mode',
    'export_options_type','export_profiles','export_profile_empty','missing_plist_output','ipa_file','ipa_size',
    'ipa_path','ipa_special_file','missing_runner','extra_application','unexpected_extension_or_archive'})
REASONS |= frozenset('export_'+key for key in p.CUSTOM_EXPORT)
REASONS |= frozenset('settings_'+key for key in ('PRODUCT_BUNDLE_IDENTIFIER','DEVELOPMENT_TEAM','CONFIGURATION',
    'PLATFORM_NAME','CODE_SIGNING_ALLOWED','CODE_SIGNING_REQUIRED','CODE_SIGN_STYLE','CODE_SIGN_IDENTITY'))


def validate_pins(value, active=False):
    p.require(type(value) is dict and set(value) == PIN_FIELDS and type(value['enabled']) is bool, 'signed_pin_schema')
    if active:p.require(value['enabled'] is True, 'signed_disabled')
    if not value['enabled']:
        p.require(all(value[k] is None for k in PIN_FIELDS-{'enabled'}), 'signed_pin_value')
        return
    patterns = {'certificate_sha256':'[a-f0-9]{64}', 'certificate_sha1':'[A-F0-9]{40}',
        'profile_sha256':'[a-f0-9]{64}', 'profile_uuid':'[A-F0-9]{8}(?:-[A-F0-9]{4}){3}-[A-F0-9]{12}',
        'asc_key_id':'[A-Z0-9]{10}', 'asc_issuer_id':'[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}'}
    for key, pattern in patterns.items():
        p.require(type(value[key]) is str and re.fullmatch(pattern,value[key]) is not None, 'signed_pin_value')


def context(env):
    p.require(env.get('WAINEK_SIGNED_TARGET') == 'mac-internal' and
              env.get('WAINEK_SIGNED_ENVIRONMENT') == ENVIRONMENT and
              env.get('GITHUB_RUN_ATTEMPT') == '1', 'signed_context')
    p.require(env.get('RUNNER_DEBUG') != '1' and env.get('ACTIONS_STEP_DEBUG','').lower() != 'true' and
              env.get('ACTIONS_RUNNER_DEBUG','').lower() != 'true', 'signed_debug_logging')
    p.require(re.fullmatch('[a-f0-9]{40}',env.get('WAINEK_EXPECTED_SHA','')) is not None, 'signed_input')
    return p.build_number(env.get('WAINEK_BUILD_NUMBER',''))


def validate_environment(environment, branches):
    # Input is GitHub REST metadata, never secret values. Must be read again by
    # the operator before activation and approval; a fixture is not live proof.
    p.require(environment.get('name') == ENVIRONMENT and environment.get('can_admins_bypass') is False,
              'signed_environment')
    p.require(environment.get('deployment_branch_policy') ==
              {'protected_branches':False,'custom_branch_policies':True}, 'signed_environment')
    rules=environment.get('protection_rules',[])
    reviewers=[r for r in rules if r.get('type')=='required_reviewers']
    p.require(len(reviewers)==1 and reviewers[0].get('prevent_self_review') is True and
              1<=len(reviewers[0].get('reviewers',[]))<=6, 'signed_environment')
    p.require(all(r.get('type') in {'User','Team'} and type(r.get('reviewer',{}).get('id')) is int
                  and r['reviewer']['id']>0 for r in reviewers[0]['reviewers']), 'signed_environment')
    p.require(type(branches) is list and len(branches)==1 and branches[0].get('name')==BRANCH and
              branches[0].get('type')=='branch', 'signed_environment')


def job():
    return {
        'name':'Manual internal TestFlight — protected environment required',
        'if':"github.event_name == 'workflow_dispatch' && inputs.target == 'mac-internal' && github.repository == 'dukkanai/wainak' && github.event.repository.private == false && github.ref == 'refs/heads/"+BRANCH+"' && inputs.expected_sha == github.sha && github.run_attempt == 1",
        'runs-on':'macos-26', 'timeout-minutes':45, 'permissions':{'contents':'read'},
        'environment':ENVIRONMENT,
        'concurrency':{'group':'wainek-internal-testflight','cancel-in-progress':False},
        'env':{'WAINEK_REPOSITORY_VISIBILITY':'${{ github.event.repository.visibility }}',
               'WAINEK_RUNNER_LABEL':'macos-26','WAINEK_EXPECTED_SHA':'${{ inputs.expected_sha }}',
               'WAINEK_BUILD_NUMBER':'${{ inputs.build_number }}','WAINEK_SIGNED_TARGET':'mac-internal',
               'WAINEK_SIGNED_ENVIRONMENT':ENVIRONMENT},
        'steps':[
            {'uses':CHECKOUT,'with':{'persist-credentials':False,'ref':'${{ github.sha }}'}},
            {'uses':PYTHON,'with':{'python-version':'3.12.7'}},
            {'name':'Check inactive or reviewed configuration','run':'python3 ci/github/internal_testflight.py --check'},
            {'name':'Verify source, SDK, compile and sign internal UI',
             'env':{name:'${{ secrets.'+name+' }}' for name in SIGNING_SECRETS},
             'run':'python3 ci/github/internal_testflight.py --build'},
            {'name':'Upload verified internal-only IPA to Apple',
             'env':{name:'${{ secrets.'+name+' }}' for name in UPLOAD_SECRETS},
             'run':'python3 ci/github/internal_testflight.py --upload'},
            {'name':'Remove owned signing material','if':'${{ always() }}',
             'run':'python3 ci/github/internal_testflight.py --cleanup'},
        ]}


def validate_job(value):
    p.require(json.dumps(value,sort_keys=True)==json.dumps(job(),sort_keys=True),'signed_template')


def candidate_workflow(source):
    # Review-only output. Caller never writes to .github/workflows automatically.
    p.require('mac-internal' not in source and source.count('options: [ci, mac-unsigned]')==1 and
              source.count('  cancel-in-progress: true')==1,'signed_template')
    source=source.replace('options: [ci, mac-unsigned]','options: [ci, mac-unsigned, mac-internal]')
    source=source.replace('Full reviewed commit SHA required for mac-unsigned','Full reviewed commit SHA required for Mac targets')
    anchor="        default: ''\n"
    p.require(source.count(anchor)==1,'signed_template')
    source=source.replace(anchor,anchor+"      build_number:\n        description: Owner-reviewed unused positive Apple build number\n        type: string\n        default: ''\n")
    source=source.replace("inputs.target != 'mac-unsigned'", "inputs.target != 'mac-unsigned' && inputs.target != 'mac-internal'")
    # Separate groups prevent an unrelated CI/unsigned run cancelling a signed one.
    source=source.replace('group: ci-${{ github.workflow }}-', 'group: ci-${{ inputs.target }}-${{ github.workflow }}-')
    source=source.replace('  cancel-in-progress: true',"  cancel-in-progress: ${{ inputs.target != 'mac-internal' }}")
    return source+'\n  mac-internal: '+json.dumps(job(),ensure_ascii=False)+'\n'

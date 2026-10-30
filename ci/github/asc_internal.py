#!/usr/bin/env python3
"""Owner-protected metadata completion for the one reviewed fake UI build."""
import argparse
import base64
import json
import os
import re
from pathlib import Path
import sys
import time
import urllib.request

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from ci.github import asc_status as a, internal_policy as q
from ci.testflight import policy as p

BUILD_ID='2879f309-6272-419f-8c1a-084873dd9ae9'
BUILD_SOURCE='398801b2e08bb381f827ba1606e5f848426dea87'
APP_TREE='2b3769a8fd174af6ed9c2ab5bec5c2eda2f35c2d'
BUILD_PATH='/v1/builds/'+BUILD_ID
REASONS=a.REASONS|{'asc_reviewed_build','asc_reviewed_app_tree','asc_owner','asc_declaration_conflict','asc_patch_ambiguous'}


def job():
    value=a.job()
    value['name']='Complete reviewed internal build metadata — owner only'
    value['if']=value['if'].replace("inputs.target == 'asc-status'","inputs.target == 'asc-internal'")+" && github.actor == 'dukkanai' && github.actor_id == '255427171'"
    value['concurrency']={'group':'wainek-internal-testflight','cancel-in-progress':False}
    value['env']['WAINEK_ASC_INTERNAL_TARGET']='asc-internal'
    value['steps'][2]={'name':'Check one-build-only internal metadata plan','run':'python3 ci/github/asc_internal.py --check'}
    value['steps'][3]={'name':'Complete reviewed fake UI encryption metadata only',
        'env':{q.UPLOAD_SECRETS[0]:'${{ secrets.'+q.UPLOAD_SECRETS[0]+' }}'},'run':'python3 ci/github/asc_internal.py --complete'}
    value['steps'][4]={'name':'Remove owned Apple API material','if':'${{ always() }}','run':'python3 ci/github/asc_internal.py --cleanup'}
    return value


def validate_workflow():
    source=(ROOT/'.github/workflows/ci.yml').read_text();q.validate_active_workflow(source)
    rows=[line for line in source.splitlines() if line.startswith('  asc-internal: ')]
    p.require(len(rows)==1 and json.loads(rows[0].split(': ',1)[1])==job(),'asc_context')


def preflight(env):
    number=a.preflight(env)
    p.require(number=='1' and env.get('GITHUB_ACTOR')==q.OWNER_LOGIN and env.get('GITHUB_ACTOR_ID')==str(q.OWNER_ID)
        and env.get('WAINEK_ASC_INTERNAL_TARGET')=='asc-internal','asc_owner')
    p.require(env.get('RUNNER_DEBUG')!='1' and env.get('ACTIONS_STEP_DEBUG','').lower()!='true'
        and env.get('ACTIONS_RUNNER_DEBUG','').lower()!='true','asc_context')
    result=a.run_bounded(['git','rev-parse','HEAD:apps/mobile'],cwd=ROOT,seconds=5,maximum=1024,check=True)
    p.require(result.stdout.strip()==APP_TREE and p.DEFINES==[
        '--dart-define=WAINEK_DEV_MODE=true','--dart-define=WAINEK_REPOSITORY=fake'],'asc_reviewed_app_tree')
    return number


def build_state(number,key,pins):
    p.require(number=='1','asc_reviewed_build')
    path=a.request_path(number)
    summary=a.project(a.get_builds(path,a.token(path,key,pins)),number)
    p.require(summary['found'] and summary['build']['build_id']==BUILD_ID,'asc_reviewed_build')
    state=summary['build']
    p.require(state['processing_state']=='VALID' and state['audience']=='INTERNAL_ONLY' and not state['expired'],'asc_reviewed_build')
    p.require(state['uses_non_exempt_encryption'] in (None,False),'asc_declaration_conflict')
    return summary


def patch_token(path,key,pins):
    p.require(path==BUILD_PATH,'asc_reviewed_build')
    now=int(time.time());header={'alg':'ES256','kid':pins['asc_key_id'],'typ':'JWT'}
    claims={'iss':pins['asc_issuer_id'],'iat':now,'exp':now+120,'aud':'appstoreconnect-v1','scope':['PATCH '+BUILD_PATH]}
    message=a.b64(json.dumps(header,separators=(',',':')).encode())+'.'+a.b64(json.dumps(claims,separators=(',',':')).encode())
    return message+'.'+a.b64(a.sign_message(message,key))


def group_observation(payload):
    p.require(type(payload) is dict and type(payload.get('data')) is list and len(payload['data'])<=100,'asc_response')
    groups=[];external=0
    for row in payload['data']:
        p.require(type(row) is dict and row.get('type')=='betaGroups' and type(row.get('attributes')) is dict,'asc_response')
        values=row['attributes'];internal=values.get('isInternalGroup')
        p.require(type(internal) is bool,'asc_response')
        if not internal:external+=1;continue
        identifier=row.get('id')
        p.require(type(identifier) is str and re.fullmatch('[a-fA-F0-9]{8}(?:-[a-fA-F0-9]{4}){3}-[a-fA-F0-9]{12}',identifier),'asc_response')
        name=values.get('name')
        group={'group_id':identifier,'name_class':{'App Store Connect Users':'DEFAULT','wainek Internal':'WAINEK_INTERNAL'}.get(name,'OTHER') if type(name) is str else 'OTHER'}
        for source,target in (('publicLinkEnabled','public_link_enabled'),('hasAccessToAllBuilds','all_builds')):
            value=values.get(source);p.require(value is None or type(value) is bool,'asc_response');group[target]=value
        groups.append(group)
    return {'event':'ASC_INTERNAL_GROUPS','app_id':p.ASC_APP_ID,'internal_groups':groups,'external_group_count':external}


def complete(number,key,pins):
    before=build_state(number,key,pins);state=before['build']
    if state['uses_non_exempt_encryption'] is None:
        p.require(state['internal_state']=='MISSING_EXPORT_COMPLIANCE','asc_declaration_conflict')
        body={'data':{'type':'builds','id':BUILD_ID,'attributes':{'usesNonExemptEncryption':False}}}
        request=urllib.request.Request('https://api.appstoreconnect.apple.com'+BUILD_PATH,
            headers={'Authorization':'Bearer '+patch_token(BUILD_PATH,key,pins),'Content-Type':'application/json','Accept':'application/json'},
            data=json.dumps(body,separators=(',',':')).encode(),method='PATCH')
        # No automatic retry after a write. A later invocation reads first.
        result=a.json_request(request)
        data=result.get('data') if type(result) is dict else None
        p.require(type(data) is dict and data.get('type')=='builds' and data.get('id')==BUILD_ID
            and type(data.get('attributes')) is dict and data['attributes'].get('usesNonExemptEncryption') is False,'asc_patch_ambiguous')
    after=build_state(number,key,pins)
    p.require(after['build']['uses_non_exempt_encryption'] is False,'asc_patch_ambiguous')
    print(json.dumps({'event':'ASC_INTERNAL_METADATA','build_id':BUILD_ID,'build_source':BUILD_SOURCE,
        'reviewed_app_tree':APP_TREE,'declaration_uses_non_exempt_encryption':False,
        'other_builds_modified':False,'groups_modified':False,'external_distribution':False}),flush=True)
    print(json.dumps(after),flush=True)
    if not after['build']['internal_available']:
        path=a.group_request_path()
        print(json.dumps(group_observation(a.get_builds(path,a.token(path,key,pins)))),flush=True)


def main(argv=None):
    parser=argparse.ArgumentParser();mode=parser.add_mutually_exclusive_group(required=True)
    for flag in ('check','complete','cleanup'):mode.add_argument('--'+flag,action='store_true')
    args=parser.parse_args(argv)
    try:
        if args.cleanup:return a.main(['--cleanup'])
        pins=json.loads(q.PIN_FILE.read_text());q.validate_reviewed_pins(pins);validate_workflow()
        if args.check:
            print(json.dumps({'status':'ASC_ONE_BUILD_METADATA_CONTRACT_PASS','build_id':BUILD_ID,'credentials_read':False}));return 0
        number=preflight(os.environ);os.umask(0o077);a.owned_path(a.WORK)
        p.require(not a.WORK.exists(),'asc_path');a.WORK.parent.mkdir(mode=0o700,exist_ok=True);a.WORK.mkdir(mode=0o700)
        try:
            try:key=base64.b64decode(os.environ[q.UPLOAD_SECRETS[0]],validate=True)
            except (ValueError,KeyError):raise p.PolicyError('asc_key_shape') from None
            p.require(0<len(key)<=16384 and key.strip().startswith(b'-----BEGIN '+b'PRIVATE KEY-----'),'asc_key_shape')
            complete(number,a.write('private.p8',key),pins)
        finally:a.cleanup()
        return 0
    except BaseException as error:
        reason=error.args[0] if isinstance(error,p.PolicyError) and error.args else None
        print(json.dumps({'status':'ASC_INTERNAL_FAILED_CLOSED','safe_reason':reason if type(reason) is str and reason in REASONS else 'OTHER','raw_output':'withheld'}),flush=True);return 1


if __name__=='__main__':raise SystemExit(main())

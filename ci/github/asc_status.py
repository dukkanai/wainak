#!/usr/bin/env python3
"""Owner-protected App Store Connect GET status, fixed app and scoped 120s JWT.

Never logs keys, JWTs, captured command output, HTTP bodies or server errors.
"""
import argparse
import base64
import json
import os
from pathlib import Path
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from ci.github import internal_policy as q
from ci.testflight import policy as p
from scripts.ci_process import run_bounded

WORK=ROOT/'.ci-github/asc-status'
FILES=('private.p8','message','signature.der')
STATES={'PROCESSING','FAILED','INVALID','VALID'}
BETA_STATES={'PROCESSING','PROCESSING_EXCEPTION','MISSING_EXPORT_COMPLIANCE','READY_FOR_BETA_TESTING',
             'IN_BETA_TESTING','EXPIRED','IN_EXPORT_COMPLIANCE_REVIEW'}
AUDIENCES={'INTERNAL_ONLY','APP_STORE_ELIGIBLE'}
REASONS={'asc_context','asc_path','asc_key_shape','asc_signature','asc_response','asc_http',
         'asc_unauthorized','asc_forbidden','asc_network','asc_cleanup','asc_source',
         'asc_bad_request','asc_not_found','asc_rate_limited','asc_server_error'}


def require(ok,reason):p.require(ok,reason)
def b64(data):return base64.urlsafe_b64encode(data).rstrip(b'=').decode('ascii')


def job():
    return {'name':'Read internal Apple build status — protected environment',
        'if':"github.event_name == 'workflow_dispatch' && inputs.target == 'asc-status' && github.repository == 'dukkanai/wainak' && github.event.repository.private == false && github.ref == 'refs/heads/"+q.BRANCH+"' && inputs.expected_sha == github.sha && github.run_attempt == 1",
        'runs-on':'ubuntu-24.04','timeout-minutes':8,'permissions':{'contents':'read'},'environment':q.ENVIRONMENT,
        'concurrency':{'group':'wainek-asc-status','cancel-in-progress':False},
        'env':{'WAINEK_REPOSITORY_VISIBILITY':'${{ github.event.repository.visibility }}',
               'WAINEK_EXPECTED_SHA':'${{ inputs.expected_sha }}','WAINEK_BUILD_NUMBER':'${{ inputs.build_number }}'},
        'steps':[{'uses':q.CHECKOUT,'with':{'persist-credentials':False,'ref':'${{ github.sha }}'}},
            {'uses':q.PYTHON,'with':{'python-version':'3.12.7'}},
            {'name':'Check fixed read-only Apple status contract','run':'python3 ci/github/asc_status.py --check'},
            {'name':'Read fixed application build state','env':{q.UPLOAD_SECRETS[0]:'${{ secrets.'+q.UPLOAD_SECRETS[0]+' }}'},
             'run':'python3 ci/github/asc_status.py --read'},
            {'name':'Remove owned status key material','if':'${{ always() }}','run':'python3 ci/github/asc_status.py --cleanup'}]}


def validate_workflow():
    source=(ROOT/'.github/workflows/ci.yml').read_text();q.validate_active_workflow(source)
    lines=[x for x in source.splitlines() if x.startswith('  asc-status: ')]
    require(len(lines)==1 and json.loads(lines[0].split(': ',1)[1])==job(),'asc_context')


def candidate_workflow(source):
    old="inputs.target != 'mac-unsigned' && inputs.target != 'mac-internal'"
    require('asc-status' not in source and source.count(old)==9 and
        source.count('options: [ci, mac-unsigned, mac-internal]')==1,'asc_context')
    source=source.replace('options: [ci, mac-unsigned, mac-internal]','options: [ci, mac-unsigned, mac-internal, asc-status]')
    source=source.replace(old,old+" && inputs.target != 'asc-status'")
    return source+'\n  asc-status: '+json.dumps(job(),ensure_ascii=False)+'\n'


def preflight(env):
    require(sys.platform=='linux' and env.get('GITHUB_REPOSITORY')=='dukkanai/wainak' and
        env.get('GITHUB_EVENT_NAME')=='workflow_dispatch' and env.get('GITHUB_REF')=='refs/heads/'+q.BRANCH and
        env.get('WAINEK_REPOSITORY_VISIBILITY')=='public' and env.get('GITHUB_RUN_ATTEMPT')=='1' and
        Path(env.get('GITHUB_WORKSPACE','/nonexistent')).resolve()==ROOT,'asc_context')
    sha=env.get('GITHUB_SHA','');require(re.fullmatch('[a-f0-9]{40}',sha) and env.get('WAINEK_EXPECTED_SHA')==sha,'asc_context')
    number=env.get('WAINEK_BUILD_NUMBER','');require(type(number) is str and re.fullmatch('[1-9][0-9]{0,8}',number),'asc_context')
    for args,expected in ((['git','rev-parse','HEAD'],sha),(['git','status','--porcelain'],'')):
        result=run_bounded(args,cwd=ROOT,check=True,seconds=5,maximum=65536)
        require(result.stdout.strip()==expected,'asc_source')
    return number


def owned_path(path):
    require(path.is_relative_to(WORK) and not any(x.is_symlink() for x in (path,*path.parents) if x.is_relative_to(ROOT)), 'asc_path')


def write(name,data):
    path=WORK/name;owned_path(path)
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'wb') as stream:stream.write(data)
    return path


def der_signature(data):
    # OpenSSL ES256 DER -> JWT's fixed r||s encoding; reject noncanonical input.
    require(type(data) is bytes and 8<=len(data)<=72 and data[0]==0x30 and data[1]==len(data)-2,'asc_signature')
    parts=[];offset=2;order=0xffffffff00000000ffffffffffffffffbce6faada7179e84f3b9cac2fc632551
    for _ in range(2):
        require(offset+2<=len(data) and data[offset]==2,'asc_signature');size=data[offset+1];offset+=2
        require(1<=size<=33 and offset+size<=len(data),'asc_signature');value=data[offset:offset+size];offset+=size
        require(not value[0]&0x80 and (size==1 or value[0]!=0 or value[1]&0x80),'asc_signature')
        number=int.from_bytes(value,'big');require(0<number<order,'asc_signature');parts.append(number.to_bytes(32,'big'))
    require(offset==len(data),'asc_signature');return b''.join(parts)


def request_path(number):
    query=urllib.parse.urlencode({'filter[app]':p.ASC_APP_ID,'filter[version]':number,
        'include':'app,preReleaseVersion,buildBetaDetail,betaGroups','limit':'10'})
    return '/v1/builds?'+query


def token(path,key,pins):
    now=int(time.time())
    header={'alg':'ES256','kid':pins['asc_key_id'],'typ':'JWT'}
    claims={'iss':pins['asc_issuer_id'],'iat':now,'exp':now+120,'aud':'appstoreconnect-v1','scope':['GET '+path]}
    message=b64(json.dumps(header,separators=(',',':')).encode())+'.'+b64(json.dumps(claims,separators=(',',':')).encode())
    for name in ('message','signature.der'):
        target=WORK/name;owned_path(target)
        if target.exists():target.unlink()
    input_file=write('message',message.encode());signature=WORK/'signature.der'
    run_bounded(['/usr/bin/openssl','dgst','-sha256','-sign',key,'-out',signature,input_file],cwd=WORK,
        env={'PATH':'/usr/bin:/bin','HOME':str(WORK)},seconds=15,maximum=16384,check=True)
    owned_path(signature);require(signature.is_file() and signature.stat().st_size<=72,'asc_signature')
    return message+'.'+b64(der_signature(signature.read_bytes()))


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None


def get_builds(path,jwt):
    require(path.startswith('/v1/builds?') and '\n' not in path,'asc_context')
    request=urllib.request.Request('https://api.appstoreconnect.apple.com'+path,headers={'Authorization':'Bearer '+jwt,'Accept':'application/json'},method='GET')
    try:
        with urllib.request.build_opener(NoRedirect).open(request,timeout=20) as response:
            require(response.status==200,'asc_http');data=response.read(512*1024+1)
    except urllib.error.HTTPError as error:
        reason={400:'asc_bad_request',401:'asc_unauthorized',403:'asc_forbidden',404:'asc_not_found',
                429:'asc_rate_limited'}.get(error.code,'asc_server_error' if 500<=error.code<600 else 'asc_http')
        error.close()
        raise p.PolicyError(reason) from None
    except (urllib.error.URLError,TimeoutError):raise p.PolicyError('asc_network') from None
    require(len(data)<=512*1024,'asc_response')
    def pairs(items):
        result={}
        for key,value in items:
            require(key not in result,'asc_response');result[key]=value
        return result
    def constant(_):raise p.PolicyError('asc_response')
    try:return json.loads(data,object_pairs_hook=pairs,parse_constant=constant)
    except (ValueError,UnicodeError,RecursionError):raise p.PolicyError('asc_response') from None


def project(payload,number):
    require(type(payload) is dict and type(payload.get('data')) is list and len(payload['data'])<=10,'asc_response')
    included=payload.get('included',[]);require(type(included) is list and len(included)<=128 and all(type(x) is dict for x in included),'asc_response')
    require(all(type(x.get('attributes',{})) is dict for x in included),'asc_response')
    related={(x.get('type'),x.get('id')):x for x in included if type(x.get('type')) is str and type(x.get('id')) is str}
    found=[]
    def relation(relationships,name):
        value=relationships.get(name,{})
        require(type(value) is dict,'asc_response')
        data=value.get('data',{})
        require(type(data) is dict,'asc_response')
        return data
    for build in payload['data']:
        require(type(build) is dict and build.get('type')=='builds','asc_response')
        attributes=build.get('attributes',{});relationships=build.get('relationships',{})
        require(type(attributes) is dict and type(relationships) is dict and attributes.get('version')==number,'asc_response')
        app=relation(relationships,'app')
        require(type(app) is dict and app.get('type')=='apps' and app.get('id')==p.ASC_APP_ID,'asc_response')
        prerelease=relation(relationships,'preReleaseVersion')
        require(prerelease.get('id') is None or type(prerelease['id']) is str,'asc_response')
        version=related.get(('preReleaseVersions',prerelease.get('id')),{}).get('attributes',{})
        if version.get('version')!='0.1.0' or version.get('platform')!='IOS':continue
        identifier=build.get('id');require(type(identifier) is str and re.fullmatch('[A-Fa-f0-9]{8}(?:-[A-Fa-f0-9]{4}){3}-[A-Fa-f0-9]{12}',identifier),'asc_response')
        processing=attributes.get('processingState');audience=attributes.get('buildAudienceType')
        beta=relation(relationships,'buildBetaDetail')
        require(beta.get('id') is None or type(beta['id']) is str,'asc_response')
        internal=related.get(('buildBetaDetails',beta.get('id')),{}).get('attributes',{}).get('internalBuildState')
        groups=relationships.get('betaGroups',{}).get('data',[]);require(type(groups) is list and len(groups)<=100,'asc_response')
        count=0
        for group in groups:
            require(type(group) is dict and type(group.get('id')) is str,'asc_response')
            if related.get(('betaGroups',group['id']),{}).get('attributes',{}).get('isInternalGroup') is True:count+=1
        encryption=attributes.get('usesNonExemptEncryption');require(encryption is None or type(encryption) is bool,'asc_response')
        expired=attributes.get('expired');require(type(expired) is bool,'asc_response')
        found.append({'build_id':identifier,'processing_state':processing if type(processing) is str and processing in STATES else 'OTHER',
            'audience':audience if type(audience) is str and audience in AUDIENCES else 'OTHER',
            'internal_state':internal if type(internal) is str and internal in BETA_STATES else 'OTHER',
            'internal_groups':count,'expired':expired,'uses_non_exempt_encryption':encryption,
            'internal_available':processing=='VALID' and audience=='INTERNAL_ONLY' and internal=='IN_BETA_TESTING' and count>0 and not expired})
    require(len(found)<=1,'asc_response')
    return {'event':'ASC_BUILD_STATUS','app_id':p.ASC_APP_ID,'build_number':number,'version':'0.1.0','found':bool(found),'build':found[0] if found else None}


def cleanup():
    if not os.path.lexists(WORK):return
    owned_path(WORK);require(WORK.is_dir() and WORK.stat().st_uid==os.getuid(),'asc_cleanup')
    for name in FILES:
        path=WORK/name;owned_path(path)
        if path.exists():require(path.is_file() and path.stat().st_uid==os.getuid(),'asc_cleanup');path.unlink()
    require(not list(WORK.iterdir()),'asc_cleanup');WORK.rmdir()


def main(argv=None):
    parser=argparse.ArgumentParser();mode=parser.add_mutually_exclusive_group(required=True)
    for flag in ('check','read','cleanup'):mode.add_argument('--'+flag,action='store_true')
    args=parser.parse_args(argv)
    try:
        if args.cleanup:
            require(os.environ.get('GITHUB_REPOSITORY')=='dukkanai/wainak' and Path(os.environ.get('GITHUB_WORKSPACE','/nonexistent')).resolve()==ROOT,'asc_context')
            cleanup();return 0
        pins=json.loads(q.PIN_FILE.read_text());q.validate_reviewed_pins(pins);validate_workflow()
        if args.check:print(json.dumps({'status':'ASC_READ_ONLY_CONTRACT_PASS','credentials_read':False}));return 0
        number=preflight(os.environ);os.umask(0o077);owned_path(WORK)
        require(not WORK.exists(),'asc_path');WORK.parent.mkdir(mode=0o700,exist_ok=True);WORK.mkdir(mode=0o700)
        try:
            try:key=base64.b64decode(os.environ[q.UPLOAD_SECRETS[0]],validate=True)
            except (ValueError,KeyError):raise p.PolicyError('asc_key_shape') from None
            require(0<len(key)<=16384 and key.strip().startswith(b'-----BEGIN '+b'PRIVATE KEY-----'),'asc_key_shape')
            key_file=write('private.p8',key);path=request_path(number)
            summary=project(get_builds(path,token(path,key_file,pins)),number);print(json.dumps(summary),flush=True)
        finally:cleanup()
        return 0
    except BaseException as error:
        reason=error.args[0] if isinstance(error,p.PolicyError) and error.args else None
        print(json.dumps({'status':'ASC_READ_FAILED_CLOSED','safe_reason':reason if type(reason) is str and reason in REASONS else 'OTHER','raw_output':'withheld'}),flush=True);return 1


if __name__=='__main__':raise SystemExit(main())

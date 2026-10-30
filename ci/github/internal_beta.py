#!/usr/bin/env python3
"""Owner-protected internal group delivery. No external testers or public links."""
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
from ci.github import asc_status as a, internal_policy as q
from ci.testflight import policy as p

BUILD_ID='f6880458-eda7-4720-8576-0b87856e767e'  # Apple readback: run 41102022775, build2.
BUILD_SOURCE='2ea5df3fa3f440f4c38d6a9265942ca69a577836'
APP_TREE='afe2a6e34a0133e81781095b04bb1bb78c247f21'
GROUP_NAME='wainek Internal'
TARGET='beta-internal'
OPERATIONS=frozenset({'OWNER_READ','GROUPS_READ','GROUP_CREATE','TESTER_READ','TESTER_CREATE',
    'GROUP_TESTERS_READ','GROUP_BUILDS_READ','ADD_OWNER','ADD_BUILD'})
REASONS=a.REASONS|{'beta_owner','beta_context','beta_plan','beta_app_tree','beta_group','beta_collision',
    'beta_tester','beta_build','beta_response','beta_http','beta_network','beta_membership','beta_deadline'}


def guid(value):
    p.require(type(value) is str and re.fullmatch('[a-fA-F0-9]{8}(?:-[a-fA-F0-9]{4}){3}-[a-fA-F0-9]{12}',value),'beta_response')
    return value


def email(value):
    p.require(type(value) is str and len(value)<=254 and re.fullmatch(
        r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]{1,64}@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+",value),'beta_owner')
    return value.casefold()


def rows(payload,kind,maximum):
    p.require(type(payload) is dict and type(payload.get('data')) is list and len(payload['data'])<=maximum,'beta_response')
    links=payload.get('links',{});p.require(type(links) is dict and links.get('next') is None,'beta_response')
    for row in payload['data']:
        p.require(type(row) is dict and row.get('type')==kind and type(row.get('attributes',{})) is dict,'beta_response')
        if kind=='users':
            # Apple's user ID is opaque and never used in a mutation or log.
            p.require(type(row.get('id')) is str and 0<len(row['id'])<=256,'beta_response')
        else:guid(row.get('id'))
    return payload['data']


def select_owner(payload):
    values=rows(payload,'users',2);p.require(len(values)==1,'beta_owner')
    roles=values[0]['attributes'].get('roles')
    p.require(type(roles) is list and 'ACCOUNT_HOLDER' in roles and all(type(x) is str for x in roles),'beta_owner')
    return email(values[0]['attributes'].get('username'))


def select_group(payload):
    values=rows(payload,'betaGroups',100)
    matches=[row for row in values if row['attributes'].get('name')==GROUP_NAME]
    p.require(len(matches)<=1,'beta_collision')
    if not matches:return None
    row=matches[0];attributes=row['attributes']
    # Apple returns null for public-link fields that do not apply to internal groups.
    p.require(attributes.get('isInternalGroup') is True and 'publicLinkEnabled' in attributes
        and (attributes['publicLinkEnabled'] is False or attributes['publicLinkEnabled'] is None)
        and all(key in attributes and attributes[key] is None for key in ('publicLink','publicLinkId'))
        and attributes.get('hasAccessToAllBuilds') is False,'beta_group')
    return guid(row['id'])


def select_tester(payload,owner):
    values=rows(payload,'betaTesters',2);p.require(len(values)<=1,'beta_tester')
    if not values:return None
    row=values[0];attributes=row['attributes']
    p.require(email(attributes.get('email'))==owner and attributes.get('inviteType')=='EMAIL','beta_tester')
    p.require(attributes.get('state') in {'NOT_INVITED','INVITED','ACCEPTED','INSTALLED','REVOKED'},'beta_tester')
    return guid(row['id'])


def created_id(payload,kind):
    row=payload.get('data') if type(payload) is dict else None
    p.require(type(row) is dict and row.get('type')==kind,'beta_response')
    return guid(row.get('id'))


class Client:
    def __init__(self,key,pins):
        self.key=key;self.pins=pins;self.owner=None;self.group=None;self.tester=None;self.verified_build=None
        self.deadline=time.monotonic()+360

    def spec(self,operation):
        p.require(type(operation) is str and operation in OPERATIONS,'beta_context')
        if operation in {'GROUP_CREATE','TESTER_CREATE','ADD_OWNER','ADD_BUILD'}:
            p.require(BUILD_ID is not None and self.verified_build==BUILD_ID,'beta_plan')
        def query(values):return '?'+urllib.parse.urlencode(values)
        if operation=='OWNER_READ':
            return 'GET','/v1/users'+query({'filter[roles]':'ACCOUNT_HOLDER','fields[users]':'username,roles','limit':'2'}),None,200
        if operation=='GROUPS_READ':
            return 'GET',a.group_request_path(),None,200
        p.require(self.owner is not None and email(self.owner)==self.owner,'beta_owner')
        if operation=='GROUP_CREATE':
            p.require(self.group is None,'beta_group')
            return 'POST','/v1/betaGroups',{'data':{'type':'betaGroups','attributes':{
                'name':GROUP_NAME,'isInternalGroup':True,'publicLinkEnabled':False,'hasAccessToAllBuilds':False},
                'relationships':{'app':{'data':{'type':'apps','id':p.ASC_APP_ID}}}}},201
        group=guid(self.group)
        if operation=='TESTER_READ':
            return 'GET','/v1/betaTesters'+query({'filter[email]':self.owner,'fields[betaTesters]':'email,inviteType,state','limit':'2'}),None,200
        if operation=='TESTER_CREATE':
            p.require(self.tester is None,'beta_tester')
            return 'POST','/v1/betaTesters',{'data':{'type':'betaTesters','attributes':{'email':self.owner},
                'relationships':{'betaGroups':{'data':[{'type':'betaGroups','id':group}]}}}},201
        if operation=='GROUP_TESTERS_READ':
            return 'GET','/v1/betaGroups/'+group+'/betaTesters'+query({'fields[betaTesters]':'email,inviteType,state','limit':'100'}),None,200
        if operation=='GROUP_BUILDS_READ':return 'GET','/v1/betaGroups/'+group+'/relationships/builds',None,200
        tester=guid(self.tester)
        if operation=='ADD_OWNER':
            return 'POST','/v1/betaGroups/'+group+'/relationships/betaTesters',{'data':[{'type':'betaTesters','id':tester}]},204
        p.require(operation=='ADD_BUILD' and BUILD_ID is not None,'beta_plan')
        return 'POST','/v1/betaGroups/'+group+'/relationships/builds',{'data':[{'type':'builds','id':guid(BUILD_ID)}]},204

    def request(self,operation):
        p.require(time.monotonic()<self.deadline,'beta_deadline')
        method,path,body,expected=self.spec(operation)
        now=int(time.time());header={'alg':'ES256','kid':self.pins['asc_key_id'],'typ':'JWT'}
        p.require(method in {'GET','POST'},'beta_context')
        # Apple supports scope entries for GET only. Writes use its documented
        # unscoped form, existing key role, a 60s lifetime and spec's fixed operations.
        claims={'iss':self.pins['asc_issuer_id'],'iat':now,'exp':now+(120 if method=='GET' else 60),'aud':'appstoreconnect-v1'}
        if method=='GET':claims['scope']=['GET '+path]
        message=a.b64(json.dumps(header,separators=(',',':')).encode())+'.'+a.b64(json.dumps(claims,separators=(',',':')).encode())
        jwt=message+'.'+a.b64(a.sign_message(message,self.key))
        p.require(time.monotonic()<self.deadline,'beta_deadline')
        request=urllib.request.Request('https://api.appstoreconnect.apple.com'+path,
            headers={'Authorization':'Bearer '+jwt,'Accept':'application/json',**({'Content-Type':'application/json'} if body is not None else {})},
            data=json.dumps(body,separators=(',',':')).encode() if body is not None else None,method=method)
        status=None;outcome='FAILED';summary={'count':None,'codes':[],'categories':['UNCLASSIFIED']}
        try:
            try:
                with urllib.request.build_opener(a.NoRedirect).open(request,timeout=min(20,max(.1,self.deadline-time.monotonic()))) as response:
                    status=response.status;p.require(status==expected,'beta_http');data=response.read(512*1024+1)
            except urllib.error.HTTPError as error:
                status=error.code
                try:summary=a.http_error_summary(error.read(16385))
                except Exception:pass
                finally:error.close()
                reason={400:'asc_bad_request',401:'asc_unauthorized',403:'asc_forbidden',404:'asc_not_found',
                    405:'asc_method_not_allowed',409:'asc_conflict',422:'asc_unprocessable',429:'asc_rate_limited'}.get(status,'beta_http')
                raise p.PolicyError(reason) from None
            except (urllib.error.URLError,TimeoutError):raise p.PolicyError('beta_network') from None
            p.require(len(data)<=512*1024,'beta_response')
            p.require(time.monotonic()<self.deadline,'beta_deadline')
            result=a.decode_response(data) if expected!=204 else None
            if expected==204:p.require(not data,'beta_response')
            outcome='PASS';summary={'count':0,'codes':[],'categories':[]};return result
        finally:
            print(json.dumps({'event':'BETA_DELIVERY_COMMAND','operation':operation,'method':method,'outcome':outcome,
                'status_code':status if type(status) is int and status in {200,201,204,400,401,403,404,405,409,422,429,500,502,503} else 'OTHER',
                'error_summary':summary}),flush=True)


def inspect(client):
    client.owner=select_owner(client.request('OWNER_READ'))
    client.group=select_group(client.request('GROUPS_READ'))
    print(json.dumps({'event':'BETA_OWNER_INSPECTION','account_holder_verified':True,
        'reserved_group_present':client.group is not None,'email_printed':False,'writes_performed':False}),flush=True)


def read_build(client):
    path=a.request_path('2');summary=a.project(a.get_builds(path,a.token(path,client.key,client.pins)),'2')
    return summary


def verify_build(client):
    p.require(BUILD_ID is not None,'beta_plan');guid(BUILD_ID)
    summary=read_build(client)
    p.require(summary['found'],'beta_build');value=summary['build']
    p.require(value['build_id']==BUILD_ID and value['processing_state']=='VALID' and value['audience']=='INTERNAL_ONLY'
        and value['uses_non_exempt_encryption'] is False and not value['expired'],'beta_build')
    client.verified_build=BUILD_ID
    return summary


def complete(client):
    verify_build(client);inspect(client)
    if client.group is None:
        client.group=created_id(client.request('GROUP_CREATE'),'betaGroups')
        p.require(select_group(client.request('GROUPS_READ'))==client.group,'beta_group')
    members=rows(client.request('GROUP_TESTERS_READ'),'betaTesters',100)
    p.require(all(email(row['attributes'].get('email'))==client.owner for row in members),'beta_membership')
    client.tester=select_tester(client.request('TESTER_READ'),client.owner)
    if client.tester is None:
        client.tester=created_id(client.request('TESTER_CREATE'),'betaTesters')
        p.require(select_tester(client.request('TESTER_READ'),client.owner)==client.tester,'beta_tester')
    members=rows(client.request('GROUP_TESTERS_READ'),'betaTesters',100)
    p.require(all(email(row['attributes'].get('email'))==client.owner for row in members),'beta_membership')
    if not any(row['id']==client.tester for row in members):client.request('ADD_OWNER')
    members=rows(client.request('GROUP_TESTERS_READ'),'betaTesters',100)
    p.require(len(members)==1 and members[0]['id']==client.tester and email(members[0]['attributes'].get('email'))==client.owner,'beta_membership')
    builds=rows(client.request('GROUP_BUILDS_READ'),'builds',100)
    p.require(all(row['id']==BUILD_ID for row in builds),'beta_collision')
    if not builds:
        verify_build(client);client.request('ADD_BUILD')
    builds=rows(client.request('GROUP_BUILDS_READ'),'builds',100)
    p.require(len(builds)==1 and builds[0]['id']==BUILD_ID,'beta_membership')
    summary=verify_build(client)
    members=rows(client.request('GROUP_TESTERS_READ'),'betaTesters',100)
    p.require(len(members)==1 and members[0]['id']==client.tester and email(members[0]['attributes'].get('email'))==client.owner,'beta_membership')
    print(json.dumps({'event':'BETA_DELIVERY_VERIFIED','build_id':BUILD_ID,'build_source':BUILD_SOURCE,
        'group_id':client.group,'owner_only':True,'owner_tester_state':members[0]['attributes'].get('state')
        if members[0]['attributes'].get('state') in {'NOT_INVITED','INVITED','ACCEPTED','INSTALLED','REVOKED'} else 'OTHER',
        'external_distribution':False,'public_link':False,'automatic_write_retry':False,
        'internal_availability_verified':summary['build']['internal_available']}),flush=True)
    print(json.dumps(summary),flush=True)


def job():
    value=a.job();mode='--inspect' if BUILD_ID is None else '--complete'
    value['name']='Owner-only internal TestFlight group '+('inspection' if BUILD_ID is None else 'delivery')
    value['if']=value['if'].replace("inputs.target == 'asc-status'","inputs.target == '"+TARGET+"'")+" && github.actor == 'dukkanai' && github.actor_id == '255427171'"
    value['concurrency']={'group':'wainek-internal-testflight','cancel-in-progress':False}
    value['env']['WAINEK_BETA_TARGET']=TARGET
    value['steps'][2]={'name':'Check reviewed owner-only beta plan','run':'python3 ci/github/internal_beta.py --check'}
    value['steps'][3]={'name':'Inspect owner only' if BUILD_ID is None else 'Deliver reviewed build2 to owner internal group',
        'env':{q.UPLOAD_SECRETS[0]:'${{ secrets.'+q.UPLOAD_SECRETS[0]+' }}'},'run':'python3 ci/github/internal_beta.py '+mode}
    value['steps'][4]={'name':'Remove owned beta API files','if':'${{ always() }}','run':'python3 ci/github/internal_beta.py --cleanup'}
    return value


def preflight(env):
    number=a.preflight(env)
    p.require(number=='2' and env.get('GITHUB_ACTOR')==q.OWNER_LOGIN and env.get('GITHUB_ACTOR_ID')==str(q.OWNER_ID)
        and env.get('WAINEK_BETA_TARGET')==TARGET,'beta_context')
    p.require(env.get('RUNNER_DEBUG')!='1' and env.get('ACTIONS_STEP_DEBUG','').lower()!='true'
        and env.get('ACTIONS_RUNNER_DEBUG','').lower()!='true','beta_context')
    result=a.run_bounded(['/usr/bin/git','rev-parse','HEAD:apps/mobile'],cwd=ROOT,env=a.git_environment(),seconds=5,maximum=1024,check=True)
    p.require(result.stdout.strip()==APP_TREE and p.DEFINES==[
        '--dart-define=WAINEK_DEV_MODE=true','--dart-define=WAINEK_REPOSITORY=fake'],'beta_app_tree')


def main(argv=None):
    parser=argparse.ArgumentParser();mode=parser.add_mutually_exclusive_group(required=True)
    for flag in ('check','inspect','complete','cleanup'):mode.add_argument('--'+flag,action='store_true')
    args=parser.parse_args(argv)
    try:
        if args.cleanup:return a.main(['--cleanup'])
        pins=json.loads(q.PIN_FILE.read_text());q.validate_reviewed_pins(pins)
        source=(ROOT/'.github/workflows/ci.yml').read_text();q.validate_active_workflow(source)
        match=[x for x in source.splitlines() if x.startswith('  '+TARGET+': ')]
        p.require(len(match)==1 and json.loads(match[0].split(': ',1)[1])==job(),'beta_context')
        if args.check:
            print(json.dumps({'status':'BETA_PLAN_CHECK_PASS','writes_enabled':BUILD_ID is not None,'credentials_read':False}));return 0
        if args.complete:p.require(BUILD_ID is not None,'beta_plan')
        preflight(os.environ);os.umask(0o077);a.owned_path(a.WORK)
        p.require(not a.WORK.exists(),'asc_path');a.WORK.parent.mkdir(mode=0o700,exist_ok=True);a.WORK.mkdir(mode=0o700)
        try:
            try:key=base64.b64decode(os.environ[q.UPLOAD_SECRETS[0]],validate=True)
            except (KeyError,ValueError):raise p.PolicyError('asc_key_shape') from None
            p.require(0<len(key)<=16384 and key.strip().startswith(b'-----BEGIN '+b'PRIVATE KEY-----'),'asc_key_shape')
            client=Client(a.write('private.p8',key),pins)
            if args.complete:complete(client)
            else:
                print(json.dumps(read_build(client)),flush=True)
                inspect(client)
        finally:a.cleanup()
        return 0
    except BaseException as error:
        reason=error.args[0] if isinstance(error,p.PolicyError) and error.args else None
        print(json.dumps({'status':'BETA_DELIVERY_FAILED_CLOSED','safe_reason':reason if type(reason) is str and reason in REASONS else 'OTHER','raw_output':'withheld'}),flush=True);return 1


if __name__=='__main__':raise SystemExit(main())

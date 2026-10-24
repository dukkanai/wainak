"""Run only synthetic independent checks against a byte-matched archive candidate.
Does not install, connect to providers, touch main, or publish raw test output.
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
sys.dont_write_bytecode=True
ROOT=Path(__file__).resolve().parents[2]
TOOLS=Path('/home/chatbot/wainak-dev/archive-tools-phase5-20261024')

def git(*args):return subprocess.check_output(['git','-C',str(ROOT),*args],text=True).strip()
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def archive_equal(candidate):
    paths=subprocess.check_output(['git','-C',str(ROOT),'ls-tree','-r','--name-only','-z',candidate,'archive/']).decode().split('\0')
    manifest={}
    for name in filter(None,paths):
        p=ROOT/name
        if not p.is_file() or p.is_symlink():raise RuntimeError('archive source boundary')
        expected=hashlib.sha256(subprocess.check_output(['git','-C',str(ROOT),'show',candidate+':'+name])).hexdigest()
        if sha(p)!=expected:raise RuntimeError('archive blob changed')
        manifest[name]=expected
    if len(manifest)!=24:raise RuntimeError('candidate archive scope changed')
    return manifest

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--candidate',required=True);ap.add_argument('--evidence',type=Path,required=True);ap.add_argument('--run-synthetic-archive',action='store_true');args=ap.parse_args()
    if not args.run_synthetic_archive or not re.fullmatch('[0-9a-f]{40}',args.candidate):raise RuntimeError('explicit candidate required')
    if git('status','--porcelain'):raise RuntimeError('clean QA worktree required')
    before=archive_equal(args.candidate);qa_head=git('rev-parse','HEAD')
    mem={k:int(v.split()[0]) for k,v in (l.split(':',1) for l in Path('/proc/meminfo').read_text().splitlines())}
    if mem['MemAvailable']<int(4.5*1024*1024):raise RuntimeError('insufficient resource margin')
    if Path('/sys/fs/cgroup/system.slice/onwani-server-admin.service/memory.max').read_text().strip()!='4294967296':raise RuntimeError('owner cap changed')
    if not args.evidence.is_dir() or args.evidence.is_symlink() or args.evidence.stat().st_uid!=os.getuid():raise RuntimeError('owned evidence required')
    resultfile=args.evidence/'independent-results.json'
    if resultfile.exists():raise RuntimeError('existing evidence must not be overwritten')
    spec=importlib.util.spec_from_file_location('reviewed_runner',ROOT/'archive/run_checks.py');runner=importlib.util.module_from_spec(spec);spec.loader.exec_module(runner)
    results=[]
    with tempfile.TemporaryDirectory(prefix='wainak-archive-qa-',dir=TOOLS/'tmp') as temp:
        env={'HOME':str(TOOLS/'home'),'PATH':str(TOOLS/'go/bin')+':/usr/bin:/bin','GOPATH':str(TOOLS/'gopath'),'GOCACHE':str(TOOLS/'gocache'),'GOMODCACHE':str(TOOLS/'gomodcache'),'TMPDIR':temp,'GOENV':'off','GOTOOLCHAIN':'local','GOTELEMETRY':'off','CGO_ENABLED':'0','GOFLAGS':'-p=1 -mod=readonly','GOMAXPROCS':'2','GOMEMLIMIT':'512MiB','GOPROXY':'off','GOSUMDB':'off','PYTHONDONTWRITEBYTECODE':'1'}
        go=str(TOOLS/'go/bin/go');own=ROOT/'qa/phase5_archive'
        code,out,_=runner.bounded_run([go,'list','-m','-json','wainak.local/historyarchive'],own,env)
        if code or Path(json.loads(out)['Dir']).resolve()!=(ROOT/'archive').resolve():raise RuntimeError('module provenance mismatch')
        overlay=Path(temp)/'overlay.json'
        overlay.write_text(json.dumps({'Replace':{str(ROOT/'archive/qa_independent_bound_test.go'):str(own/'bound_internal_test.go.txt')}}))
        commands=[
            ('independent_api',[go,'test','-json','-count=1','-parallel=1','-timeout=90s','./...'],own),
            ('independent_bound',[go,'test','-json','-count=1','-overlay='+str(overlay),'-run=^TestQABoundedCopyProbe$','.'],ROOT/'archive'),
            ('independent_lifecycle',['python3',str(own/'test_runner_independent.py')],ROOT),
            ('offline_provenance',['/home/chatbot/wainak-dev/auth-tools-phase2/venv/bin/python','-I',str(own/'verify_provenance.py')],ROOT),
            ('qa_vet',[go,'vet','./...'],own),
            ('publication',['python3','scripts/check_publication.py'],ROOT),
        ]
        for label,command,cwd in commands:
            code,out,seconds=runner.bounded_run(command,cwd,env,timeout=180)
            item={'gate':label,'exit_code':code,'seconds':seconds}
            if label in ('independent_api','independent_bound'):
                events=[]
                for line in out.splitlines():
                    try:event=json.loads(line)
                    except ValueError:continue
                    if event.get('Action') in ('pass','fail','skip') and event.get('Test'):
                        name=event['Test'];events.append({'action':event['Action'],'test':name if re.fullmatch('[A-Za-z0-9_./-]{1,200}',name) else 'nonstandard_name'})
                item['tests']=events
            elif label=='offline_provenance' and not code:item['details']=json.loads(out)
            elif label=='independent_lifecycle':
                item['expected_cases']=4;item['summary_ok']=b'Ran 4 tests' in out and b'\nOK\n' in out
                if not item['summary_ok']:code=1;item['exit_code']=1
            results.append(item)
            print(json.dumps(item,sort_keys=True),flush=True)
            if code:
                # Output stays in RAM; fixed failure category is sufficient for
                # deciding whether a separately bounded diagnostic is needed.
                resultfile.write_text(json.dumps({'status':'FAIL','candidate':args.candidate,'qa_head':qa_head,'results':results},indent=2)+'\n')
                raise RuntimeError('independent gate incomplete; raw output withheld')
    if Path(temp).exists():raise RuntimeError('owned temp remains')
    if before!=archive_equal(args.candidate) or git('status','--porcelain') or git('rev-parse','HEAD')!=qa_head:raise RuntimeError('source changed')
    result={'status':'PASS','candidate':args.candidate,'qa_head':qa_head,'archive_files_byte_equal':len(before),'source_manifest_sha256':hashlib.sha256(json.dumps(before,sort_keys=True).encode()).hexdigest(),'results':results,'owned_temp_removed':True,'scope':'bounded synthetic Linux only'}
    resultfile.write_text(json.dumps(result,sort_keys=True,indent=2)+'\n')
    print(json.dumps({'status':'PASS','candidate':args.candidate,'qa_head':qa_head,'result_sha256':sha(resultfile)},sort_keys=True))
if __name__=='__main__':main()

"""Independent exact AAR/host-overlay/advisory checks; never executes Android code."""
import base64, hashlib, importlib.util, json, os, re, signal, subprocess, sys, tempfile
from pathlib import Path
sys.dont_write_bytecode=True
T=Path('/home/chatbot/wainak-dev/native-archive-tools-phase6-20261024')
AT=Path('/home/chatbot/wainak-dev/archive-tools-phase5-20261024')
A=T/'gomobile-build-197770444867/attempt2-modfile'
B=T/'gobind-197770444867'
S=Path('/home/chatbot/wainak-dev/archive-bridge-phase6')
Q=Path('/home/chatbot/wainak-dev/qa-archive-bridge-phase6')
HEAD='5ff300d48b38e98212ff8b5a7333dd92f8c1c3ff'
OUT=T/'qa-aar-offline-20261025T0041'
DB=T/'public-go-vulndb-20261025T0038'

def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def check(v,m):
 if not v: raise RuntimeError(m)
def git(root,*args): return subprocess.check_output(['git','-C',str(root),*args],text=True,timeout=15).strip()
def objects(data):
 d=json.JSONDecoder();s=data.decode();r=[]
 while s.strip():
  s=s.lstrip();x,n=d.raw_decode(s);r.append(x);s=s[n:]
 return r

def main():
 check(os.getuid()==1001,'owner')
 check(git(S,'rev-parse','HEAD')==HEAD and not git(S,'status','--porcelain'),'source')
 check(git(Q,'rev-parse','HEAD')=='184c4a34b5f98e0c9f2d4ceff0ae40fd1a1ae993' and not git(Q,'status','--porcelain'),'qa_source')
 check(Path('/sys/fs/cgroup/system.slice/onwani-server-admin.service/memory.max').read_text().strip()=='4294967296','cap')
 avail=int(next(l.split()[1] for l in Path('/proc/meminfo').read_text().splitlines() if l.startswith('MemAvailable:')))
 check(avail>=4.5*1024*1024,'headroom')
 pins={A/'binding.mod':'5dcf29a69ea79031e761c9a903fbfd6582dd5944a1c9b2707cd9c0486c88ef6c',A/'binding.sum':'499f336ff315cb42122c1190e819f3a38050641eedeedbdd3674bcf774c6387c',A/'artifacts/archivebridge.aar':'05a6410ff782676cb656e801c03c16af86ae0175dd7e813ea7be3a8ed4f8d95a',A/'artifacts/libgojni.so':'35ce2cbfbfa76910092b6995c6c29502ea976af839eaf75706a9a1428e39f83e',A/'bin/gomobile':'a1f2470c5834bb22ed6485065d0f2f809e9ecc0ccdb11838daabdbaf6b5d8ff8',AT/'bin/govulncheck':'4907a1e5eaae5e3c5b6a120173916b011ea23a0c1c83be8b4f8a09a2a7f69691',Q/'qa/phase6_archive_bridge/bridge_independent_test.go.txt':'16175d21a67563803c57b6c14fc0714959a1be4c893bfe48766227359a493603'}
 for p,h in pins.items(): check(sha(p)==h,'pin '+p.name)
 before={p:sha(S/p) for p in git(S,'ls-files').splitlines()}
 check(sha(DB/'manifest.json')=='1370a12bae56c5ebd201d5557887beca94ee57eba66b6ff68042f1dc46656cb7','snapshot manifest')
 dbmanifest=json.loads((DB/'manifest.json').read_text())
 for item in dbmanifest['requests']:
  rel=item['url'].removeprefix('https://vuln.go.dev/').removesuffix('.gz')
  check(sha(DB/rel)==item['json_sha256'],'snapshot bytes')
 OUT.mkdir(mode=0o700)
 spec=importlib.util.spec_from_file_location('bounded',S/'archive/run_checks.py');base=importlib.util.module_from_spec(spec);spec.loader.exec_module(base)
 def interrupted(*_): raise RuntimeError('interrupted')
 signal.signal(signal.SIGTERM,interrupted);signal.signal(signal.SIGINT,interrupted)
 go=str(AT/'go/bin/go'); scanner=str(AT/'bin/govulncheck')
 gates=[]
 with tempfile.TemporaryDirectory(prefix='qa-aar-',dir=A/'tmp') as temp:
  env={'HOME':str(A/'home'),'PATH':str(AT/'go/bin')+':/usr/bin:/bin','GOPATH':str(A/'gopath'),'GOCACHE':str(B/'gocache'),'GOMODCACHE':str(B/'gomodcache'),'TMPDIR':temp,'GOENV':'off','GOTOOLCHAIN':'local','GOTELEMETRY':'off','GOWORK':'off','CGO_ENABLED':'0','GOFLAGS':'-p=1 -mod=readonly -modfile='+str(A/'binding.mod'),'GOMAXPROCS':'2','GOMEMLIMIT':'768MiB','GOPROXY':'off','GOSUMDB':'off','PYTHONDONTWRITEBYTECODE':'1'}
  overlay=Path(temp)/'overlay.json';overlay.write_text(json.dumps({'Replace':{str(S/'archivebridge/qa_independent_test.go'):str(Q/'qa/phase6_archive_bridge/bridge_independent_test.go.txt')}}))
  def run(label,cmd,allowed=(0,),secret=False):
   code,raw,secs=base.bounded_run(cmd,B/'binding',env,timeout=180)
   result={'gate':label,'exit_code':code,'seconds':secs,'command':cmd}
   if secret:
    events=[{k:e[k] for k in ('Action','Test','Package') if k in e} for e in objects(raw) if e.get('Action') in ('pass','fail','skip')]
    result['tests']=events
    check(sum(e.get('Action')=='pass' and e.get('Test','').startswith('TestQA') and '/' not in e['Test'] for e in events)==17,'17 QA tests required')
    saved=json.dumps(events,sort_keys=True,indent=2).encode()
   else: saved=raw if isinstance(raw,bytes) else raw.encode()
   (OUT/(label+'.json')).write_bytes(saved);result['output_sha256']=sha(OUT/(label+'.json'));gates.append(result)
   print(json.dumps({k:v for k,v in result.items() if k not in ('command','tests')}),flush=True)
   check(code in allowed,'gate failed '+label)
   return raw
  graph=objects(run('all_modules',[go,'list','-m','-json','all']))
  check(not any(x.get('Error') for x in graph),'module errors')
  check(all(x['Path'].startswith('wainek.local/') or x['Path'] in dbmanifest['public_module_allowlist'] for x in graph),'snapshot public graph coverage')
  run('independent_17',[go,'test','-json','-count=1','-parallel=1','-timeout=90s','-overlay='+str(overlay),'-run=^TestQA','wainek.local/archivebridge'],secret=True)
  run('independent_vet',[go,'vet','-overlay='+str(overlay),'wainek.local/archivebridge'])
  run('native_buildinfo',[go,'version','-m',str(A/'artifacts/libgojni.so')])
  run('gomobile_buildinfo',[go,'version','-m',str(A/'bin/gomobile')])
  # Materially safer replacement: all scanner database reads use reviewed localSource.
  # No network namespace claim; explicit file:// client and offline Go settings.
  env['GOVULNDB']=DB.as_uri()
  for label,p in [('gomobile_binary',A/'bin/gomobile'),('android_so_binary',A/'artifacts/libgojni.so')]:
   run(label,[scanner,'-db='+DB.as_uri(),'-json','-mode=binary',str(p)],allowed=(0,3))
  queries=sorted(x['Path']+'@'+x['Version'] for x in graph if x['Path'] in dbmanifest['public_module_allowlist'])+['stdlib@v1.27.3','toolchain@v1.27.3']
  check(len(queries)==21,'complete public module queries')
  run('effective_graph_advisories',[scanner,'-db='+DB.as_uri(),'-json','-mode=query']+queries)
 check(not Path(temp).exists(),'temp remains')
 for p,h in pins.items(): check(sha(p)==h,'post pin '+p.name)
 check(before=={p:sha(S/p) for p in before} and not git(S,'status','--porcelain'),'source changed')
 summaries={}
 for name in ['gomobile_binary','android_so_binary','effective_graph_advisories']:
  rows=objects((OUT/(name+'.json')).read_bytes())
  summaries[name]={'config':[x['config'] for x in rows if 'config'in x], 'sbom':[x.get('SBOM',x.get('sbom')) for x in rows if 'SBOM'in x or 'sbom'in x], 'findings':[x['finding'] for x in rows if 'finding'in x], 'osv_ids':[x['osv']['id'] for x in rows if 'osv'in x]}
 result={'status':'CHECKS_COMPLETED_REVIEW_ADVISORIES','source':HEAD,'qa_head':git(Q,'rev-parse','HEAD'),'effective_inputs':{str(p):h for p,h in pins.items()},'all_modules':[{k:x[k] for k in ('Path','Version') if k in x} for x in graph],'gates':gates,'advisory_snapshot_manifest_sha256':sha(DB/'manifest.json'),'advisory_summaries':summaries,'owned_temp_removed':True,'source_unchanged':True,'source_module_scan':'FAILED: first invalid package-pattern flag, then readonly loader requested mod updates; no changes allowed. Replaced by exact public-module query evaluation, not a source scan pass.','scope':'host tests and cross-built artifact static inspection only; Android execution NOT RUN'}
 (OUT/'result.json').write_text(json.dumps(result,sort_keys=True,indent=2)+'\n')
 print(json.dumps({'result':str(OUT/'result.json'),'sha256':sha(OUT/'result.json'),'advisories':{k:{'findings':v['findings'],'osv_ids':v['osv_ids']} for k,v in summaries.items()}}),flush=True)
if __name__=='__main__': main()

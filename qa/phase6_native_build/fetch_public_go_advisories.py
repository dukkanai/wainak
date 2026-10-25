"""Fetch only fixed public indexes/advisory IDs; never reads a project or artifact."""
import argparse, concurrent.futures, datetime, gzip, hashlib, io, json, pathlib, re, time, urllib.request
PUBLIC=frozenset('''c2sp.org/CCTV/age
filippo.io/age
filippo.io/edwards25519
filippo.io/hpke
filippo.io/nistec
github.com/rogpeppe/go-internal
golang.org/x/crypto
golang.org/x/exp/shiny
golang.org/x/image
golang.org/x/mobile
golang.org/x/mod
golang.org/x/net
golang.org/x/sync
golang.org/x/sys
golang.org/x/term
golang.org/x/text
golang.org/x/tools
golang.org/x/tools/go/expect
golang.org/x/tools/go/packages/packagestest
stdlib
toolchain'''.splitlines())
BASE='https://vuln.go.dev/'
class NoRedirect(urllib.request.HTTPRedirectHandler):
 def redirect_request(self,*args,**kwargs): raise RuntimeError('redirect rejected')
def check(v,m):
 if not v:raise RuntimeError(m)
def fetch(endpoint):
 check(endpoint in ('index/db','index/modules') or re.fullmatch(r'ID/GO-\d{4}-\d{4,8}',endpoint),'public endpoint')
 url=BASE+endpoint+'.json.gz'
 opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
 with opener.open(urllib.request.Request(url,method='GET',headers={'Accept-Encoding':'identity'}),timeout=20) as r:
  check(r.status==200 and r.url==url,'origin/status')
  compressed=r.read(8*1024*1024+1)
 check(len(compressed)<=8*1024*1024,'compressed bound')
 with gzip.GzipFile(fileobj=io.BytesIO(compressed)) as z:raw=z.read(32*1024*1024+1)
 check(len(raw)<=32*1024*1024,'expanded bound')
 obj=json.loads(raw)
 if endpoint.startswith('ID/'):check(obj.get('id')==endpoint[3:],'advisory identity')
 return endpoint,raw,{'url':url,'compressed_bytes':len(compressed),'compressed_sha256':hashlib.sha256(compressed).hexdigest(),'json_bytes':len(raw),'json_sha256':hashlib.sha256(raw).hexdigest()}
def main():
 ap=argparse.ArgumentParser();ap.add_argument('output',type=pathlib.Path);a=ap.parse_args()
 check(not a.output.exists() and a.output.parent.is_dir(),'new owned output required')
 a.output.mkdir(mode=0o700);(a.output/'index').mkdir();(a.output/'ID').mkdir()
 records=[];total=0;started=time.monotonic();utc=datetime.datetime.now(datetime.timezone.utc).isoformat()
 def save(row):
  nonlocal total
  endpoint,raw,record=row;total+=len(raw)
  check(total<=64*1024*1024,'total bound');check(time.monotonic()-started<300,'overall deadline')
  (a.output/(endpoint+'.json')).write_bytes(raw);records.append(record)
  return json.loads(raw)
 db=save(fetch('index/db'));mods=save(fetch('index/modules'))
 check(isinstance(mods,list) and len(mods)<=100000,'index shape')
 ids=set();covered=set()
 for m in mods:
  if m.get('path') in PUBLIC:
   covered.add(m['path'])
   for v in m['vulns']:
    check(re.fullmatch(r'GO-\d{4}-\d{4,8}',v['id']),'public id');ids.add(v['id'])
 check(len(ids)<=1500,'advisory count')
 with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
  for row in pool.map(fetch,['ID/'+i for i in sorted(ids)]): save(row)
 manifest={'source':BASE,'created_utc':utc,'db_modified':db.get('modified'),'public_module_allowlist':sorted(PUBLIC),'modules_with_entries':sorted(covered),'absent_from_index':sorted(PUBLIC-covered),'advisories':len(ids),'requests':records,'total_json_bytes':total,'scope':'Public complete module index plus every ID referenced for fixed public modules; no project/artifact/secret read, query, upload or redirect; not complete DB for unlisted modules'}
 (a.output/'manifest.json').write_text(json.dumps(manifest,sort_keys=True,indent=2)+'\n')
 print(json.dumps({'status':'PUBLIC_SNAPSHOT_READY','path':str(a.output),'advisories':len(ids),'bytes':total,'manifest_sha256':hashlib.sha256((a.output/'manifest.json').read_bytes()).hexdigest()}))
if __name__=='__main__':main()

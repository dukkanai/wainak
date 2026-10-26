"""Future Apple build implementation; imported only for explicit --build-ios.

No code here is executed by --check. The caller owns this process group and must
TERM/grace>=15s/KILL it on timeout/error, including when this leader has exited.
Children never start another session. No signing, license acceptance, SDK install,
provider calls, vendor patches, go interception, init or latest operations exist.
"""
import base64
from contextlib import contextmanager
import sys
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import platform
import plistlib
import re
import selectors
import shutil
import signal
import stat
import subprocess
import tarfile
import time
import urllib.request
from check_static import InvalidRecipe, require, read_regular, read_json, sha, module_id
from host_diagnostics import declared_tests, project_go_events, safe_last_command, HOST_COMMANDS, classify_tool_output, classify_gate_error, graph_failure_reason
from artifact_diagnostics import strict_symbols_present, symbol_summary, load_summary, reason as artifact_reason
from artifact_static import static_arm64_container, validate_modulemap, validate_apple_load_commands

class BuildFailure(RuntimeError):
    pass

def digest_file(path):
    h=hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024), b''): h.update(chunk)
    return h.hexdigest()

def safe_child(root, path):
    root=root.resolve(); path=path.absolute()
    require(path.is_relative_to(root) and path != root, 'path escapes owned root')
    current=root
    for part in path.relative_to(root).parts:
        require(part not in ('','.', '..'), 'unsafe path component')
        current=current/part
        require(not current.is_symlink(), 'symlink in owned path')
    return path

def byte_size(root):
    if not root.exists(): return 0
    total=root.lstat().st_size
    for path in root.rglob('*'):
        total += path.lstat().st_size
    return total

def file_inventory(root):
    result={}
    for path in sorted(root.rglob('*')):
        require(not path.is_symlink(), 'unexpected artifact/source symlink')
        if path.is_file(): result[str(path.relative_to(root))]=digest_file(path)
    return result

def json_stream(raw):
    out=[]; decoder=json.JSONDecoder(); text=raw.decode()
    while text.strip():
        text=text.lstrip(); item,end=decoder.raw_decode(text); out.append(item); text=text[end:]
    return out

def escaped_module(value):
    return ''.join('!'+c.lower() if c.isupper() else c for c in value)

class Runtime:
    def __init__(self, repo, work, lock):
        self.repo, self.work, self.lock=repo,work,lock
        self.cancelled=False; self.commands=[]; self.stage='preflight'; self.sequence=0
        self.last_audit=None; self.last_aggregate=0; self.reserved=0
        self.last_command=None; self.test_names=declared_tests(repo,lock['source_hashes']); self.resource_final_audit_failed=False
        self.previous={s:signal.signal(s,self.signal) for s in (signal.SIGTERM,signal.SIGINT)}
    def signal(self, number, frame): self.cancelled=True
    def restore(self):
        for sig,handler in self.previous.items(): signal.signal(sig,handler)
    def full_audit(self):
        aggregate=sum(byte_size(p) for p in (
            self.repo/'.ci-work',self.repo/'apps/mobile/build',self.repo/'apps/mobile/.dart_tool',
            self.repo/'apps/mobile/ios/Flutter/ephemeral'))
        self.last_aggregate=aggregate; self.last_audit=time.monotonic()
        self.full_audits=getattr(self,'full_audits',0)+1
        return aggregate
    def guard(self, force=False):
        if self.cancelled: raise BuildFailure('build cancelled')
        now=time.monotonic()
        if force or self.last_audit is None or now-self.last_audit>=2:
            self.full_audit()
        if self.last_aggregate+self.reserved>self.lock['limits']['aggregate_bytes']:
            raise BuildFailure('workspace budget exceeded')
        if shutil.disk_usage(self.repo).free<self.lock['limits']['minimum_free_bytes']+self.reserved:
            raise BuildFailure('free disk floor exceeded')
        return self.last_aggregate
    @contextmanager
    def reservation(self, size):
        require(type(size) is int and size>=0 and self.reserved==0,'invalid resource reservation')
        self.reserved=size
        self.peak_reserved=max(getattr(self,'peak_reserved',0),size)
        try:
            self.guard(force=True)
            yield
        finally:
            primary=sys.exc_info()[1]; self.reserved=0
            try: self.guard(force=True)
            except BaseException:
                if primary is None: raise
                self.resource_final_audit_failed=True
    def consume(self, size):
        require(type(size) is int and 0<=size<=self.reserved,'reservation exhausted')
        self.reserved-=size
    def run(self, args, cwd, env, name, public_output=True, seconds=None, go_json=False):
        self.sequence+=1; started=time.monotonic(); data=bytearray(); proc=None
        timeout=seconds if seconds is not None else self.lock['limits']['process_seconds']
        primary=None; failure='NONE'; cleanup_failed=False
        try:
            if timeout<=0: raise BuildFailure('child deadline exceeded')
            self.guard(force=True)
            proc=subprocess.Popen([str(a) for a in args],cwd=cwd,env=env,
                                  stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,
                                  stderr=subprocess.STDOUT,start_new_session=False)
            with selectors.DefaultSelector() as select:
                select.register(proc.stdout,selectors.EVENT_READ)
                while select.get_map():
                    self.guard()
                    if time.monotonic()-started>timeout: raise BuildFailure('child deadline exceeded')
                    for key,_ in select.select(.5):
                        chunk=os.read(key.fileobj.fileno(),65536)
                        if not chunk: select.unregister(key.fileobj); continue
                        if len(data)+len(chunk)>self.lock['limits']['process_output_bytes']:
                            raise BuildFailure('child output bound exceeded')
                        data.extend(chunk)
                code=proc.wait(timeout=5)
            self.guard(force=True)
            if code: raise BuildFailure('child command failed')
            return bytes(data)
        except BaseException as error:
            primary=error
            fixed={'build cancelled':'CANCELLED','child deadline exceeded':'TIMEOUT',
                   'child output bound exceeded':'OUTPUT_BOUND','child command failed':'NONZERO_EXIT',
                   'workspace budget exceeded':'RESOURCE_GUARD','free disk floor exceeded':'RESOURCE_GUARD'}
            failure=fixed.get(str(error),'SPAWN_OR_IO' if isinstance(error,OSError) else 'OTHER')
            raise
        finally:
            # Preserve primary failure; never claim success if direct-child cleanup fails.
            if proc is not None:
                try:
                    if proc.poll() is None:
                        proc.terminate()
                        try: proc.wait(timeout=8)
                        except subprocess.TimeoutExpired: proc.kill(); proc.wait(timeout=2)
                except BaseException: cleanup_failed=True
                try:
                    if proc.stdout is not None: proc.stdout.close()
                except BaseException: cleanup_failed=True
            try: self.guard(force=True)
            except BaseException: cleanup_failed=True
            if cleanup_failed and primary is None: failure='CLEANUP'
            outcome='FAILED' if primary is not None or cleanup_failed else 'PASS'
            elapsed=time.monotonic()-started
            projection=None; proof_failed=False
            if go_json:
                package='wainak.local/archivebridge' if name.startswith('archivebridge-') else 'wainak.local/historyarchive'
                projection,has_failure,proof_ok=project_go_events(bytes(data),self.test_names[package],package)
                proof_failed=not proof_ok
                if proof_failed and primary is None and not cleanup_failed: failure='OTHER';outcome='FAILED'
                if outcome=='FAILED' and not has_failure:
                    projection['failure_categories'].append('NO_TEST_FAILURE_EVENT')
            elif outcome=='FAILED' and name in ('age-cli-build','archive-test-compile','archivebridge-test-compile'):
                projection={'failed_tests':[],'failure_categories':['COMPILE_PHASE_FAILURE']}
            last=safe_last_command(name,None if proc is None else proc.returncode,elapsed,outcome,failure,projection)
            if last is not None and outcome == 'FAILED' and name not in HOST_COMMANDS:
                try: last['tool_categories'] = classify_tool_output(bytes(data))
                except BaseException: last['tool_categories'] = ['UNKNOWN_TOOL_FAILURE']
            self.last_command=last
            row={'name':name,'exit_code':None if proc is None else proc.returncode,
                 'elapsed_seconds':round(elapsed,3),'outcome':outcome,'failure_kind':failure,
                 'output_bytes':len(data),'output_sha256':hashlib.sha256(data).hexdigest()}
            if projection is not None: row.update(projection)
            self.commands.append(row)
            try:
                if public_output: (self.work/'logs'/f'{self.sequence:03}-{name}.log').write_bytes(data)
                (self.work/'commands.json').write_text(json.dumps(self.commands,indent=2,sort_keys=True)+'\n')
            except BaseException:
                cleanup_failed=True
                row.update(outcome='FAILED',failure_kind=failure if primary is not None else 'SPAWN_OR_IO')
                if self.last_command is not None:
                    self.last_command.update(outcome='FAILED',failure_kind=row['failure_kind'])
                try: (self.work/'commands.json').write_text(json.dumps(self.commands,indent=2,sort_keys=True)+'\n')
                except BaseException: pass
            if cleanup_failed and primary is None: raise BuildFailure('command cleanup failed')
            if proof_failed and primary is None: raise BuildFailure('test JSON proof invalid')

def download_go(runtime, spec, target):
    part=target.with_suffix('.part'); require(not part.exists() and not target.exists(),'download destination exists')
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, request, fp, code, message, headers, newurl):
            raise BuildFailure('Go artifact redirect rejected before connection')
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
    h=hashlib.sha256(); count=0
    with opener.open(spec['url'],timeout=30) as response, part.open('xb') as stream:
        require(response.url==spec['url'],'unexpected Go artifact redirect')
        while True:
            runtime.guard(); chunk=response.read(1024*1024)
            if not chunk: break
            count+=len(chunk); require(count<=spec['bytes'],'Go artifact size exceeded')
            h.update(chunk); stream.write(chunk)
    require(count==spec['bytes'] and h.hexdigest()==spec['sha256'],'Go artifact integrity failure')
    part.rename(target)

def extract_go(runtime, archive, destination, limit):
    require(not destination.exists(),'tool extraction destination exists')
    # Reserve payload plus conservative metadata before any extraction. This is
    # accounting under a monitored cap, not an OS allocation quota.
    with runtime.reservation(limit+128*1024*1024):
        destination.mkdir(mode=0o700); runtime.consume(destination.lstat().st_size)
        total=0; names=set(); metadata=0
        with tarfile.open(archive,'r:gz') as tar:
            for member in tar:
                runtime.guard(); p=PurePosixPath(member.name)
                require(not p.is_absolute() and '..' not in p.parts and p.parts and p.parts[0]=='go','unsafe Go archive path')
                require(len(member.name)<=4096 and len(p.parts)<=32,'archive path bounds')
                require(member.name not in names and len(names)<30000,'duplicate/excess Go archive members'); names.add(member.name)
                require(member.isdir() or member.isfile(),'Go archive links/special files rejected')
                require(member.size>=0,'negative archive size'); total+=member.size
                require(total<=limit,'Go archive expanded bound exceeded')
                output=safe_child(destination,destination.joinpath(*p.parts))
                parent=output if member.isdir() else output.parent
                absent=[]; current=parent
                while not current.exists(): absent.append(current);current=current.parent
                for directory in reversed(absent):
                    directory.mkdir(mode=0o700); cost=directory.lstat().st_size
                    metadata+=cost; require(metadata<=128*1024*1024,'archive metadata bound')
                    runtime.consume(cost)
                if member.isdir(): continue
                require(member.size<=runtime.reserved,'extraction reservation exhausted')
                with tar.extractfile(member) as source, output.open('xb') as sink:
                    written=0
                    while True:
                        runtime.guard(); block=source.read(1024*1024)
                        if not block: break
                        require(written+len(block)<=member.size,'archive member size grew')
                        sink.write(block);written+=len(block);runtime.consume(len(block))
                require(output.stat().st_size==member.size,'Go archive member size mismatch')
                output.chmod(0o700 if member.mode&0o111 else 0o600)
    return destination/'go/bin/go'

def make_env(work, go, developer_dir):
    # No inherited credentials, signing settings, proxies, GOFLAGS or persistent Go config.
    return {'HOME':str(work/'home'),'PATH':str(go.parent)+':'+str(work/'bin')+':/usr/bin:/bin:/usr/sbin:/sbin',
            'TMPDIR':str(work/'tmp'),'GOTMPDIR':str(work/'compiler-tmp'),'GOENV':'off','GOTOOLCHAIN':'local','GOWORK':'off','GOTELEMETRY':'off',
            'GOPROXY':'off','GOSUMDB':'off','GONOSUMDB':'','GONOPROXY':'','GOPRIVATE':'',
            'GOMODCACHE':str(work/'gomodcache'),'GOCACHE':str(work/'gocache'),'GOPATH':str(work/'gopath'),
            'GOFLAGS':'-mod=readonly -p=1','GOMAXPROCS':'2','GOMEMLIMIT':'1073741824',
            'DEVELOPER_DIR':developer_dir,'LANG':'en_US.UTF-8','LC_ALL':'C','CGO_ENABLED':'1'}

def all_rows(lock): return lock['input_modules']+lock['auxiliary_modules']

def make_module(path, name, lock, local_sources=None):
    path.mkdir(parents=True,exist_ok=False)
    text='module '+name+'\n\ngo 1.27.3\n\nrequire (\n'
    text+=''.join('\t'+m['path']+' '+m['version']+'\n' for m in lock['input_modules'])
    if local_sources:
        for module in local_sources: text+='\t'+module+' v0.0.0\n'
    text+=')\n'
    if local_sources:
        for module,target in local_sources.items(): text+='replace '+module+' => '+str(target)+'\n'
    (path/'go.mod').write_text(text)
    sums=[]
    for row in all_rows(lock):
        sums.append(row['path']+' '+row['version']+'/go.mod '+row['go_mod_sum'])
        if not row.get('metadata_only'): sums.append(row['path']+' '+row['version']+' '+row['sum'])
    (path/'go.sum').write_text('\n'.join(sorted(set(sums)))+'\n')


def validate_graph_controls(controls, local, generated_main=None):
    require(not controls.get('Exclude') and not controls.get('Toolchain'),'unapproved graph controls')
    seen=set()
    for replacement in controls.get('Replace') or []:
        old,new=replacement.get('Old',{}),replacement.get('New',{})
        identity=old.get('Path')
        require(identity not in seen,'duplicate replacement control');seen.add(identity)
        require(not old.get('Version') and not new.get('Version'),'versioned replacement control')
        # Upstream parseModuleVersions preserves the original versionless main
        # module as a control-only local replacement. It is NOT a dependency.
        expected=local.get(identity)
        if identity=='wainak.local/cibinding' and generated_main is not None:
            expected=generated_main
        require(expected is not None and new.get('Path')==str(expected),'unapproved replacement')


def inspect_graph(runtime, go, cwd, env, name, allowed, local, generated_main=None):
    if generated_main is not None:
        require(name in ('target-0','target-1'),'owned main replacement context invalid')
        target_root=runtime.work/'tmp'
        parts=cwd.relative_to(target_root).parts if cwd.is_relative_to(target_root) else ()
        require(len(parts)==3 and parts[-2] in ('ios','iossimulator') and parts[-1]=='src-arm64' and
                cwd.is_dir() and cwd.resolve()==cwd and not any(part.is_symlink() for part in (cwd,*cwd.parents)),
                'owned main replacement context invalid')
        expected=runtime.work/'binding'
        require(type(generated_main) is type(expected) and generated_main==expected and generated_main.is_absolute(),
                'owned main replacement path invalid')
        # Reject links in every component, not merely the final directory.
        require(generated_main.is_dir() and generated_main.resolve()==generated_main and
                not any(part.is_symlink() for part in (generated_main,*generated_main.parents)),
                'owned main replacement path invalid')
    raw=runtime.run([go,'list','-m','-json','all'],cwd,env,name+'-modules')
    rows=json_stream(raw)
    if generated_main is not None:
        mains=[row for row in rows if row.get('Main')]
        require(len(mains)==1 and mains[0].get('Path')=='gobind','generated target main module invalid')
    for row in rows:
        require(not row.get('Error'),'unresolved graph metadata')
        if row.get('Main'): continue
        require(row.get('Path')!='wainak.local/cibinding','owned main module selected as dependency')
        key=(row['Path'],row.get('Version'))
        if row['Path'] in local:
            require(row.get('Replace',{}).get('Dir')==str(local[row['Path']]),'local source replacement drift')
        else:
            require(key in allowed and not row.get('Replace'),'unapproved public module selected')
    controls=json.loads(runtime.run([go,'mod','edit','-json'],cwd,env,name+'-controls'))
    validate_graph_controls(controls,local,generated_main)
    return {'modules':rows,'controls':controls,'go_mod_sha256':digest_file(cwd/'go.mod'),
            'go_sum_sha256':digest_file(cwd/'go.sum') if (cwd/'go.sum').exists() else None}


def inspect_target_packages(runtime, go, root, env, variant, allowed, local):
    """Record actual imported target packages, separate from selected module roots."""
    sdk = 'iphonesimulator' if variant == 'simulator' else 'iphoneos'
    clang = runtime.run(['/usr/bin/xcrun','--sdk',sdk,'--find','clang'],runtime.repo,env,sdk+'-clang').decode().strip()
    sysroot = runtime.run(['/usr/bin/xcrun','--sdk',sdk,'--show-sdk-path'],runtime.repo,env,sdk+'-sysroot').decode().strip()
    require(not any(c.isspace() for c in clang+sysroot),'unsupported whitespace in pinned SDK paths')
    # Mirror pinned env.go212-223/266-276/436-459; no vendor interception.
    minimum_flag='-mios-simulator-version-min=' if variant=='simulator' else '-miphoneos-version-min='
    flags='-isysroot '+sysroot+' '+minimum_flag+'15.0 -fembed-bitcode -arch arm64'
    target_env = dict(env,GOOS='ios',GOARCH='arm64',CGO_ENABLED='1',CC=clang,CXX=clang+'++',
                      CGO_CFLAGS=flags,CGO_CXXFLAGS=flags,CGO_LDFLAGS=flags,DARWIN_SDK=sdk,GOFLAGS='-mod=readonly -p=1 -tags=ios')
    raw=runtime.run([go,'list','-deps','-json','./gobind'],root,target_env,'target-'+variant+'-packages')
    rows=json_stream(raw); result=[]
    for row in rows:
        require(not row.get('Error') and not row.get('DepsErrors'),'target imported package closure unresolved')
        module=row.get('Module')
        if module and not module.get('Main'):
            if module['Path'] in local:
                require(module.get('Replace',{}).get('Dir')==str(local[module['Path']]),'target package local replacement drift')
            else:
                require((module['Path'],module.get('Version')) in allowed and not module.get('Replace'),
                        'target package uses an unapproved dependency')
        result.append({'import_path':row['ImportPath'],'standard':bool(row.get('Standard')),
                       'module':None if not module else {'path':module['Path'],'version':module.get('Version')},
                       'go_files':row.get('GoFiles',[]),'cgo_files':row.get('CgoFiles',[])})
    require(result,'target package closure empty')
    return {'variant':variant,'sdk':sdk,'goos':'ios','goarch':'arm64','cgo_flags':flags,
            'upstream_env_source_sha256':'0a8be58a499bc36f8fe0dd8da7a44f5c4388d000f12b041d95158d29a359285b','packages':result}


def acquire_modules(runtime, go, cwd, env, lock):
    network=dict(env,GOPROXY='https://proxy.golang.org',GOSUMDB='sum.golang.org')
    licenses=[]; modules=[]
    for row in all_rows(lock):
        runtime.guard(); key=module_id(row)
        if row.get('metadata_only'):
            folder=Path(env['GOMODCACHE'])/'cache/download'/escaped_module(row['path'])/'@v'
            folder.mkdir(parents=True,exist_ok=True)
            (folder/(row['version']+'.mod')).write_text(row['go_mod'])
            (folder/(row['version']+'.info')).write_text(json.dumps(row['info'],sort_keys=True))
            continue
        raw=runtime.run([go,'mod','download','-json',row['path']+'@'+row['version']],cwd,network,'module-acquisition')
        info=json.loads(raw); require(not info.get('Error'),'public module acquisition failed')
        require((info['Path'],info['Version'])==key and info['Sum']==row['sum'] and info['GoModSum']==row['go_mod_sum'],
                'module integrity/identity mismatch')
        source=Path(info['Dir']); archive=Path(info['Zip']); mod=Path(info['GoMod'])
        require(source.is_relative_to(Path(env['GOMODCACHE'])) and archive.is_relative_to(Path(env['GOMODCACHE'])),'cache path escaped')
        require(archive.stat().st_size<=lock['limits']['module_zip_bytes'] and byte_size(source)<=lock['limits']['module_expanded_bytes'],
                'module size bound exceeded')
        require(digest_file(mod)==row['go_mod_sha256'],'authenticated module metadata changed')
        found=[]
        for path in source.rglob('*'):
            if path.is_file() and not path.is_symlink() and re.match(r'(?i)^(license|copying|notice|patents)(?:[._-].*)?$',path.name):
                data=read_regular(path,1024*1024); relative=str(path.relative_to(source))
                name=hashlib.sha256((row['path']+'@'+row['version']+'/'+relative).encode()).hexdigest()+'.txt'
                (runtime.work/'licenses'/name).write_bytes(data)
                found.append({'path':relative,'sha256':hashlib.sha256(data).hexdigest(),'retained_file':name})
        for exception in lock.get('license_path_exceptions',[]):
            if (exception['path'],exception['version'])==key:
                path=source/exception['file']; data=read_regular(path,1024*1024)
                require(hashlib.sha256(data).hexdigest()==exception['sha256'],'pinned license exception changed')
                name=exception['sha256']+'.txt'; (runtime.work/'licenses'/name).write_bytes(data)
                found.append({'path':exception['file'],'sha256':exception['sha256'],'retained_file':name,'explicit_exception':True})
        require(found,'module license provenance missing')
        licenses.append({'module':row['path']+'@'+row['version'],'files':found,'legal_clearance':False})
        modules.append({'path':row['path'],'version':row['version'],'sum':row['sum'],'go_mod_sum':row['go_mod_sum'],
                        'zip_sha256':digest_file(archive),'source_inventory':file_inventory(source)})
    (runtime.work/'licenses.json').write_text(json.dumps(licenses,indent=2,sort_keys=True)+'\n')
    return modules


def cache_inventory(env):
    result={}
    for name in ('GOCACHE','GOMODCACHE','GOTMPDIR'):
        root=Path(env[name]);require(root.is_dir() and not root.is_symlink(),'cache root boundary')
        files={}
        for path in sorted(root.rglob('*')):
            mode=path.lstat().st_mode
            require(stat.S_ISDIR(mode) or stat.S_ISREG(mode),'unexpected cache special file')
            if stat.S_ISREG(mode): files[str(path.relative_to(root))]=digest_file(path)
        result[name]=files
    return result

def runtime_test_env(env, root, age):
    # No compiler cache paths inherited by the executed test/CLI. These writable
    # destinations and cwd are all inside the owned canary-scanned root.
    return {'PATH':'/nonexistent','LC_ALL':'C','HOME':str(root/'home'),'TMPDIR':str(root/'tmp'),
            'GOENV':'off','GOTOOLCHAIN':'local','GOWORK':'off','GOTELEMETRY':'off',
            'GOPROXY':'off','GOSUMDB':'off','GOMAXPROCS':'2','GOMEMLIMIT':'1073741824',
            'WAINAK_ARCHIVE_INTEROP':'1','WAINAK_AGE_CLI':str(age),
            'WAINAK_AGE_CLI_SHA256':digest_file(age),'WAINAK_ARCHIVE_SCAN_ROOT':str(root)}

def test_host_policy(runtime, go, tools_module, env, lock):
    runtime.stage='new-policy-host-tests'
    age=runtime.work/'bin/age'
    runtime.run([go,'build','-trimpath','-o',age,'filippo.io/age/cmd/age'],tools_module,dict(env,CGO_ENABLED='0'),'age-cli-build')
    source=runtime.work/'host-tests'; source.mkdir()
    local={'wainak.local/historyarchive':source/'archive/module'}
    results=[]
    for name,module in [('archive','wainak.local/historyarchive'),('archivebridge','wainak.local/archivebridge')]:
        root=source/name; root.mkdir(mode=0o700)
        for folder in ('home','tmp'): (root/folder).mkdir(mode=0o700)
        target=root/'module';make_module(target,module,lock,None if name=='archive' else local)
        for path in (runtime.repo/name).glob('*.go'): shutil.copyfile(path,target/path.name)
        compileenv=dict(env,CGO_ENABLED='0')
        binary=runtime.work/'bin'/(name+'.test')
        deadline=time.monotonic()+180
        runtime.run([go,'test','-c','-o',binary,'.'],target,compileenv,name+'-test-compile',public_output=False,seconds=deadline-time.monotonic())
        before=cache_inventory(env)
        binary_before=digest_file(binary); age_before=digest_file(age)
        testenv=runtime_test_env(env,root,age)
        audit={'cache_before_sha256':hashlib.sha256(json.dumps(before,sort_keys=True).encode()).hexdigest(),
               'runtime_cwd_home_tmp':'owned-test-root','cache_unchanged_during_runtime_tests':False,
               'scan_bound_bytes':512*1024*1024,'os_sandbox':False,
               'test_binary_sha256':binary_before,'age_cli_sha256':age_before}
        try:
            runtime.run([go,'tool','test2json','-t','-p',module,binary,'-test.v=test2json','-test.count=1','-test.timeout=120s'],
                        target,testenv,name+'-tests',public_output=False,seconds=deadline-time.monotonic(),go_json=True)
        finally:
            primary=sys.exc_info()[1]
            try:
                after=cache_inventory(env)
                audit.update(cache_after_sha256=hashlib.sha256(json.dumps(after,sort_keys=True).encode()).hexdigest(),
                             cache_unchanged_during_runtime_tests=before==after)
                (runtime.work/(name+'-runtime-cache.json')).write_text(json.dumps(audit,sort_keys=True)+'\n')
                require(before==after,'compiler/module cache changed during runtime tests')
                require(binary_before==digest_file(binary) and age_before==digest_file(age),'runtime binary changed')
            except BaseException:
                if primary is None: raise
                runtime.resource_final_audit_failed=True
        runtime.run([go,'vet','./...'],target,compileenv,name+'-vet',public_output=False,seconds=180)
        results.append({'module':module,'status':'PASS','graph_policy':'explicit-input26','interop_enabled':name=='archive',
                        'runtime_cache_audit':audit})
        if name=='archive':
            for fuzz in ('FuzzStrictHistoryJSON','FuzzArchiveOpen'):
                # Keep supported go test fuzz instrumentation. Corpus inputs are
                # public schema literals or ciphertext, never runtime key/canary.
                fuzz_env=dict(compileenv,HOME=str(root/'home'),TMPDIR=str(root/'tmp'))
                cache_before=cache_inventory(env)
                try:
                    runtime.run([go,'test','-json','-run=^$','-fuzz=^'+fuzz+'$','-fuzztime=10s','-parallel=1'],target,fuzz_env,
                                'fuzz-'+fuzz,public_output=False,seconds=60,go_json=True)
                finally:
                    primary=sys.exc_info()[1]
                    try:
                        cache_after=cache_inventory(env)
                        (runtime.work/(fuzz+'-cache.json')).write_text(json.dumps({'before':cache_before,'after':cache_after,
                            'corpus_scope':'public-schema-input-or-ciphertext-only','cache_immutable_claim':False},sort_keys=True)+'\n')
                        require(cache_before['GOMODCACHE']==cache_after['GOMODCACHE'],'module cache changed during fuzz')
                    except BaseException:
                        if primary is None: raise
                        runtime.resource_final_audit_failed=True

    return results

def inspect_xcframework(runtime, output, env, lock):
    # Only independent read-only checks continue after a semantic mismatch.
    # Command/resource/cancellation failures still propagate immediately.
    receipt={'checks':[],'symbols':[],'loads':[]};runtime.artifact_receipt=receipt
    failed=False
    def check(label,variant,operation):
        nonlocal failed
        try:
            value=operation()
        except (InvalidRecipe,OSError,ValueError,KeyError,TypeError) as error:
            failed=True
            try:code=artifact_reason(error)
            except BaseException:code='UNKNOWN'
            receipt['checks'].append({'check':label,'variant':variant,'outcome':'FAILED','reason':code})
            return False,None
        receipt['checks'].append({'check':label,'variant':variant,'outcome':'PASS','reason':'NONE'})
        return True,value
    def metadata():
        info=plistlib.loads(read_regular(output/'Info.plist'))
        require(type(info) is dict,'wrong XCFramework slice count')
        libs=info.get('AvailableLibraries',[])
        require(type(libs) is list and len(libs)==2,'wrong XCFramework slice count')
        return libs
    ok,libs=check('metadata','unknown',metadata)
    require(ok,'artifact validation failed')
    observed=set();results=[]
    for lib in libs:
        def slice_metadata():
            require(type(lib) is dict,'unexpected native platform/ABI')
            require(lib['SupportedPlatform']=='ios' and lib['SupportedArchitectures']==['arm64'],'unexpected native platform/ABI')
            variant=lib.get('SupportedPlatformVariant','device')
            require(variant in ('device','simulator'),'unexpected native variant')
            require(variant not in observed,'duplicate native variant');observed.add(variant)
            return variant
        ok,variant=check('slice_metadata','unknown',slice_metadata)
        if not ok:continue
        def slice_path():
            path=PurePosixPath(lib['LibraryIdentifier'])/lib['LibraryPath']
            require(not path.is_absolute() and '..' not in path.parts,'unsafe XCFramework metadata path')
            return safe_child(output,output.joinpath(*path.parts))
        ok,framework=check('path',variant,slice_path)
        if not ok:continue
        binary=framework/'Archivebridge'
        check('header',variant,lambda:require(sha(framework/'Headers/Archivebridge.objc.h')==lock['apple']['header_sha256'],'regenerated ABI header changed'))
        check('modulemap',variant,lambda:validate_modulemap(read_regular(framework/'Modules/module.modulemap').decode(),lock['apple']['headers']))
        container_ok,container=check('container',variant,lambda:static_arm64_container(binary))
        load_evidence=None
        if container_ok:
            # Do not swallow runtime.run errors: limits and primary errors retain ownership.
            raw=runtime.run(['/usr/bin/xcrun','lipo','-archs',binary],runtime.repo,env,'slice-architecture')
            check('architecture',variant,lambda:require(raw.decode().strip()=='arm64','unexpected binary architectures'))
            raw=runtime.run(['/usr/bin/xcrun','nm','-g',binary],runtime.repo,env,'slice-symbols')
            decoded,symbols=check('symbols',variant,lambda:raw.decode())
            if decoded:
                try:summary=symbol_summary(symbols)
                except BaseException:summary={'complete':False}
                receipt['symbols'].append({'variant':variant,**summary})
                # Replace decode-only receipt with the unchanged acceptance check.
                receipt['checks'].pop()
                check('symbols',variant,lambda:require(strict_symbols_present(symbols),'defined native binding symbols missing'))
            raw=runtime.run(['/usr/bin/xcrun','otool','-l',binary],runtime.repo,env,'slice-load-commands')
            decoded,loads=check('load_commands',variant,lambda:raw.decode())
            if decoded:
                try:summary=load_summary(loads)
                except BaseException:summary={'complete':False}
                receipt['loads'].append({'variant':variant,**summary})
                receipt['checks'].pop()
                _,load_evidence=check('load_commands',variant,lambda:validate_apple_load_commands(loads,variant))
        def framework_plist():
            plist=plistlib.loads(read_regular(framework/'Info.plist'))
            require(type(plist) is dict,'upstream framework metadata changed')
            require(plist.get('MinimumOSVersion')==lock['apple']['framework_plist_minimum_os_upstream'],'upstream framework metadata changed')
        check('framework_plist',variant,framework_plist)
        _,binary_hash=check('binary_hash',variant,lambda:digest_file(binary)) if container_ok else (False,None)
        results.append({'variant':variant,'architectures':['arm64'],'binary_sha256':binary_hash,'static_container':container,'load_command_evidence':load_evidence})
    check('variants','unknown',lambda:require(observed=={'device','simulator'},'missing Apple slice'))
    require(not failed,'artifact validation failed')
    return results


def finalize_native_result(runtime,repo,directory,result,initial,manifests,primary):
    """Bounded audit labels; final bookkeeping never replaces an existing failure."""
    errors=[]
    def audit(label, action):
        try: return action()
        except BaseException: errors.append(label); return None
    audit('SOURCE_GUARD',lambda:require(initial=={name:sha(repo/name) for name in initial},'repository Go source changed'))
    audit('MODULE_MANIFEST_GUARD',lambda:require(manifests=={name:sha(repo/name) for name in manifests},'repository manifests changed'))
    result['last_command']=runtime.last_command
    if hasattr(runtime,'artifact_receipt'):result['artifact_inspection']=runtime.artifact_receipt
    result['resource_final_audit_failed']=runtime.resource_final_audit_failed
    result['resource_monitor']={'period_seconds':2,'full_audits_before_final':getattr(runtime,'full_audits',0),
        'peak_reserved_bytes':getattr(runtime,'peak_reserved',0),'hard_quota':False}
    result['commands_manifest_sha256']=audit('COMMAND_METADATA',lambda:digest_file(runtime.work/'commands.json') if (runtime.work/'commands.json').exists() else None)
    result['lock_sha256']=audit('LOCK_METADATA',lambda:sha(directory/'lock.json'))
    if errors or primary is not None:result.update(status='FAILED',failed_stage=runtime.stage)
    result['final_audit_errors']=errors;result['final_budget_audit']='PASS'
    path=runtime.work/'result.json'
    audit('RESULT_WRITE',lambda:path.write_text(json.dumps(result,indent=2,sort_keys=True)+'\n'))
    audit('RESOURCE_GUARD',lambda:runtime.guard(force=True))
    if errors:
        result.update(status='FAILED',failed_stage=runtime.stage,final_budget_audit='FAILED')
        # One best-effort fixed failure result; never serialize exception messages.
        try:path.write_text(json.dumps(result,indent=2,sort_keys=True)+'\n')
        except BaseException:pass
        if primary is None:raise BuildFailure('final audit failed')


def build_ios(repo, directory, lock, work, output):
    require(platform.system()=='Darwin' and platform.machine()=='arm64','Apple arm64 host required')
    require(os.getpgrp()==os.getpid(),'outer driver must own this native process group')
    repo=repo.resolve(); expected=repo/'.ci-work/native'
    require(work.absolute()==expected and output.absolute()==expected/'Archivebridge.xcframework','explicit canonical native output required')
    safe_child(repo,work); require(not work.exists(),'native attempt already exists; no implicit cleanup/overwrite')
    os.umask(0o077); work.mkdir(parents=True,mode=0o700)
    for name in ('logs','home','tmp','compiler-tmp','bin','licenses'): (work/name).mkdir(mode=0o700)
    runtime=Runtime(repo,work,lock); result={'status':'FAILED','native_runtime_test':False,'application_signing_performed':False}
    initial={name:sha(repo/name) for name in lock['source_hashes']}
    manifests={name:sha(repo/name) for name in ('archive/go.mod','archive/go.sum','archivebridge/go.mod','archivebridge/go.sum')}
    try:
        runtime.guard()
        basic={'PATH':'/usr/bin:/bin:/usr/sbin:/sbin','HOME':str(work/'home'),'TMPDIR':str(work/'tmp'),'LC_ALL':'C'}
        developer=os.environ.get('DEVELOPER_DIR','')
        require(developer.startswith('/Applications/') and Path(developer).is_dir(),'preconfigured full Xcode required')
        basic['DEVELOPER_DIR']=developer
        xcode=runtime.run(['/usr/bin/xcodebuild','-version'],repo,basic,'xcode-version',seconds=30).decode()
        require(xcode.splitlines()==['Xcode '+lock['apple']['xcode'],'Build version '+lock['apple']['xcode_build']],'selected Xcode version/build drift')
        for sdk in ('iphoneos','iphonesimulator'):
            runtime.run(['/usr/bin/xcrun','--sdk',sdk,'--show-sdk-path'],repo,basic,sdk+'-sdk',seconds=30)
        runtime.stage='authenticated-go-bootstrap'
        archive=work/'go-darwin-arm64.tar.gz'; download_go(runtime,lock['go'],archive)
        go=extract_go(runtime,archive,work/'toolchain',lock['go']['expanded_limit'])
        env=make_env(work,go,developer)
        shutil.copyfile(work/'toolchain/go/LICENSE',work/'licenses/GO-TOOLCHAIN-LICENSE.txt')
        version=runtime.run([go,'version'],repo,env,'go-version').decode().strip()
        require(version=='go version go1.27.3 darwin/arm64','bootstrapped Go identity mismatch')
        tools_module=work/'tools-module'; make_module(tools_module,'wainak.local/citools',lock)
        runtime.stage='authenticated-public-module-acquisition'
        acquired=acquire_modules(runtime,go,tools_module,env,lock)
        allowed={(r['path'],r['version']) for r in all_rows(lock) if not r.get('metadata_only')}
        graph=inspect_graph(runtime,go,tools_module,env,'tool-input',allowed,{})
        expected={(r['path'],r['version']) for r in lock['input_modules']}
        require({(r['Path'],r.get('Version')) for r in graph['modules'] if not r.get('Main')}==expected,'input26 selected graph changed')
        runtime.run([go,'mod','verify'],tools_module,env,'module-verify')
        runtime.stage='pinned-upstream-tool-build'
        for tool in ('gobind','gomobile'):
            runtime.run([go,'build','-trimpath','-o',work/'bin'/tool,'golang.org/x/mobile/cmd/'+tool],tools_module,env,tool+'-build')
            runtime.run([go,'version','-m',work/'bin'/tool],repo,env,tool+'-buildinfo')
        host_tests=test_host_policy(runtime,go,tools_module,env,lock)
        runtime.stage='unmodified-upstream-apple-bind'
        local={'wainak.local/archivebridge':repo/'archivebridge','wainak.local/historyarchive':repo/'archive'}
        binding=work/'binding'; make_module(binding,'wainak.local/cibinding',lock,local)
        input_graph=inspect_graph(runtime,go,binding,env,'binding-input',allowed,local)
        runtime.run([work/'bin/gomobile','bind','-v','-x','-work','-target=ios/arm64,iossimulator/arm64',
                     '-iosversion=15.0','-o',output,'wainak.local/archivebridge'],binding,env,'apple-bind')
        generated=[]
        target_packages=[]
        for mod in sorted((work/'tmp').rglob('go.mod')):
            if (mod.parent/'gobind').is_dir():
                relative=str(mod.parent.relative_to(work))
                parts=mod.parent.relative_to(work/'tmp').parts
                require(len(parts)==3 and parts[-1]=='src-arm64' and parts[-2] in ('ios','iossimulator'),'unexpected generated target path')
                variant='simulator' if parts[-2]=='iossimulator' else 'device'
                generated.append({'relative_path':relative,
                                  'graph':inspect_graph(runtime,go,mod.parent,env,'target-'+str(len(generated)),allowed,local,generated_main=binding)})
                target_packages.append(inspect_target_packages(runtime,go,mod.parent,env,variant,allowed,local))
        require(len(generated)==2 and {r['variant'] for r in target_packages}=={'device','simulator'},'generated target module evidence absent/ambiguous')
        runtime.stage='artifact-inspection'
        slices=inspect_xcframework(runtime,output,env,lock)
        runtime.run([go,'mod','verify'],tools_module,env,'module-verify-after')
        for row in acquired:
            source=Path(env['GOMODCACHE'])/(row['path']+'@'+row['version'])
            # Module-cache directory casing follows Go's escaped module paths.
            source=Path(env['GOMODCACHE'])/(escaped_module(row['path'])+'@'+row['version'])
            require(file_inventory(source)==row['source_inventory'],'dependency source changed during build')
        result.update({'status':'PASS_UNSIGNED_NATIVE_BUILD_ONLY','source_hashes':initial,'source_manifests':manifests,
                       'go':version,'go_artifact_sha256':lock['go']['sha256'],'xcode':xcode.strip(),
                       'tool_input_graph':graph,'binding_input_graph':input_graph,'generated_target_graphs':generated,
                       'host_tests':host_tests,'target_imported_packages':target_packages,'slices':slices,'artifact_files':file_inventory(output),
                       'module_acquisition':acquired,'licenses_manifest_sha256':digest_file(work/'licenses.json'),
                       'objc_header_sha256':lock['apple']['header_sha256'],'mach_o_minimum_ios':'15.0',
                       'framework_plist_minimum_ios':'100.0','runtime_security_acceptance':False,
                       'native_binary_advisory_scan':'NOT_RUN_BY_THIS_RECIPE',
                       'whole_process_group_cleanup':'OWNED_BY_OUTER_DRIVER'})
    except BaseException as error:
        try:
            result['gate_category'] = classify_gate_error(error)
            reason=graph_failure_reason(error)
            if reason is not None:result['graph_reason']=reason
        except BaseException: result['gate_category'] = 'UNKNOWN_TOOL_FAILURE'
        result.update({'status':'FAILED','failed_stage':runtime.stage,'whole_process_group_cleanup':'REQUIRED_FROM_OUTER_DRIVER'})
        raise
    finally:
        primary=sys.exc_info()[1]
        try: finalize_native_result(runtime,repo,directory,result,initial,manifests,primary)
        finally: runtime.restore()
    print(json.dumps({'status':result['status'],'result_sha256':digest_file(work/'result.json')},sort_keys=True))

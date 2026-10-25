"""Future Apple build implementation; imported only for explicit --build-ios.

No code here is executed by --check. The caller owns this process group and must
TERM/grace>=15s/KILL it on timeout/error, including when this leader has exited.
Children never start another session. No signing, license acceptance, SDK install,
provider calls, vendor patches, go interception, init or latest operations exist.
"""
import base64
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
import subprocess
import tarfile
import time
import urllib.request
from check_static import InvalidRecipe, require, read_regular, read_json, sha, module_id
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
        self.previous={s:signal.signal(s,self.signal) for s in (signal.SIGTERM,signal.SIGINT)}
    def signal(self, number, frame): self.cancelled=True
    def restore(self):
        for sig,handler in self.previous.items(): signal.signal(sig,handler)
    def guard(self):
        if self.cancelled: raise BuildFailure('build cancelled')
        aggregate=sum(byte_size(p) for p in (
            self.repo/'.ci-work',self.repo/'apps/mobile/build',self.repo/'apps/mobile/.dart_tool',
            self.repo/'apps/mobile/ios/Flutter/ephemeral'))
        if aggregate>self.lock['limits']['aggregate_bytes']: raise BuildFailure('workspace budget exceeded')
        if shutil.disk_usage(self.repo).free<self.lock['limits']['minimum_free_bytes']:
            raise BuildFailure('free disk floor exceeded')
        return aggregate
    def run(self, args, cwd, env, name, public_output=True, seconds=None):
        self.guard(); self.sequence+=1; started=time.monotonic(); data=bytearray(); proc=None
        timeout=seconds or self.lock['limits']['process_seconds']
        try:
            # All descendants remain in the outer driver's owned session/group.
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
            self.guard()
            if code: raise BuildFailure('child command failed')
            return bytes(data)
        finally:
            # Direct-child reaping only. Whole-group cleanup is the driver's job.
            if proc is not None:
                if proc.poll() is None:
                    proc.terminate()
                    try: proc.wait(timeout=8)
                    except subprocess.TimeoutExpired: proc.kill(); proc.wait(timeout=2)
                if proc.stdout is not None: proc.stdout.close()
            row={'name':name,'argv':[str(a) for a in args],'exit_code':None if proc is None else proc.returncode,
                 'elapsed_seconds':round(time.monotonic()-started,3),'output_bytes':len(data),
                 'output_sha256':hashlib.sha256(data).hexdigest()}
            self.commands.append(row)
            if public_output:
                (self.work/'logs'/f'{self.sequence:03}-{name}.log').write_bytes(data)
            # Go tests are retained as fixed status/hash only, never raw key-bearing output.
            (self.work/'commands.json').write_text(json.dumps(self.commands,indent=2,sort_keys=True)+'\n')

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
    require(not destination.exists(),'tool extraction destination exists'); destination.mkdir(mode=0o700)
    total=0; names=set()
    with tarfile.open(archive,'r:gz') as tar:
        for member in tar:
            runtime.guard(); p=PurePosixPath(member.name)
            require(not p.is_absolute() and '..' not in p.parts and p.parts and p.parts[0]=='go','unsafe Go archive path')
            require(member.name not in names and len(names)<30000,'duplicate/excess Go archive members'); names.add(member.name)
            require(member.isdir() or member.isfile(),'Go archive links/special files rejected')
            require(member.size>=0,'negative archive size'); total+=member.size
            require(total<=limit,'Go archive expanded bound exceeded')
            output=safe_child(destination,destination.joinpath(*p.parts))
            if member.isdir(): output.mkdir(parents=True,exist_ok=True,mode=0o700); continue
            output.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
            with tar.extractfile(member) as source, output.open('xb') as sink:
                shutil.copyfileobj(source,sink,1024*1024)
            require(output.stat().st_size==member.size,'Go archive member size mismatch')
            output.chmod(0o700 if member.mode&0o111 else 0o600)
    return destination/'go/bin/go'

def make_env(work, go, developer_dir):
    # No inherited credentials, signing settings, proxies, GOFLAGS or persistent Go config.
    return {'HOME':str(work/'home'),'PATH':str(go.parent)+':'+str(work/'bin')+':/usr/bin:/bin:/usr/sbin:/sbin',
            'TMPDIR':str(work/'tmp'),'GOENV':'off','GOTOOLCHAIN':'local','GOWORK':'off','GOTELEMETRY':'off',
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


def inspect_graph(runtime, go, cwd, env, name, allowed, local):
    raw=runtime.run([go,'list','-m','-json','all'],cwd,env,name+'-modules')
    rows=json_stream(raw)
    for row in rows:
        require(not row.get('Error'),'unresolved graph metadata')
        if row.get('Main'): continue
        key=(row['Path'],row.get('Version'))
        if row['Path'] in local:
            require(row.get('Replace',{}).get('Dir')==str(local[row['Path']]),'local source replacement drift')
        else:
            require(key in allowed and not row.get('Replace'),'unapproved public module selected')
    controls=json.loads(runtime.run([go,'mod','edit','-json'],cwd,env,name+'-controls'))
    require(not controls.get('Exclude') and not controls.get('Toolchain'),'unapproved graph controls')
    for replacement in controls.get('Replace') or []:
        require(replacement['Old']['Path'] in local and replacement['New']['Path']==str(local[replacement['Old']['Path']]),
                'unapproved replacement')
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


def test_host_policy(runtime, go, tools_module, env, lock):
    runtime.stage='new-policy-host-tests'
    age=runtime.work/'bin/age'
    runtime.run([go,'build','-trimpath','-o',age,'filippo.io/age/cmd/age'],tools_module,env,'age-cli-build')
    source=runtime.work/'host-source'; source.mkdir()
    local={'wainak.local/historyarchive':source/'archive'}
    results=[]
    for name,module in [('archive','wainak.local/historyarchive'),('archivebridge','wainak.local/archivebridge')]:
        target=source/name
        make_module(target,module,lock,None if name=='archive' else local)
        for path in (runtime.repo/name).glob('*.go'): shutil.copyfile(path,target/path.name)
        testenv=dict(env,WAINAK_ARCHIVE_INTEROP='1',WAINAK_AGE_CLI=str(age),WAINAK_AGE_CLI_SHA256=digest_file(age),
                     WAINAK_ARCHIVE_SCAN_ROOT=str(runtime.work),CGO_ENABLED='0')
        runtime.run([go,'test','-count=1','-timeout=120s','./...'],target,testenv,name+'-tests',public_output=False,seconds=180)
        runtime.run([go,'vet','./...'],target,testenv,name+'-vet',public_output=False,seconds=180)
        results.append({'module':module,'status':'PASS','graph_policy':'explicit-input26','interop_enabled':name=='archive'})
        if name=='archive':
            for fuzz in ('FuzzStrictHistoryJSON','FuzzArchiveOpen'):
                runtime.run([go,'test','-run=^$','-fuzz=^'+fuzz+'$','-fuzztime=10s','-parallel=1'],target,testenv,
                            'fuzz-'+fuzz,public_output=False,seconds=60)
    return results


def inspect_xcframework(runtime, output, env, lock):
    info=plistlib.loads(read_regular(output/'Info.plist'))
    libs=info.get('AvailableLibraries',[]); require(len(libs)==2,'wrong XCFramework slice count')
    observed=set(); results=[]
    functions=['Cancel','Close','Epoch','ExportHistory','HistorySnapshot','ImportHistory','NewSyntheticSession']
    for lib in libs:
        require(lib['SupportedPlatform']=='ios' and lib['SupportedArchitectures']==['arm64'],'unexpected native platform/ABI')
        variant=lib.get('SupportedPlatformVariant','device'); require(variant in ('device','simulator'),'unexpected native variant')
        require(variant not in observed,'duplicate native variant'); observed.add(variant)
        path=PurePosixPath(lib['LibraryIdentifier'])/lib['LibraryPath']
        require(not path.is_absolute() and '..' not in path.parts,'unsafe XCFramework metadata path')
        framework=safe_child(output,output.joinpath(*path.parts)); binary=framework/'Archivebridge'
        require(sha(framework/'Headers/Archivebridge.objc.h')==lock['apple']['header_sha256'],'regenerated ABI header changed')
        modulemap=read_regular(framework/'Modules/module.modulemap').decode()
        validate_modulemap(modulemap,lock['apple']['headers'])
        container=static_arm64_container(binary)
        arch=runtime.run(['/usr/bin/xcrun','lipo','-archs',binary],runtime.repo,env,'slice-architecture').decode().strip()
        require(arch=='arm64','unexpected binary architectures')
        symbols=runtime.run(['/usr/bin/xcrun','nm','-g',binary],runtime.repo,env,'slice-symbols').decode()
        require(all(re.search(r'(?m)^[0-9a-fA-F]+\s+[Tt]\s+_Archivebridge'+name+r'$',symbols) for name in functions),'defined native binding symbols missing')
        loads=runtime.run(['/usr/bin/xcrun','otool','-l',binary],runtime.repo,env,'slice-load-commands').decode()
        load_evidence=validate_apple_load_commands(loads,variant)
        plist=plistlib.loads(read_regular(framework/'Info.plist'))
        require(plist.get('MinimumOSVersion')==lock['apple']['framework_plist_minimum_os_upstream'],'upstream framework metadata changed')
        results.append({'variant':variant,'architectures':['arm64'],'binary_sha256':digest_file(binary),'static_container':container,'load_command_evidence':load_evidence})
    require(observed=={'device','simulator'},'missing Apple slice')
    return results


def build_ios(repo, directory, lock, work, output):
    require(platform.system()=='Darwin' and platform.machine()=='arm64','Apple arm64 host required')
    require(os.getpgrp()==os.getpid(),'outer driver must own this native process group')
    repo=repo.resolve(); expected=repo/'.ci-work/native'
    require(work.absolute()==expected and output.absolute()==expected/'Archivebridge.xcframework','explicit canonical native output required')
    safe_child(repo,work); require(not work.exists(),'native attempt already exists; no implicit cleanup/overwrite')
    os.umask(0o077); work.mkdir(parents=True,mode=0o700)
    for name in ('logs','home','tmp','bin','licenses'): (work/name).mkdir(mode=0o700)
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
                                  'graph':inspect_graph(runtime,go,mod.parent,env,'target-'+str(len(generated)),allowed,local)})
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
    except BaseException:
        result.update({'status':'FAILED','failed_stage':runtime.stage,'whole_process_group_cleanup':'REQUIRED_FROM_OUTER_DRIVER'})
        raise
    finally:
        try:
            require(initial=={name:sha(repo/name) for name in initial},'repository Go source changed')
            require(manifests=={name:sha(repo/name) for name in manifests},'repository module manifests changed')
            result['commands_manifest_sha256']=digest_file(work/'commands.json') if (work/'commands.json').exists() else None
            result['lock_sha256']=sha(directory/'lock.json')
            (work/'result.json').write_text(json.dumps(result,indent=2,sort_keys=True)+'\n')
        finally: runtime.restore()
    print(json.dumps({'status':result['status'],'result_sha256':digest_file(work/'result.json')},sort_keys=True))

"""Pure-stdlib native recipe validation. This module never runs tools or network."""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from ci.rename_provenance import source_matches

EXPECTED_PROOFS = {'proofs/auxiliary-module-metadata.json': '8931cc6885b275384a8c4e27860ffb9bf95494120663513a1f34608140e3f24c', 'proofs/candidate-graph.json': '71ededfd405d45db884cf22cd4f68c378e5995153af36531a9d57a312e54e291', 'proofs/new-module-authenticated-metadata.json': '224205964c8cdaa4b9e5a2132a0a843dd2eb04e17b48835c81db1a69d93a72ee', 'proofs/prior-pins.json': 'b3f6b089001c537e7302626f22217a52740317226ba3c06c06e340f996c4a31b'}
EXPECTED_SOURCE = {'archive/archive.go': '20ed943c8e8a4c4c8f1b3c19c422c3530678302b408884c8c311b71efa0d639e', 'archive/archive_test.go': 'ec0aa6352375e556b411ff0bfcc33c27acf8d90f7ae9877fbdc33fb42d51ead0', 'archive/interop_test.go': '80061c03c2bcc19d2f709a6ff131d162dc5573ab3e5ff331ff910d02d4304072', 'archivebridge/bridge.go': '3cf7dcf2f25454bcf3c16dd3a6189382babcb93fe7fb2913a60383aeb48df415', 'archivebridge/bridge_test.go': 'c58856dcf372791b03553924111ae9c403afb0501ceacf3bc230a6ffafdc52a1'}

EXPECTED_SOURCE_MODULES = {'archive/go.mod': '68e37b3d448d929b2a6ac03a0d0364e851b1b9e1cf6cf67f1ab4e12b7a154823', 'archivebridge/go.mod': '8fe3d9077d27830843a138ad522156fa367a922039e61b50761275c858dedf3e', 'archive/go.sum': 'ce89bc3d29b0b26309dfe62825689c4fa82314f29fecf4bc22088b63d084ec4f', 'archivebridge/go.sum': '40b1ef66457e931191a49c57d4b0b272b4cb1fd632b06d390c74cac5436bb634'}
EXPECTED_LICENSE_EXCEPTIONS = [{'file': 'README.md', 'path': 'c2sp.org/CCTV/age', 'sha256': 'fdbd4b06044f3803c72bdaf2df7681fdce3a45a326a2898e75640eae906606ad', 'version': 'v0.0.0-20260829155415-4448f2097b2d'}]
SOURCE_DOCUMENTATION = frozenset({'archive/README.md', 'archivebridge/README.md'})

class InvalidRecipe(ValueError):
    pass

def require(ok, message):
    if not ok:
        raise InvalidRecipe(message)

def unique(pairs):
    out = {}
    for key, value in pairs:
        require(key not in out, 'duplicate JSON key')
        out[key] = value
    return out

def read_regular(path, bound=1024*1024):
    flags = os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0)
    require(not path.is_symlink(), 'symlink input rejected')
    fd = os.open(path, flags)
    try:
        meta = os.fstat(fd)
        require(stat.S_ISREG(meta.st_mode), 'input is not a regular nonsymlink file')
        require(meta.st_size <= bound, 'input size bound exceeded')
        data = bytearray()
        while len(data) <= bound:
            chunk = os.read(fd, min(65536, bound + 1 - len(data)))
            if not chunk: break
            data.extend(chunk)
        require(len(data) <= bound, 'input size bound exceeded')
        return bytes(data)
    finally:
        os.close(fd)

def sha(path):
    return hashlib.sha256(read_regular(path)).hexdigest()

def read_json(path):
    return json.loads(read_regular(path).decode('utf-8'), object_pairs_hook=unique,
                      parse_constant=lambda _: require(False, 'nonfinite JSON'))

def module_id(row):
    path, version = row['path'], row['version']
    require(re.fullmatch(r'[A-Za-z0-9._~/-]+', path) is not None, 'invalid public module path')
    require(not path.startswith(('wainek.local/','wainak.local/')) and '..' not in path.split('/'), 'nonpublic module identity')
    require(re.fullmatch(r'v[0-9]+\.[0-9]+\.[0-9]+(?:-[A-Za-z0-9.-]+)?(?:\+incompatible)?', version) is not None,
            'unversioned module')
    for name in ('sum','go_mod_sum'):
        require(row[name].startswith('h1:'), 'missing module checksum')
        require(len(base64.b64decode(row[name][3:], validate=True)) == 32, 'invalid module checksum')
    require(re.fullmatch('[0-9a-f]{64}', row['go_mod_sha256']) is not None, 'invalid metadata digest')
    return path, version

def validate_lock(lock, directory):
    require(lock['status'] == 'INPUT_MVS_VERIFIED_SOURCE_NOT_ACQUIRED_TARGET_NOT_RUN', 'preparation status drift')
    require(lock['schema'] == 1 and lock['scope'] == 'synthetic-history-only-ios-source-preparation', 'wrong recipe scope')
    require(lock['go']['version'] == '1.27.3' and lock['go']['bytes'] == 68196737, 'Go pin drift')
    require(lock['go']['url'] == 'https://dl.google.com/go/go1.27.3.darwin-arm64.tar.gz', 'unapproved Go source')
    require(lock['go']['sha256'] == 'dd3908cf20959d798c1e06ebe5b72213f0505ce01373b40ce3110975a6cd99c2', 'Go artifact pin drift')
    require(lock['mobile']['version'] == 'v0.0.0-20261011034528-197770444867', 'mobile pin drift')
    require(lock['apple']['targets'] == ['ios/arm64','iossimulator/arm64'] and lock['apple']['minimum_ios'] == '15.0', 'Apple target drift')
    require(lock['apple']['module'] == 'Archivebridge', 'framework naming drift')
    require(lock['apple']['xcode']=='26.4.1' and lock['apple']['xcode_build']=='17E202', 'Xcode pin drift')
    require(lock['source_hashes']==EXPECTED_SOURCE, 'source provenance pins changed')
    require(lock['source_module_hashes']==EXPECTED_SOURCE_MODULES, 'source module pins changed')
    require(lock['license_path_exceptions']==EXPECTED_LICENSE_EXCEPTIONS, 'license path exception changed')
    require(lock['proof_files']==EXPECTED_PROOFS, 'reviewed proof pins changed')
    rows = lock['input_modules']; ids = [module_id(row) for row in rows]
    require(len(ids) == len(set(ids)) == 26, 'input graph identities changed')
    versions = dict(ids)
    for path, version in [('golang.org/x/crypto','v0.58.0'),('golang.org/x/sys','v0.49.0'),
                          ('filippo.io/age','v1.3.2'),('github.com/evanw/esbuild','v0.28.2')]:
        require(versions.get(path) == version, 'runtime/advisory policy drift')
    aux = [module_id(row) for row in lock['auxiliary_modules']]
    require(set(aux) == {('golang.org/x/sys','v0.0.0-20220715151400-c0bba94af5f8'),
                         ('golang.org/x/net','v0.60.0')}, 'auxiliary allowlist drift')
    for name, digest in lock['proof_files'].items():
        p = Path(name)
        require(p.parts[0] == 'proofs' and not p.is_absolute() and '..' not in p.parts, 'unsafe proof path')
        require(sha(directory/p) == digest, 'retained proof bytes changed')
    candidate=read_json(directory/'proofs/candidate-graph.json')
    fixed={(r['path'],r['version']):r for r in candidate['public_modules']}
    prior=read_json(directory/'proofs/prior-pins.json')
    fresh=read_json(directory/'proofs/new-module-authenticated-metadata.json')
    auxiliary=read_json(directory/'proofs/auxiliary-module-metadata.json')
    evidence={(r['path'],r['version']):r for r in prior['modules']+fresh['modules']}
    require(set(ids)==set(fixed), 'selected input graph differs from reviewed MVS candidate')
    for row in rows:
        require(set(row)=={'path','version','sum','go_mod_sum','go_mod_sha256'},'unexpected input module controls')
        key=(row['path'],row['version']); source=evidence[key]
        expected_sum=source['sum'] if 'sum' in source else source['proof']['h1']
        require(row['sum']==expected_sum and row['go_mod_sum']==source['go_mod_sum'] and row['go_mod_sha256']==fixed[key]['go_mod_sha256'],
                'input module integrity differs from immutable proof')
    aux_evidence={(r['path'],r['version']):r for r in auxiliary['modules']}
    for row in lock['auxiliary_modules']:
        source=aux_evidence[(row['path'],row['version'])]
        require(row['sum']==source['proof']['h1'] and row['go_mod_sum']==source['go_mod_sum'] and row['go_mod_sha256']==source['go_mod_sha256'],
                'auxiliary integrity differs from immutable proof')
        require(row['metadata_only']==(row['path']=='golang.org/x/sys'), 'auxiliary source acquisition policy changed')
        require(row['info']==source['info'], 'auxiliary info changed')
        raw = row['go_mod'].encode()
        require(hashlib.sha256(raw).hexdigest() == row['go_mod_sha256'], 'auxiliary metadata changed')
        h = 'h1:'+base64.b64encode(hashlib.sha256((hashlib.sha256(raw).hexdigest()+'  go.mod\n').encode()).digest()).decode()
        require(h == row['go_mod_sum'], 'auxiliary Hash1 mismatch')
    notices = read_json(directory/'notice-manifest.json')
    for row in notices['licenses']:
        require(Path(row['path']).parts[0] == 'notices' and '..' not in Path(row['path']).parts, 'unsafe notice path')
        require(sha(directory/row['path']) == row['sha256'], 'retained notice changed')
    return lock

def validate_source_inventory(repo, hashes):
    """Reject any additional file in a compiled source directory, tracked or not.

    The notices directory and two exact README paths are non-compiler input.
    README files must be bounded regular UTF-8 text; no Markdown wildcard is
    permitted. Host modules copy only the separately pinned source allowlist.
    """
    expected=set(hashes)
    found=set()
    for module in ('archive','archivebridge'):
        root=repo/module
        require(root.is_dir() and not root.is_symlink(),'source directory boundary')
        with os.scandir(root) as entries:
            for entry in entries:
                relative=module+'/'+entry.name
                info=entry.stat(follow_symlinks=False)
                if module=='archive' and entry.name=='notices':
                    require(stat.S_ISDIR(info.st_mode),'source notices boundary')
                    continue
                require(stat.S_ISREG(info.st_mode),'source entry type changed')
                if relative in SOURCE_DOCUMENTATION:
                    read_regular(repo/relative,128*1024).decode('utf-8')
                    continue
                require(relative in expected or entry.name in ('go.mod','go.sum'),
                        'unreviewed source input present')
                if relative in expected: found.add(relative)
    require(found==expected,'reviewed source inventory changed')
    return found

def validate_sources(repo, lock):
    validate_source_inventory(repo, lock['source_hashes'])
    for relative, digest in lock['source_hashes'].items():
        require(source_matches(repo,relative,digest), 'reviewed Go source/test bytes changed')
    for relative,digest in lock['source_module_hashes'].items():
        require(source_matches(repo,relative,digest), 'source module/sum bytes changed')
    for relative in ('archive/go.mod','archivebridge/go.mod'):
        require(source_matches(repo,relative,lock['source_module_hashes'][relative]), 'source module bytes changed')
        text = read_regular(repo/relative).decode()
        require(re.search(r'^go 1\.27\.3$', text, re.M) is not None, 'source Go version changed')
        for path, version in [('filippo.io/age','v1.3.2'),('golang.org/x/crypto','v0.58.0'),('golang.org/x/sys','v0.49.0')]:
            require(re.search(r'(?m)^\s*(?:require )?'+re.escape(path)+r'\s+'+re.escape(version)+r'(?:\s|$)', text) is not None,
                    'source manifest does not pin reviewed runtime policy')
        replacements = [line.strip() for line in text.splitlines() if line.startswith('replace ')]
        require(replacements == ([] if relative.startswith('archive/') else ['replace wainek.local/historyarchive => ../archive']),
                'unexpected source replacement')
        require(not re.search(r'(?m)^(exclude|toolchain)\s', text), 'unexpected source graph control')
    return {'status':'PASS_STATIC_SOURCE_PREPARATION_ONLY','input_modules':26,'native_build_run':False}

def check(directory, repo=None):
    lock = validate_lock(read_json(directory/'lock.json'), directory)
    if repo is not None:
        validate_sources(repo, lock)
    return lock

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', required=True)
    args=parser.parse_args()
    root=Path(__file__).resolve().parent
    check(root, root.parents[1])
    print(json.dumps({'status':'PASS_STATIC_SOURCE_PREPARATION_ONLY','native_build_run':False},sort_keys=True))

if __name__ == '__main__':
    main()

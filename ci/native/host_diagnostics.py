"""Fixed public test diagnostics; untrusted Go JSON Output is never returned."""
import json
import math
import re
import hashlib
from check_static import read_regular, require

HOST_COMMANDS = frozenset({'age-cli-build', 'archive-test-compile', 'archive-tests', 'archive-vet',
 'fuzz-FuzzStrictHistoryJSON', 'fuzz-FuzzArchiveOpen', 'archivebridge-test-compile',
 'archivebridge-tests', 'archivebridge-vet'})
FAILURE_KINDS = frozenset({'NONE','NONZERO_EXIT','TIMEOUT','CANCELLED','OUTPUT_BOUND',
 'RESOURCE_GUARD','SPAWN_OR_IO','CLEANUP','OTHER'})
FAILURE_CATEGORIES = frozenset({'MALFORMED_TEST_JSON','INCOMPLETE_TEST_JSON','TEST_FAILURE',
 'NO_TEST_FAILURE_EVENT','COMPILE_PHASE_FAILURE'})

def declared_tests(repo, source_hashes):
    result={'wainak.local/historyarchive':set(),'wainak.local/archivebridge':set()}
    for relative in ('archive/archive_test.go','archive/interop_test.go','archivebridge/bridge_test.go'):
        data=read_regular(repo/relative,1024*1024)
        require(hashlib.sha256(data).hexdigest()==source_hashes.get(relative),'test declaration source changed')
        package='wainak.local/archivebridge' if relative.startswith('archivebridge/') else 'wainak.local/historyarchive'
        result[package].update(re.findall(r'^func ((?:Test|Fuzz)[A-Za-z0-9_]+)\(',data.decode('utf-8'),re.M))
    return {package:frozenset(names) for package,names in result.items()}

def event_json(line):
    text=line.decode('utf-8'); depth=0; quoted=escaped=False
    for char in text:
        if quoted:
            if escaped: escaped=False
            elif char=='\\': escaped=True
            elif char=='"': quoted=False
        elif char=='"': quoted=True
        elif char in '[{':
            depth+=1
            if depth>32: raise ValueError()
        elif char in ']}':
            depth-=1
            if depth<0: raise ValueError()
    def pairs(items):
        result={}
        for key,value in items:
            if key in result: raise ValueError()
            result[key]=value
        return result
    def constant(value): raise ValueError()
    return json.loads(text,object_pairs_hook=pairs,parse_constant=constant)

def project_go_events(raw, names, package):
    failed=set(); categories=set(); failure_event=False; terminal=None
    lines=raw.splitlines()
    if not raw or not raw.endswith(b'\n'): categories.add('INCOMPLETE_TEST_JSON')
    if len(lines)>10000:
        categories.add('MALFORMED_TEST_JSON');lines=[]
    for line in lines:
        if len(line)>262144:
            categories.add('MALFORMED_TEST_JSON'); continue
        try:
            row=event_json(line)
            if type(row) is not dict or row.get('Package')!=package: raise ValueError()
            action=row.get('Action')
            if action not in {'start','run','pause','cont','pass','bench','fail','output','skip'}: raise ValueError()
            if 'Test' in row and (type(row['Test']) is not str or len(row['Test'])>512): raise ValueError()
        except (ValueError,TypeError,RecursionError):
            categories.add('MALFORMED_TEST_JSON'); continue
        # Output, FailedBuild, paths and all unknown fields are ignored.
        test=row.get('Test')
        if terminal is not None: categories.add('MALFORMED_TEST_JSON')
        if action in ('pass','fail') and test is None: terminal=action
        if action=='fail':
            failure_event=True; categories.add('TEST_FAILURE')
            top=test.split('/',1)[0] if isinstance(test,str) else None
            if top in names: failed.add(top)
    if terminal is None: categories.add('INCOMPLETE_TEST_JSON')
    proof_ok=terminal=='pass' and not categories
    return {'failed_tests':sorted(failed),'failure_categories':sorted(categories)},failure_event,proof_ok

def safe_last_command(name, code, elapsed, outcome, failure_kind, projection=None):
    if name not in HOST_COMMANDS: return None
    if type(code) is not int or not -255<=code<=255: code=None
    elapsed=float(elapsed)
    if not math.isfinite(elapsed) or not 0<=elapsed<=3600: elapsed=3600.0
    result={'name':name,'exit_code':code,'elapsed_seconds':round(elapsed,3),
            'outcome':outcome if outcome in ('PASS','FAILED') else 'FAILED',
            'failure_kind':failure_kind if failure_kind in FAILURE_KINDS else 'OTHER',
            'failed_tests':[],'failure_categories':[]}
    if projection:
        result.update(projection)
    return result

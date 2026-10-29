"""Project unittest failures onto test IDs declared in public source only."""
import ast
from pathlib import Path
import re

PROFILE='public_unittest_failures'
ROOT=Path(__file__).resolve().parents[1]
STATUSES=frozenset({'IDENTIFIED','UNCLASSIFIED','CLASSIFIER_FAILED'})


def catalogue():
    names=set()
    for path in (ROOT/'ci/tests').glob('test_*.py'):
        names.add('unittest.loader._FailedTest.'+path.stem)
        tree=ast.parse(path.read_text())
        for node in tree.body:
            if isinstance(node,ast.ClassDef):
                for method in node.body:
                    if isinstance(method,(ast.FunctionDef,ast.AsyncFunctionDef)) and method.name.startswith('test_'):
                        names.add(path.stem+'.'+node.name+'.'+method.name)
    return names


def project(value,allowed):
    fallback={'status':'CLASSIFIER_FAILED','failures':[],'errors':[],'tests_run':None}
    if type(value) is not dict or type(value.get('status')) is not str or value['status'] not in STATUSES:return fallback
    result={'status':value['status']}
    for field in ('failures','errors'):
        items=value.get(field)
        if type(items) is not list or len(items)>128 or any(type(x) is not str or x not in allowed for x in items):return fallback
        result[field]=sorted(set(items))
    count=value.get('tests_run')
    if count is not None and (type(count) is not int or not 0<=count<=100000):return fallback
    result['tests_run']=count
    return result


def safe_project(value):
    try:return project(value,catalogue())
    except Exception:return {'status':'CLASSIFIER_FAILED','failures':[],'errors':[],'tests_run':None}


def classify(output,allowed):
    result={'status':'UNCLASSIFIED','failures':[],'errors':[],'tests_run':None}
    if type(output) not in (bytes,bytearray) or len(output)>16*1024**2:return result
    # Nothing matched from an exception, filename, message, subtest parameter,
    # arbitrary numeric value, or environment is ever returned.
    for line in bytes(output).splitlines():
        if len(line)>4096:continue
        text=line.decode('ascii',errors='replace')
        count=re.fullmatch(r'Ran ([0-9]{1,5}) tests? in [0-9.]+s',text)
        if count:result['tests_run']=int(count[1])
        match=re.match(r'^(FAIL|ERROR): (test_[A-Za-z0-9_]+) \(([A-Za-z0-9_.]+)\)(?: |$)',text)
        if not match:continue
        name=match[3].removeprefix('ci.tests.')
        if name in allowed and name.rsplit('.',1)[-1]==match[2]:
            field='failures' if match[1]=='FAIL' else 'errors'
            if name not in result[field] and len(result[field])<128:result[field].append(name)
    if result['failures'] or result['errors']:result['status']='IDENTIFIED'
    return project(result,allowed)

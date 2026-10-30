"""Finite observations from read-only security queries; never return input text."""
import json
import re

CONTEXTS=frozenset({'ISOLATED','ACCOUNT'})
PHASES=frozenset({'AFTER_SELECT','BEFORE_ARCHIVE'})
COMMANDS={
    'keychain_search_isolated':('/usr/bin/security','list-keychains','-d','user'),
    'identity_search_isolated':('/usr/bin/security','find-identity','-v','-p','codesigning'),
    'keychain_search_account':('/usr/bin/security','list-keychains','-d','user'),
    'identity_search_account':('/usr/bin/security','find-identity','-v','-p','codesigning'),
}


def lines(text):
    if type(text) is not str or len(text)>65536:return None
    result=[line.strip() for line in text.splitlines() if line.strip()]
    if len(result)>129 or any(len(line)>4096 for line in result):return None
    return result


def search_list(text,owned,expected):
    unknown={'status':'UNCLASSIFIED','count':None,'owned_present':None,'matches_expected':None}
    rows=lines(text)
    if rows is None or len(rows)>32:return unknown
    paths=[]
    for line in rows:
        match=re.fullmatch(r'"(/[^"\x00-\x1f]{0,4095})"',line)
        if not match:return unknown
        paths.append(match[1])
    if len(set(paths))!=len(paths):return unknown
    return {'status':'OBSERVED','count':len(paths),'owned_present':str(owned) in paths,
            'matches_expected':paths==list(expected)}


def identities(text,pin):
    unknown={'status':'UNCLASSIFIED','count':None,'pinned_present':None}
    rows=lines(text)
    if not rows:return unknown
    final=re.fullmatch(r'([0-9]{1,3}) valid identities found',rows[-1])
    if not final or int(final[1])>128 or int(final[1])!=len(rows)-1:return unknown
    hashes=[]
    for index,line in enumerate(rows[:-1],1):
        match=re.fullmatch(r'([0-9]{1,3})\) ([A-Fa-f0-9]{40}) "[^"\x00-\x1f]{1,2048}"',line)
        if not match or int(match[1])!=index:return unknown
        hashes.append(match[2].upper())
    if len(set(hashes))!=len(hashes):return unknown
    return {'status':'OBSERVED','count':len(hashes),'pinned_present':pin.upper() in hashes}


def emit(phase,context,query,result):
    # Fixed call-site labels and independently projected field types. A parser
    # regression must not make arbitrary dictionaries or strings loggable.
    if phase not in PHASES or context not in CONTEXTS or query not in {'SEARCH_LIST','IDENTITIES'}:
        raise ValueError('signed_keychain_probe_command')
    fields={'count','owned_present','matches_expected'} if query=='SEARCH_LIST' else {'count','pinned_present'}
    maximum=32 if query=='SEARCH_LIST' else 128
    valid=(type(result) is dict and set(result)=={'status',*fields} and
        type(result.get('status')) is str and result['status'] in {'OBSERVED','UNCLASSIFIED'} and
        (result.get('count') is None or type(result.get('count')) is int and 0<=result['count']<=maximum) and
        all(result.get(k) is None or type(result.get(k)) is bool for k in fields-{'count'}))
    if valid:
        valid=(all(result[k] is None for k in fields) if result['status']=='UNCLASSIFIED'
               else all(result[k] is not None for k in fields))
    if not valid:result={'status':'UNCLASSIFIED',**{key:None for key in fields}}
    print(json.dumps({'event':'GITHUB_KEYCHAIN_DISCOVERY','phase':phase,'context':context,'query':query,**result}),flush=True)

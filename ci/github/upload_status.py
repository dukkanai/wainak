"""Finite import-state diagnostics. Never return Apple descriptions or paths."""
import re
from ci.testflight import policy as p

STATES=frozenset({'AWAITING_UPLOAD','PROCESSING','FAILED','COMPLETE'})
CODES=frozenset({'90022','90023','90035','90056','90057','90078','90161','90165',
    '90179','90186','90205','90206','90209','90210','90236','90426','90683','90725',
    '90771','90788','90863','90907','91053','91054','91109'})
PATTERNS={
    'ICON_MISSING':r'missing required icon|missing app icon',
    'ICON_ALPHA':r'(?:icon|app icon).{0,128}(?:alpha|transparen)|(?:alpha|transparen).{0,128}(?:icon|app icon)',
    'ICON_DIMENSIONS':r'icon.{0,128}(?:dimension|size|[0-9]+x[0-9]+)',
    'INVALID_SIGNATURE':r'invalid (?:code )?signature|code signing entitlements are invalid',
    'SDK_UNSUPPORTED':r'sdk version|sdk.{1,80}(?:not supported|require|invalid)|built with.{0,80}(?:beta|pre-release)',
    'PRIVACY_USAGE':r'missing purpose string|missing.{0,128}NS[A-Za-z]{1,64}UsageDescription',
    'PRIVACY_MANIFEST':r'privacy manifest|NSPrivacy',
    'BUNDLE_METADATA':r'Info\.plist|CFBundle|bundle identifier',
    'MACHO_INVALID':r'invalid (?:binary|Mach-O)|unsupported architecture|invalid segment alignment',
    'ENCRYPTION_METADATA':r'encryption info|export compliance|cryptography',
}


def details(values):
    if values is None:return {'count':None,'codes':[],'categories':[]}
    p.require(type(values) is list and len(values)<=100 and all(type(x) is dict for x in values),'asc_response')
    codes=set();categories=set()
    for value in values:
        code=value.get('code');description=value.get('description')
        if type(code) is str:
            code=code.removeprefix('ITMS-')
            codes.add(code if code in CODES else 'OTHER')
        else:codes.add('OTHER')
        matched=False
        if type(description) is str and len(description)<=4096:
            for category,pattern in PATTERNS.items():
                if re.search(pattern,description,re.I):categories.add(category);matched=True
        if not matched:categories.add('UNCLASSIFIED')
    return {'count':len(values),'codes':sorted(codes),'categories':sorted(categories)}


def project(payload,number):
    p.require(type(payload) is dict and type(payload.get('data')) is list and len(payload['data'])<=10,'asc_response')
    uploads=[]
    for item in payload['data']:
        p.require(type(item) is dict and item.get('type')=='buildUploads','asc_response')
        attributes=item.get('attributes');p.require(type(attributes) is dict,'asc_response')
        p.require(attributes.get('cfBundleVersion')==number and attributes.get('cfBundleShortVersionString')=='0.1.0'
                  and attributes.get('platform')=='IOS','asc_response')
        state=attributes.get('state');p.require(type(state) is dict,'asc_response')
        value=state.get('state')
        uploads.append({'state':value if type(value) is str and value in STATES else 'OTHER',
            'errors':details(state.get('errors',[])),'warnings':details(state.get('warnings',[])),
            'info_count':details(state.get('infos',[]))['count']})
    return {'event':'ASC_UPLOAD_STATUS','app_id':p.ASC_APP_ID,'build_number':number,
            'version':'0.1.0','returned_uploads':len(uploads),'uploads':uploads}

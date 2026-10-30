"""Finite Apple error/group diagnostics. Never return descriptions or paths."""
import re
from ci.testflight import policy as p

CODES=frozenset({'90022','90023','90035','90056','90057','90078','90161','90165',
    '90179','90186','90205','90206','90209','90210','90236','90426','90683','90725',
    '90771','90788','90863','90907','91053','91054','91109','STATE_ERROR','ENTITY_ERROR',
    'ENTITY_ERROR.ATTRIBUTE.INVALID','ENTITY_ERROR.ATTRIBUTE.UNKNOWN','ENTITY_ERROR.ATTRIBUTE.REQUIRED',
    'ENTITY_ERROR.ATTRIBUTE.INVALID.DUPLICATE','ENTITY_ERROR.RELATIONSHIP.INVALID',
    'ENTITY_ERROR.RELATIONSHIP.REQUIRED','PARAMETER_ERROR.INVALID','PARAMETER_ERROR.REQUIRED',
    'FORBIDDEN_ERROR','NOT_FOUND','UNEXPECTED_ERROR','METHOD_NOT_ALLOWED'})
PATTERNS={
    'METHOD_NOT_ALLOWED':r'(?:request|http).{0,20}method.{0,64}(?:not valid|not allowed|invalid)',
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
    'ENCRYPTION_DECLARATION':r'encryption|usesNonExemptEncryption',
    'ATTRIBUTE_NOT_EDITABLE':r'not editable|read.only|cannot be (?:changed|modified)|no longer.{0,80}(?:modifi|chang|edit)',
    'INVALID_ATTRIBUTE':r'attribute.{0,128}invalid|invalid.{0,128}attribute',
    'UNSUPPORTED_ATTRIBUTE':r'(?:attribute|field).{0,100}(?:not allowed|not valid|unknown|not supported|unrecognized)',
    'INTERNAL_ONLY_RESTRICTION':r'internal.?only',
    'RELATED_RESOURCE_MISSING':r'relationship.{0,128}(?:missing|not found|required)|(?:missing|required).{0,128}relationship',
    'AGREEMENT_REQUIRED':r'agreement|contract|accept.{0,50}terms',
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


def project_groups(payload):
    p.require(type(payload) is dict and type(payload.get('data')) is list and len(payload['data'])<=100,'asc_response')
    groups=[];external=0
    for row in payload['data']:
        p.require(type(row) is dict and row.get('type')=='betaGroups' and type(row.get('attributes')) is dict,'asc_response')
        values=row['attributes'];internal=values.get('isInternalGroup')
        p.require(type(internal) is bool,'asc_response')
        if not internal:external+=1;continue
        identifier=row.get('id')
        p.require(type(identifier) is str and re.fullmatch('[a-fA-F0-9]{8}(?:-[a-fA-F0-9]{4}){3}-[a-fA-F0-9]{12}',identifier),'asc_response')
        name=values.get('name')
        group={'group_id':identifier,'name_class':{'App Store Connect Users':'DEFAULT','wainek Internal':'WAINEK_INTERNAL'}.get(name,'OTHER') if type(name) is str else 'OTHER'}
        for source,target in (('publicLinkEnabled','public_link_enabled'),('hasAccessToAllBuilds','all_builds')):
            value=values.get(source);p.require(value is None or type(value) is bool,'asc_response');group[target]=value
        groups.append(group)
    return {'event':'ASC_INTERNAL_GROUPS','app_id':p.ASC_APP_ID,'internal_groups':groups,'external_group_count':external}

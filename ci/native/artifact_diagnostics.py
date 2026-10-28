"""Bounded, value-free artifact observations; never accepts an artifact itself."""
import re
ABI_NAMES = ('Cancel','Close','Epoch','ExportHistory','HistorySnapshot','ImportHistory','NewSyntheticSession')
CHECKS = frozenset({'metadata','slice_metadata','path','header','modulemap','container','architecture','symbols','load_commands','framework_plist','binary_hash','variants'})
REASONS = frozenset({'NONE','METADATA','PLATFORM_ABI','VARIANT','DUPLICATE_VARIANT','PATH','HEADER','MODULEMAP','CONTAINER','ARCHITECTURE','SYMBOLS','LOAD_PLATFORM','LOAD_MINIMUM','LOAD_RECORD','FRAMEWORK_PLIST','VARIANTS','IO','DECODE','SHAPE','UNKNOWN'})
MESSAGE_REASONS = {
 'wrong XCFramework slice count':'METADATA','unexpected native platform/ABI':'PLATFORM_ABI',
 'unexpected native variant':'VARIANT','duplicate native variant':'DUPLICATE_VARIANT',
 'unsafe XCFramework metadata path':'PATH','path escapes owned root':'PATH','unsafe path component':'PATH','symlink in owned path':'PATH',
 'regenerated ABI header changed':'HEADER','unexpected framework module-map semantics':'MODULEMAP',
 'unexpected binary architectures':'ARCHITECTURE','defined native binding symbols missing':'SYMBOLS',
 'upstream framework metadata changed':'FRAMEWORK_PLIST','missing Apple slice':'VARIANTS',
 'actual Mach-O platform conflicts with slice metadata':'LOAD_PLATFORM','foreign legacy minimum-OS record':'LOAD_PLATFORM',
 'actual Mach-O minimum iOS is not15':'LOAD_MINIMUM','no actual LC_BUILD_VERSION platform evidence':'LOAD_RECORD',
 'malformed Apple build-version record':'LOAD_RECORD','malformed legacy minimum-OS record':'LOAD_RECORD','invalid requested Apple variant':'VARIANT',
}
CONTAINER_MESSAGES = frozenset({'native archive bytes required','truncated native archive','native binary is neither static ar nor supported FAT','only one arm64 architecture is allowed per platform slice','truncated FAT table','nonzero FAT64 reserved field','only generic arm64 static slices are allowed','invalid FAT alignment','invalid FAT bounds','overlapping FAT entries','FAT payload is not a static ar archive'})

def reason(error):
    if isinstance(error,UnicodeError): return 'DECODE'
    if isinstance(error,OSError): return 'IO'
    args=getattr(error,'args',())
    message=args[0] if type(args) is tuple and len(args)==1 and type(args[0]) is str and len(args[0])<=160 else None
    if message in CONTAINER_MESSAGES:return 'CONTAINER'
    return MESSAGE_REASONS.get(message,'SHAPE' if isinstance(error,(KeyError,TypeError,ValueError)) else 'UNKNOWN')

def strict_symbols_present(text):
    # Deliberately unchanged acceptance expression from the preceding recipe.
    return all(re.search(r'(?m)^[0-9a-fA-F]+\s+[Tt]\s+_Archivebridge'+name+r'$',text) for name in ABI_NAMES)

def symbol_summary(text):
    result={'defined':[],'undefined':[],'nontext':[],'missing':[],'hex_text':[],'addressless_text':[],'unrecognized':[],
            'format_counts':{'bsd':0,'posix':0,'darwin':0,'other':0},'complete':True}
    if type(text) is not str or len(text)>8*1024*1024:
        result['complete']=False;return result
    found={key:set() for key in ('defined','undefined','nontext')}
    fullnames={'_Archivebridge'+name:name for name in ABI_NAMES}
    hex_text=set();addressless=set();unrecognized=set()
    lines=text.splitlines()
    if len(lines)>100000:result['complete']=False
    for line in lines[:100000]:
        if len(line)>4096:
            result['complete']=False;result['format_counts']['other']+=1;continue
        parts=line.split();style=None;kind=None;name=None;address=None
        # Tokenized fixed field forms avoid overlapping-whitespace regex work.
        if len(parts)==3 and parts[2] in fullnames and len(parts[1])==1 and re.fullmatch(r'[0-9a-fA-F]+|-+',parts[0]):
            style='bsd';address=parts[0];kind=parts[1];name=parts[2]
        elif len(parts)==2 and parts[1] in fullnames and len(parts[0])==1:
            style='bsd';kind=parts[0];name=parts[1]
        elif 2<=len(parts)<=4 and parts[0] in fullnames and len(parts[1])==1 and all(re.fullmatch(r'[0-9a-fA-F]+|-+',v) for v in parts[2:]):
            style='posix';kind=parts[1];name=parts[0]
        elif parts and parts[-1] in fullnames and 'external' in parts:
            section=next((v for v in parts if v.startswith('(') and v.endswith(')')),None)
            if section is not None:
                style='darwin';name=parts[-1];kind='U' if section=='(undefined)' else ('T' if section=='(__TEXT,__text)' else 'D')
        if style is None or kind not in 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz?':
            result['format_counts']['other']+=1
            for token in parts:
                if token in fullnames:unrecognized.add(fullnames[token])
            continue
        result['format_counts'][style]+=1
        group='defined' if kind in ('T','t') else ('undefined' if kind in ('U','u') else 'nontext')
        short=fullnames[name];found[group].add(short)
        if kind in ('T','t') and style=='bsd':
            (hex_text if address and re.fullmatch(r'[0-9a-fA-F]+',address) else addressless).add(short)
    for key,value in found.items():result[key]=sorted(value)
    result['hex_text']=sorted(hex_text);result['addressless_text']=sorted(addressless);result['unrecognized']=sorted(unrecognized)
    result['missing']=sorted(set(ABI_NAMES)-set.union(*found.values())-unrecognized)
    return result


def load_summary(text):
    counts={key:0 for key in ('build_records','legacy_records','platform_device','platform_simulator','platform_other','minimum_match','minimum_other')}
    result={'counts':counts,'complete':True}
    if type(text) is not str or len(text)>8*1024*1024:result['complete']=False;return result
    current={}
    def finish():
        name=current.get('cmd','')
        if name=='LC_BUILD_VERSION':
            counts['build_records']+=1
            value=current.get('platform','').upper().replace('_','')
            counts['platform_device' if value in ('2','IOS','PLATFORMIOS') else ('platform_simulator' if value in ('7','IOSSIMULATOR','PLATFORMIOSSIMULATOR') else 'platform_other')]+=1
            minimum=current.get('minos')
        elif name.startswith('LC_VERSION_MIN_'):
            counts['legacy_records']+=1;minimum=current.get('version')
        else:return
        counts['minimum_match' if minimum in ('15.0','15.0.0') else 'minimum_other']+=1
    lines=text.splitlines()
    if len(lines)>100000:result['complete']=False
    for line in lines[:100000]:
        if len(line)>4096:result['complete']=False;continue
        parts=line.split()
        if len(parts)==3 and parts[:2]==['Load','command'] and parts[2].isdigit():
            finish();current={}
        elif len(parts)==2 and parts[0] in ('cmd','platform','minos','version'):
            current.setdefault(parts[0],parts[1])
    finish()
    return result

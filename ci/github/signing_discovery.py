"""Read-only filesystem metadata and Foundation home booleans; no credential reads."""
import ctypes
import json
import os
from pathlib import Path
import stat
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from ci.github import internal_policy as q

PROFILE_DIRS=('Library/MobileDevice/Provisioning Profiles','Library/Developer/Xcode/UserData/Provisioning Profiles')
FIELDS=frozenset({'env_home_matches_isolated','foundation_home_matches_isolated',
    'isolated_legacy_profile_present','isolated_xcode_profile_present',
    'foundation_legacy_profile_present','foundation_xcode_profile_present'})


def foundation_home():
    if sys.platform!='darwin':return None
    foundation=ctypes.CDLL('/System/Library/Frameworks/Foundation.framework/Foundation')
    cf=ctypes.CDLL('/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation')
    foundation.NSHomeDirectory.argtypes=[];foundation.NSHomeDirectory.restype=ctypes.c_void_p
    cf.CFStringGetCString.argtypes=[ctypes.c_void_p,ctypes.c_void_p,ctypes.c_long,ctypes.c_uint32]
    cf.CFStringGetCString.restype=ctypes.c_bool
    value=foundation.NSHomeDirectory();buffer=ctypes.create_string_buffer(16384)
    if not value or not cf.CFStringGetCString(value,buffer,len(buffer),0x08000100):return None
    path=Path(buffer.value.decode('utf-8'))
    return path if path.is_absolute() else None


def regular_present(path):
    try:return stat.S_ISREG(path.lstat().st_mode)
    except FileNotFoundError:return False
    except OSError:return None


def observe(root,env_home,uuid,resolve_home=foundation_home):
    result={'status':'UNAVAILABLE',**{key:None for key in FIELDS}}
    isolated=root/'.ci-github/home'
    try:
        result['env_home_matches_isolated']=Path(env_home).is_absolute() and Path(env_home).resolve()==isolated.resolve()
        for suffix,directory in zip(('legacy','xcode'),PROFILE_DIRS):
            result['isolated_'+suffix+'_profile_present']=regular_present(isolated/directory/(uuid+'.mobileprovision'))
        native=resolve_home()
        if native is not None:
            result['foundation_home_matches_isolated']=native.resolve()==isolated.resolve()
            for suffix,directory in zip(('legacy','xcode'),PROFILE_DIRS):
                result['foundation_'+suffix+'_profile_present']=regular_present(native/directory/(uuid+'.mobileprovision'))
            result['status']='OBSERVED'
    except Exception:pass  # Advisory only; never print exception or fallback paths.
    return result


def project(value):
    if (type(value) is not dict or set(value)!={'status',*FIELDS} or
        type(value.get('status')) is not str or value['status'] not in {'OBSERVED','UNAVAILABLE'} or
        any(value[k] is not None and type(value[k]) is not bool for k in FIELDS)):
        return {'status':'UNAVAILABLE',**{key:None for key in FIELDS}}
    return dict(value)


def artifact_presence(mobile,work):
    # Fixed owned paths only; no globbing outside isolated TMPDIR, no file reads.
    result={key:None for key in ('archive_directory_present','archive_info_present','ipa_directory_present','temporary_result_bundle_present')}
    def owned(base,path):
        return path.is_relative_to(base) and not any(x.is_symlink() for x in (path,*path.parents) if x.is_relative_to(base))
    try:
        archive=mobile/'build/ios/archive/Runner.xcarchive'
        for path,key in ((archive,'archive_directory_present'),(mobile/'build/ios/ipa','ipa_directory_present')):
            if owned(mobile,path):result[key]=path.is_dir()
        if owned(mobile,archive/'Info.plist'):result['archive_info_present']=regular_present(archive/'Info.plist')
        tmp=work/'tmp';result['temporary_result_bundle_present']=False
        if not owned(work,tmp):result['temporary_result_bundle_present']=None
        elif tmp.is_dir():
            for index,path in enumerate(tmp.iterdir()):
                if index>=128:result['temporary_result_bundle_present']=None;break
                if path.name.startswith('flutter_ios_build_temp_dir') and path.is_dir() and not path.is_symlink():
                    bundle=path/'temporary_xcresult_bundle'
                    if bundle.is_dir() and not bundle.is_symlink():result['temporary_result_bundle_present']=True;break
    except Exception:pass
    return result


if __name__=='__main__':
    print(json.dumps(observe(ROOT,os.environ.get('HOME',''),q.REVIEWED_PINS['profile_uuid'])),flush=True)

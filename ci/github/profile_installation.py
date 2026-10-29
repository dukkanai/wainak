"""Temporary pinned profile links in the account home, with durable ownership.

No credential generation, directory sweeps, replacement, or raw diagnostics.
The original private file is retained until every owned external link is gone.
"""
from contextlib import ExitStack
import hashlib
import json
import os
from pathlib import Path
import pwd
import stat
import unicodedata

from ci.github import signing_discovery
from ci.testflight import policy as p
from ci.ios.diagnostics import safe_error

JOURNAL='native-profile-ownership.json'
SOURCE='profile.mobileprovision'
DIRECTORIES=signing_discovery.PROFILE_DIRS
REASONS=frozenset({'signed_native_home','signed_native_path','signed_native_collision',
    'signed_native_pin','signed_native_ownership','signed_native_io','signed_native_cleanup'})
FLAGS=os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC


def failure(operation,error):
    reason=error.args[0] if isinstance(error,p.PolicyError) and error.args else None
    print(json.dumps({'event':'GITHUB_NATIVE_PROFILE','operation':operation,'outcome':'FAILED',
        'error':safe_error(error),'safe_reason':reason if type(reason) is str and reason in REASONS else 'OTHER'}),flush=True)


def require(ok,reason='signed_native_ownership'):
    p.require(ok,reason)


def identity(info):return [info.st_dev,info.st_ino]


def native_home():
    home=signing_discovery.foundation_home()
    account=Path(pwd.getpwuid(os.getuid()).pw_dir)
    require(home is not None and home==account and home.is_absolute() and
            '..' not in home.parts and home!=Path('/'),'signed_native_home')
    return home


def hold(stack,fd):
    stack.callback(os.close,fd)
    return fd


def directory_ok(info,owner=True):
    require(stat.S_ISDIR(info.st_mode),'signed_native_path')
    require(info.st_uid==os.getuid() if owner else info.st_uid in {0,os.getuid()},'signed_native_ownership')
    # Ancestor /tmp may be root-owned and sticky in isolated Linux fixtures.
    sticky=not owner and info.st_uid==0 and bool(info.st_mode & stat.S_ISVTX)
    require(not info.st_mode & 0o022 or sticky,'signed_native_ownership')


def open_path(stack,path):
    require(path.is_absolute() and '..' not in path.parts,'signed_native_path')
    fd=hold(stack,os.open('/',FLAGS))
    directory_ok(os.fstat(fd),False)
    for part in path.parts[1:]:
        fd=hold(stack,os.open(part,FLAGS,dir_fd=fd))
        directory_ok(os.fstat(fd),False)
    directory_ok(os.fstat(fd))
    return fd


def aliases(fd,name):
    names=os.listdir(fd)
    require(len(names)<=4096,'signed_native_path')
    folded=unicodedata.normalize('NFD',name).casefold()
    return [n for n in names if unicodedata.normalize('NFD',n).casefold()==folded]


def target_directory(stack,homefd,relative,create):
    fd=homefd
    for name in relative.split('/'):
        matches=aliases(fd,name)
        require(not matches or matches==[name],'signed_native_collision')
        if not matches and create:
            # No exist_ok: a concurrent creator is a collision, not ownership.
            os.mkdir(name,0o700,dir_fd=fd)
            os.fsync(fd)
        fd=hold(stack,os.open(name,FLAGS,dir_fd=fd))
        directory_ok(os.fstat(fd))
    return fd


def read_file(stack,fd,name,maximum,links):
    filefd=hold(stack,os.open(name,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK|os.O_CLOEXEC,dir_fd=fd))
    info=os.fstat(filefd)
    require(stat.S_ISREG(info.st_mode) and info.st_uid==os.getuid() and
            stat.S_IMODE(info.st_mode)==0o600 and info.st_nlink in links and
            0<info.st_size<=maximum,'signed_native_ownership')
    data=bytearray()
    while len(data)<=maximum:
        block=os.read(filefd,min(65536,maximum+1-len(data)))
        if not block:break
        data.extend(block)
    require(len(data)==info.st_size and identity(os.stat(name,dir_fd=fd,follow_symlinks=False))==identity(info),
            'signed_native_ownership')
    return bytes(data),info


def private_directory(stack,private):
    fd=open_path(stack,private)
    require(stat.S_IMODE(os.fstat(fd).st_mode)==0o700,'signed_native_ownership')
    return fd


def pinned(stack,fd,name,pins,links):
    data,info=read_file(stack,fd,name,36*1024,links)
    require(hashlib.sha256(data).hexdigest()==pins['profile_sha256'],'signed_native_pin')
    return info


def write_journal(fd,value):
    data=(json.dumps(value,sort_keys=True)+'\n').encode()
    filefd=os.open(JOURNAL,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW|os.O_CLOEXEC,0o600,dir_fd=fd)
    try:
        with os.fdopen(filefd,'wb',closefd=False) as stream:
            stream.write(data);stream.flush();os.fsync(filefd)
    finally:os.close(filefd)
    os.fsync(fd)


def snapshot(privatefd,homefd,source,targets,home,pins):
    return {'version':1,'home':str(home),'home_identity':identity(os.fstat(homefd)),
        'private_identity':identity(os.fstat(privatefd)),'source_identity':identity(source),
        'directory_identities':[identity(os.fstat(fd)) for fd in targets],
        'profile_uuid':pins['profile_uuid'],'profile_sha256':pins['profile_sha256']}


def load(stack,privatefd):
    data,_=read_file(stack,privatefd,JOURNAL,8192,{1})
    def pairs(items):
        result={}
        for k,v in items:
            require(k not in result);result[k]=v
        return result
    try:value=json.loads(data,object_pairs_hook=pairs)
    except (ValueError,UnicodeError,RecursionError):raise p.PolicyError('signed_native_ownership') from None
    require(type(value) is dict)
    return value


def session(stack,private,pins,create=False):
    # Caller already validates the exact reviewed pins; filename must remain a
    # single fixed UUID component even for direct unit-test invocation.
    import re
    require(type(pins.get('profile_uuid')) is str and re.fullmatch(r'[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}',pins['profile_uuid']),
            'signed_native_pin')
    home=native_home();homefd=open_path(stack,home);privatefd=private_directory(stack,private)
    source=pinned(stack,privatefd,SOURCE,pins,{1} if create else {1,2,3})
    targets=[target_directory(stack,homefd,d,create) for d in DIRECTORIES]
    value=snapshot(privatefd,homefd,source,targets,home,pins)
    if not create:
        require(json.dumps(load(stack,privatefd),sort_keys=True)==json.dumps(value,sort_keys=True))
    return privatefd,targets,source,value


def install(private,pins):
    try:
        with ExitStack() as stack:
            privatefd,targets,source,value=session(stack,private,pins,True)
            name=pins['profile_uuid']+'.mobileprovision'
            require(not aliases(privatefd,JOURNAL),'signed_native_collision')
            for fd in targets:require(not aliases(fd,name),'signed_native_collision')
            # Persist intent before atomic no-replace hard links. If interrupted
            # after link(), the source inode proves ownership even without a
            # second journal write. EXDEV is failure, never a copying fallback.
            write_journal(privatefd,value)
            for fd in targets:
                os.link(SOURCE,name,src_dir_fd=privatefd,dst_dir_fd=fd,follow_symlinks=False)
                os.fsync(fd)
                require(identity(pinned(stack,fd,name,pins,{2,3}))==identity(source))
        verify(private,pins)
    except BaseException as error:
        failure('INSTALL',error)
        if isinstance(error,OSError):raise p.PolicyError('signed_native_io') from None
        raise
    print(json.dumps({'event':'GITHUB_NATIVE_PROFILE','operation':'INSTALL','outcome':'PASS',
        'locations':2,'pinned_hash_match':True,'ownership_journal':True}),flush=True)


def verify(private,pins):
    try:
        with ExitStack() as stack:
            _,targets,source,_=session(stack,private,pins)
            require(source.st_nlink==3)
            name=pins['profile_uuid']+'.mobileprovision'
            for fd in targets:
                require(aliases(fd,name)==[name],'signed_native_collision')
                require(identity(pinned(stack,fd,name,pins,{3}))==identity(source))
    except BaseException as error:
        failure('VERIFY',error)
        if isinstance(error,OSError):raise p.PolicyError('signed_native_io') from None
        raise


def cleanup(private,pins,required=False):
    # No journal means no authority to remove any account-home profile.
    if not os.path.lexists(private/JOURNAL):
        require(not required,'signed_native_cleanup')
        return
    try:
        with ExitStack() as stack:
            privatefd,targets,source,_=session(stack,private,pins)
            name=pins['profile_uuid']+'.mobileprovision';errors=0
            for fd in targets:
                try:
                    matches=aliases(fd,name)
                    if not matches:continue  # A prior cleanup may have unlinked it.
                    require(matches==[name],'signed_native_collision')
                    require(identity(pinned(stack,fd,name,pins,{1,2,3}))==identity(source))
                    os.unlink(name,dir_fd=fd);os.fsync(fd)
                    require(not aliases(fd,name))
                except BaseException as error:errors+=1;failure('CLEANUP_LINK',error)
            require(errors==0,'signed_native_cleanup')
            require(os.stat(SOURCE,dir_fd=privatefd,follow_symlinks=False).st_nlink==1)
            os.unlink(JOURNAL,dir_fd=privatefd);os.fsync(privatefd)
    except BaseException as error:
        failure('CLEANUP',error)
        if isinstance(error,OSError):raise p.PolicyError('signed_native_cleanup') from None
        raise
    print(json.dumps({'event':'GITHUB_NATIVE_PROFILE','operation':'CLEANUP','outcome':'PASS',
        'owned_links_removed':True}),flush=True)

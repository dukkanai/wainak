"""Independent offline verification of public bootstrap evidence; no network.
The original installation proof was not retained. This explicitly checks the
fresh authenticated public proof, its binding to the retained ZIP, and installed
bytes. It does not claim a second independent cryptographic implementation.
"""
from pathlib import Path, PurePosixPath
import base64
import hashlib
import json
import stat
import sys
if sys.flags.optimize != 0:
    raise RuntimeError("verification requires assertions enabled")
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.exceptions import InvalidSignature
import zipfile

ROOT = Path('/home/chatbot/wainak-dev/archive-tools-phase5-20261024')
KEY = 'sum.golang.org+033de0ae+Ac4zctda0e5eza+HJyk9SxEdh+s3Ux18htTTAD8OuAn8'
MODULE = 'golang.org/toolchain@v0.0.1-go1.27.3.linux-amd64'
proof_file = ROOT/'sumdb-proof-recheck-20261024T1612.json'
proof = json.loads(proof_file.read_bytes())
responses = {name: base64.b64decode(value, validate=True) for name,value in proof['responses_b64'].items()}
lookup = responses['lookup/'+MODULE]
assert len(lookup) <= 65536
record_part, signed_note = lookup.split(b'\n\n',1)
record_number, record_data = record_part.split(b'\n',1)
record_data += b'\n'
leaf_id = int(record_number)
body, signatures = signed_note.split(b'\n\n',1)
body += b'\n'
key = base64.b64decode(KEY.split('+',2)[2],validate=True)
assert len(key)==33 and key[0]==1
assert hashlib.sha256(b'sum.golang.org\n'+key).digest()[:4].hex()=='033de0ae'
signature_lines=signatures.decode().splitlines()
assert len(signature_lines)==1
mark,name,signature=signature_lines[0].split(' ')
assert mark=='—' and name=='sum.golang.org'
signature=base64.b64decode(signature,validate=True)
assert len(signature)==68 and signature[:4].hex()=='033de0ae'
public=Ed25519PublicKey.from_public_bytes(key[1:])
public.verify(signature[4:],body)
try:
    public.verify(signature[4:],body+b'changed')
except InvalidSignature:
    pass
else:
    raise AssertionError('signature negative control')
header,size_text,root_text=body.decode().splitlines()
assert header=='go.sum database tree'
size=int(size_text);expected_root=base64.b64decode(root_text,validate=True)
assert 0<=leaf_id<size<2**48 and len(expected_root)==32

def branch(left,right):
    return hashlib.sha256(b'\x01'+left+right).digest()

def tile_node(level,index):
    """Fetch a perfect-subtree hash using cached Go height-8 tiles."""
    tile_level=level//8
    width_below=1<<(level%8)
    base_index=index*width_below
    tile_number,offset=divmod(base_index,256)
    width=min(256,(size>>(tile_level*8))-tile_number*256)
    assert 0<width<=256 and offset+width_below<=width
    parts=[f'{tile_number%1000:03d}'];remainder=tile_number//1000
    while remainder:
        parts.insert(0,f'x{remainder%1000:03d}');remainder//=1000
    path=f'tile/8/{tile_level}/'+ '/'.join(parts)
    if width<256:path+=f'.p/{width}'
    data=responses[path]
    assert len(data)==32*width
    values=[data[i*32:(i+1)*32] for i in range(offset,offset+width_below)]
    while len(values)>1:values=[branch(values[i],values[i+1]) for i in range(0,len(values),2)]
    return values[0]

def subtree(start,count):
    """Fold binary forest nodes in RFC6962 order."""
    forest=[]
    cursor=start;remaining=count
    while remaining:
        level=remaining.bit_length()-1
        while cursor%(1<<level):level-=1
        forest.append(tile_node(level,cursor>>level))
        cursor+=1<<level;remaining-=1<<level
    result=forest.pop()
    while forest:result=branch(forest.pop(),result)
    return result

def included(start,count):
    if count==1:
        assert start==leaf_id
        return hashlib.sha256(b'\x00'+record_data).digest()
    split=1<<((count-1).bit_length()-1)
    if leaf_id<start+split:return branch(included(start,split),subtree(start+split,count-split))
    return branch(subtree(start,split),included(start+split,count-split))
assert included(0,size)==expected_root
prefix=MODULE.replace('@',' ')+' '
entries=[line[len(prefix):] for line in record_data.decode().splitlines() if line.startswith(prefix)]
assert len(entries)==1
expected_h1=entries[0]
assert expected_h1==proof['proof']['h1']
assert hashlib.sha256(lookup).hexdigest()==proof['proof']['signed_lookup_sha256']
assert leaf_id==proof['proof']['record_id'] and size==proof['proof']['tree_size']
archive=ROOT/'go1.27.3.linux-amd64.toolchain.zip'
zip_sha=hashlib.file_digest(archive.open('rb'),'sha256').hexdigest()
assert zip_sha=='af4c06478303fdd1bfb335fab86c7ccb9b12e529044a946a16a1c4bcc779f8d7'
assert archive.stat().st_size==75781305
files=0;total=0;module_hash=hashlib.sha256()
with zipfile.ZipFile(archive) as z:
    infos=z.infolist()
    assert len(infos)==len({i.filename for i in infos})
    for info in sorted(infos,key=lambda i:i.filename):
        assert info.filename.startswith(MODULE+'/') and '\n' not in info.filename
        relative=PurePosixPath(info.filename[len(MODULE)+1:])
        assert not relative.is_absolute() and '..' not in relative.parts
        mode=info.external_attr>>16
        assert stat.S_IFMT(mode) in (0,stat.S_IFDIR,stat.S_IFREG)
        total+=info.file_size
        assert info.file_size<=200*1024*1024 and total<1024**3
        with z.open(info) as stream:content_hash=hashlib.file_digest(stream,'sha256').hexdigest()
        module_hash.update((content_hash+'  '+info.filename+'\n').encode())
        if info.is_dir():continue
        installed=ROOT/'go'/relative
        assert installed.is_file() and not installed.is_symlink()
        with installed.open('rb') as stream:installed_hash=hashlib.file_digest(stream,'sha256').hexdigest()
        assert installed_hash==content_hash
        files+=1
actual_h1='h1:'+base64.b64encode(module_hash.digest()).decode()
assert actual_h1==expected_h1
installation=json.loads((ROOT/'installation.json').read_bytes())
assert installation['sumdb_h1']==actual_h1 and installation['zip_sha256']==zip_sha
with (ROOT/'bin/age').open('rb') as stream:age_sha=hashlib.file_digest(stream,'sha256').hexdigest()
assert age_sha==installation['binary_sha256']
print(json.dumps({'status':'PASS','scope':'offline fresh signed proof plus ZIP and installed-byte equality','signed_proof_sha256':hashlib.sha256(proof_file.read_bytes()).hexdigest(),'signature_negative_control':True,'zip_sha256':zip_sha,'module_h1':actual_h1,'installed_files_equal':files,'uncompressed_bytes':total,'age_binary_sha256':age_sha,'original_install_proof_retained':False},sort_keys=True))

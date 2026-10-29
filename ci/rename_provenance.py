"""Reviewed rename overlay: retain historical pins and verify current source bytes."""
import hashlib
import json
from pathlib import Path, PurePosixPath
import re

class RenameError(ValueError):
    pass

def require(ok, reason):
    if not ok:raise RenameError(reason)

def regular(root, relative):
    name=PurePosixPath(relative)
    require(not name.is_absolute() and '..' not in name.parts and str(name)==relative, 'rename_path')
    current=root
    for part in name.parts:
        current=current/part
        require(not current.is_symlink(), 'rename_symlink')
    require(current.is_file(), 'rename_missing_source')
    return current

def load(root):
    path=root/'ci/wainek-rename-provenance.json'
    if not path.exists():return {}
    data=json.loads(regular(root,'ci/wainek-rename-provenance.json').read_text())
    require(set(data)=={'schema','base_commit','scope','files'} and data['schema']==1, 'rename_schema')
    require(data['base_commit']=='9bb2aa7731911c1b9d16c76ec4f276ec599f7755', 'rename_anchor')
    require(isinstance(data['files'],dict) and 0<len(data['files'])<100, 'rename_inventory')
    for old,row in data['files'].items():
        require(old.startswith(('archive/','archivebridge/','apps/mobile/')), 'rename_scope')
        require(set(row)=={'path','before_sha256','after_sha256','reason'} and row['reason'], 'rename_entry')
        expected=old.replace('invalid/example/wainak/wainak_mobile','com/nextaura/wainek')
        require(row['path']==expected, 'rename_destination')
        require(all(isinstance(row[k],str) and re.fullmatch('[a-f0-9]{64}',row[k]) for k in ('before_sha256','after_sha256')), 'rename_digest')
    return data['files']

def source_path(root, old):
    return regular(root,load(root).get(old,{}).get('path',old))

def source_matches(root, old, expected):
    row=load(root).get(old)
    path=regular(root,row['path'] if row else old)
    if row:
        require(row['before_sha256']==expected, 'rename_previous_pin_mismatch')
        expected=row['after_sha256']
    return hashlib.sha256(path.read_bytes()).hexdigest()==expected

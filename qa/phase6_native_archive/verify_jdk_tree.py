"""Read-only equivalence check of the retained official JDK and installed tree."""
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import stat
import tarfile

ROOT = Path('/home/chatbot/wainak-dev/native-archive-tools-phase6-20261024')
EXPECTED = 'd7f5d5cf865a2902b70ff549b97586a7d3f234e016f041ab447ea740c7d66d1c'

def main():
    archive = ROOT / 'downloads/temurin-21.0.13_9.tar.gz'
    installed = ROOT / 'jdk'
    if archive.is_symlink() or installed.is_symlink() or installed.stat().st_uid != os.getuid():
        raise RuntimeError('owned regular roots required')
    with archive.open('rb') as stream:
        if hashlib.file_digest(stream, 'sha256').hexdigest() != EXPECTED:
            raise RuntimeError('retained published tar digest changed')
    expected = {}
    total = 0
    with tarfile.open(archive, 'r:gz') as tf:
        for member in tf:
            name = PurePosixPath(member.name)
            if name.is_absolute() or '..' in name.parts or not name.parts or len(name.parts) > 24:
                raise RuntimeError('archive path rejected')
            if name.parts[0] != 'jdk-21.0.13+9':
                raise RuntimeError('archive root mismatch')
            if len(name.parts) == 1:
                continue
            relative = str(PurePosixPath(*name.parts[1:]))
            p = installed / relative
            meta = p.lstat()
            if meta.st_uid != os.getuid():
                raise RuntimeError('installed ownership differs')
            if member.isdir():
                if not stat.S_ISDIR(meta.st_mode):
                    raise RuntimeError('directory kind differs')
                continue
            if relative in expected:
                raise RuntimeError('duplicate archive member')
            if member.issym():
                if not stat.S_ISLNK(meta.st_mode) or os.readlink(p) != member.linkname:
                    raise RuntimeError('symlink differs')
                expected[relative] = {'kind': 'symlink', 'target': member.linkname}
                continue
            if not member.isfile() or not stat.S_ISREG(meta.st_mode) or member.size != meta.st_size:
                raise RuntimeError('regular file kind or size differs')
            total += member.size
            if total > 1024 * 1024 * 1024 or len(expected) > 20000:
                raise RuntimeError('verification bound exceeded')
            with tf.extractfile(member) as source, p.open('rb') as target:
                a = hashlib.file_digest(source, 'sha256').hexdigest()
                b = hashlib.file_digest(target, 'sha256').hexdigest()
            if a != b:
                raise RuntimeError('installed file content differs')
            expected[relative] = {'kind': 'file', 'bytes': member.size, 'sha256': a}
    actual = set()
    for directory, dirs, files in os.walk(installed, followlinks=False):
        for name in files + dirs:
            p = Path(directory) / name
            if p.is_symlink() or not p.is_dir():
                actual.add(str(p.relative_to(installed)))
    if actual != set(expected):
        raise RuntimeError('installed extra or missing file')
    print(json.dumps({'status': 'PASS', 'gate': 'JDK installed-tree content equivalence', 'files_and_symlinks': len(expected), 'regular_bytes': total, 'tar_sha256': EXPECTED, 'tree_manifest_sha256': hashlib.sha256(json.dumps(expected, sort_keys=True).encode()).hexdigest(), 'scope': 'read-only tool content check; not JVM/native runtime acceptance'}, sort_keys=True))

if __name__ == '__main__':
    main()

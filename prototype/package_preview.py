#!/usr/bin/env python3
"""Package the synthetic browser prototype without credentials or server dependencies."""
import base64
import hashlib
import io
from html.parser import HTMLParser
import json
import mimetypes
import os
from pathlib import Path, PurePosixPath
import stat
import re
import zipfile
import uuid

ROOT = Path(__file__).resolve().parent
DIST = ROOT / 'dist'
RELEASES = ROOT / 'releases'


MAX_ASSET_BYTES = 16 * 1024 * 1024

def relative_asset(relative):
    path = PurePosixPath(relative)
    if (not relative or not path.parts or path.is_absolute() or '..' in path.parts or
            str(path) != relative or '\\' in relative or
            any(ord(char) < 32 for char in relative)):
        raise ValueError('Invalid local asset path')
    return path

def open_directory(root):
    """Anchor every directory component without following symlinks."""
    path = Path(root).absolute()
    if '..' in path.parts:
        raise ValueError('Invalid source root')
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    fd = os.open(path.anchor, flags)
    try:
        for component in path.parts[1:]:
            child = os.open(component, flags, dir_fd=fd)
            os.close(fd)
            fd = child
        return fd
    except BaseException:
        os.close(fd)
        raise

def read_local(root, relative):
    """Read the opened regular descriptor, not a checked path reopened later."""
    path = relative_asset(relative)
    directory = open_directory(root)
    try:
        for component in path.parts[:-1]:
            child = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                            dir_fd=directory)
            os.close(directory)
            directory = child
        fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                     dir_fd=directory)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_ASSET_BYTES:
                raise ValueError('Invalid local asset type or size')
            data = bytearray()
            while True:
                block = os.read(fd, min(65536, MAX_ASSET_BYTES + 1 - len(data)))
                if not block:
                    break
                data.extend(block)
                if len(data) > MAX_ASSET_BYTES:
                    raise ValueError('Local asset read bound exceeded')
            return bytes(data)
        finally:
            os.close(fd)
    finally:
        os.close(directory)

def local_asset(relative):
    return read_local(DIST, relative)

def source_files(root):
    """Enumerate inputs fail-closed; reject links/special files even if unused."""
    directory = open_directory(root)
    def walk(fd, prefix='', depth=0):
        if depth > 64:
            raise ValueError('Source directory depth exceeded')
        with os.scandir(fd) as entries:
            for entry in entries:
                relative = prefix + entry.name
                relative_asset(relative)
                info = entry.stat(follow_symlinks=False)
                if stat.S_ISDIR(info.st_mode):
                    child = os.open(entry.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                                    dir_fd=fd)
                    try:
                        yield from walk(child, relative + '/', depth + 1)
                    finally:
                        os.close(child)
                elif stat.S_ISREG(info.st_mode):
                    yield relative
                else:
                    raise ValueError('Source link or special file rejected')
    try:
        return sorted(walk(directory))
    finally:
        os.close(directory)

def output_target(directory, name):
    try:
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                     dir_fd=directory)
    except FileNotFoundError:
        return None
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or
                info.st_nlink != 1):
            raise ValueError('Unsafe existing output file')
        return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)
    finally:
        os.close(fd)

def publish_outputs(payloads):
    """Atomic replacement per regular owned output; never truncate old leaves.

    Existing normal outputs may be refreshed. Links, FIFOs, devices, multiply
    linked files and output-directory drift fail closed. The manifest is last;
    this is not a cross-file transaction or a hostile same-user filesystem lock.
    """
    if set(payloads) != {'wainek-preview.html', 'wainek-prototype.zip', 'manifest.json'}:
        raise ValueError('Unexpected output inventory')
    RELEASES.mkdir(mode=0o700, exist_ok=True)
    directory = open_directory(RELEASES)
    temporary = {}
    primary = None
    def directory_current():
        current = open_directory(RELEASES)
        try:
            info = os.fstat(current)
            original = os.fstat(directory)
            if ((info.st_dev, info.st_ino) != (original.st_dev, original.st_ino) or
                    info.st_uid != os.getuid() or info.st_mode & 0o022):
                raise ValueError('Output directory ownership or identity changed')
        finally:
            os.close(current)
    try:
        directory_current()
        previous = {name: output_target(directory, name) for name in payloads}
        for name, data in payloads.items():
            temp = '.wainek-package-' + uuid.uuid4().hex
            fd = os.open(temp, os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW |
                         os.O_NONBLOCK, 0o600, dir_fd=directory)
            with os.fdopen(fd, 'w+b') as stream:
                info = os.fstat(stream.fileno())
                temporary[name] = (temp, info.st_dev, info.st_ino)
                if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or
                        info.st_uid != os.getuid()):
                    raise ValueError('Unsafe temporary output')
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
                stream.seek(0)
                digest = hashlib.sha256()
                for block in iter(lambda: stream.read(65536), b''):
                    digest.update(block)
                if digest.digest() != hashlib.sha256(data).digest():
                    raise ValueError('Staged output bytes changed')
        directory_current()
        if any(output_target(directory, name) != previous[name] for name in payloads):
            raise ValueError('Existing output changed before publication')
        for name in ('wainek-preview.html', 'wainek-prototype.zip', 'manifest.json'):
            directory_current()
            if output_target(directory, name) != previous[name]:
                raise ValueError('Output leaf changed before publication')
            temp, device, inode = temporary[name]
            info = os.stat(temp, dir_fd=directory, follow_symlinks=False)
            if (info.st_dev, info.st_ino) != (device, inode) or not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise ValueError('Temporary output identity changed')
            # rename/replace acts on the leaf itself, never follows its link.
            os.replace(temp, name, src_dir_fd=directory, dst_dir_fd=directory)
            published = output_target(directory, name)
            if published is None or published[:2] != (device, inode):
                raise ValueError('Published output identity changed')
        directory_current()
        os.fsync(directory)
    except BaseException as error:
        primary = error
        raise
    finally:
        cleanup_failed = False
        for temp, device, inode in temporary.values():
            try:
                info = os.stat(temp, dir_fd=directory, follow_symlinks=False)
                if (info.st_dev, info.st_ino) != (device, inode):
                    raise ValueError('Temporary cleanup identity changed')
                os.unlink(temp, dir_fd=directory)
            except FileNotFoundError:
                pass
            except BaseException:
                cleanup_failed = True
        os.close(directory)
        if cleanup_failed and primary is None:
            raise ValueError('Owned temporary cleanup failed')


class Tag(HTMLParser):
    def handle_starttag(self, tag, attrs):
        self.attrs = dict(attrs)


def attrs(tag):
    parser = Tag()
    parser.feed(tag)
    return parser.attrs


def inline_css(css):
    def replace(match):
        url = match.group(1).strip().strip('\"\'')
        if url.startswith('data:') or url.startswith('#'):
            return match.group(0)
        if '://' in url or url.startswith('//'):
            raise ValueError('External asset cannot be included in offline preview')
        data = local_asset(url)
        mime = mimetypes.guess_type(PurePosixPath(url).name)[0] or 'application/octet-stream'
        payload = base64.b64encode(data).decode('ascii')
        return f'url("data:{mime};base64,{payload}")'
    return re.sub(r'url\(([^)]+)\)', replace, css)


def main():
    inputs = source_files(DIST)
    html = local_asset('index.html').decode('utf-8')
    def stylesheet(match):
        tag = match.group(0)
        properties = attrs(tag)
        if properties.get('rel') != 'stylesheet':
            return tag
        return '<style>\n' + inline_css(local_asset(properties['href']).decode('utf-8')) + '\n</style>'
    html = re.sub(r'<link\b[^>]*>', stylesheet, html, flags=re.I)
    scripts = []
    def script(match):
        properties = attrs(match.group(0).split('>')[0] + '>')
        content = local_asset(properties['src']).decode('utf-8')
        scripts.append('<script>\n' + content.replace('</script', '<\\/script') + '\n</script>')
        return ''
    html = re.sub(r'<script\b[^>]*\bsrc=[\"\'][^\"\']+[\"\'][^>]*>\s*</script>', script, html, flags=re.I)
    def inline_license(match):
        relative = match.group(1)
        payload = base64.b64encode(local_asset(relative)).decode('ascii')
        return 'href="data:text/plain;charset=utf-8;base64,' + payload + '" download="' + PurePosixPath(relative).name + '"'
    notices = []
    for relative in inputs:
        path = PurePosixPath(relative)
        if path.parent == PurePosixPath('assets') and 'OFL' in path.name:
            notices.append(local_asset(relative).decode('utf-8').replace('--', '- -'))
    html = html.replace('</body>', '\n'.join(scripts) + '\n<!-- Bundled font license notices\n' + '\n'.join(notices) + '\n-->\n</body>')
    html = re.sub(r'href="(assets/[^\"]*OFL[^\"]*)"', inline_license, html)
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as output:
        for relative in inputs:
            output.writestr('wainek-prototype/' + relative, local_asset(relative))
        output.writestr('wainek-preview.html', html)
        try:
            readme = read_local(ROOT, 'README.md').decode('utf-8')
        except FileNotFoundError:
            readme = None
        if readme is not None:
            output.writestr('README.md', readme.replace('releases/wainek-preview.html', 'wainek-preview.html').replace('releases/wainek-prototype.zip', 'wainek-prototype.zip').replace('[تقرير التنفيذ](../docs/reviews/iteration-01.md) عند اكتماله', 'تقرير التنفيذ في مستودع المشروع: docs/reviews/iteration-01.md'))
    payloads = {'wainek-preview.html': html.encode('utf-8'),
                'wainek-prototype.zip': archive.getvalue()}
    manifest = {name: {'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data)}
                for name, data in payloads.items()}
    payloads['manifest.json'] = (json.dumps(manifest, indent=2) + '\n').encode('utf-8')
    publish_outputs(payloads)
    print(json.dumps(manifest, indent=2))


if __name__ == '__main__':
    main()

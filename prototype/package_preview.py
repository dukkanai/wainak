#!/usr/bin/env python3
"""Package the synthetic browser prototype without credentials or server dependencies."""
import base64
import hashlib
from html.parser import HTMLParser
import json
import mimetypes
from pathlib import Path
import re
import zipfile

ROOT = Path(__file__).resolve().parent
DIST = ROOT / 'dist'
RELEASES = ROOT / 'releases'


def local_asset(relative):
    path = (DIST / relative).resolve()
    if not path.is_relative_to(DIST.resolve()) or not path.is_file() or path.is_symlink():
        raise ValueError(f'Invalid local asset: {relative}')
    return path


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
        path = local_asset(url)
        mime = mimetypes.guess_type(path.name)[0] or 'application/octet-stream'
        payload = base64.b64encode(path.read_bytes()).decode('ascii')
        return f'url("data:{mime};base64,{payload}")'
    return re.sub(r'url\(([^)]+)\)', replace, css)


def main():
    RELEASES.mkdir(exist_ok=True)
    html = local_asset('index.html').read_text()
    def stylesheet(match):
        tag = match.group(0)
        properties = attrs(tag)
        if properties.get('rel') != 'stylesheet':
            return tag
        return '<style>\n' + inline_css(local_asset(properties['href']).read_text()) + '\n</style>'
    html = re.sub(r'<link\b[^>]*>', stylesheet, html, flags=re.I)
    scripts = []
    def script(match):
        properties = attrs(match.group(0).split('>')[0] + '>')
        content = local_asset(properties['src']).read_text()
        scripts.append('<script>\n' + content.replace('</script', '<\\/script') + '\n</script>')
        return ''
    html = re.sub(r'<script\b[^>]*\bsrc=[\"\'][^\"\']+[\"\'][^>]*>\s*</script>', script, html, flags=re.I)
    def inline_license(match):
        asset = local_asset(match.group(1))
        payload = base64.b64encode(asset.read_bytes()).decode('ascii')
        return 'href="data:text/plain;charset=utf-8;base64,' + payload + '" download="' + asset.name + '"'
    notices = []
    for path in sorted((DIST / 'assets').glob('*OFL*')):
        notices.append(path.read_text().replace('--', '- -'))
    html = html.replace('</body>', '\n'.join(scripts) + '\n<!-- Bundled font license notices\n' + '\n'.join(notices) + '\n-->\n</body>')
    html = re.sub(r'href="(assets/[^\"]*OFL[^\"]*)"', inline_license, html)
    standalone = RELEASES / 'wainak-preview.html'
    standalone.write_text(html)
    archive = RELEASES / 'wainak-prototype.zip'
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as output:
        for path in sorted(DIST.rglob('*')):
            if path.is_file() and not path.is_symlink():
                output.write(path, 'wainak-prototype/' + str(path.relative_to(DIST)))
        output.write(standalone, 'wainak-preview.html')
        readme = ROOT / 'README.md'
        if readme.exists():
            output.writestr('README.md', readme.read_text().replace('releases/wainak-preview.html', 'wainak-preview.html').replace('releases/wainak-prototype.zip', 'wainak-prototype.zip').replace('[تقرير التنفيذ](../docs/reviews/iteration-01.md) عند اكتماله', 'تقرير التنفيذ في مستودع المشروع: docs/reviews/iteration-01.md'))
    manifest = {path.name: {'sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'bytes': path.stat().st_size}
                for path in (standalone, archive)}
    (RELEASES / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(json.dumps(manifest, indent=2))


if __name__ == '__main__':
    main()

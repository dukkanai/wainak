import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock
from ci.testflight import sdk_overlay as s, policy as p


def blob(data):
    return hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()


class SdkOverlayGuards(unittest.TestCase):
    def test_reviewed_delta_manifest_and_bounds(self):
        manifest, helper = s.delta()
        self.assertEqual(s.digest(helper), manifest['helper_sha256'])
        self.assertIn(b'await exited.timeout(termTimeout)', helper)
        self.assertIn(b'await exited.timeout(killTimeout)', helper)
        self.assertIn(b'ProcessSignal.sigkill.kill(process)', helper)
        self.assertEqual((manifest['term_timeout_seconds'],manifest['kill_timeout_seconds']), (5,2))

    def test_exact_source_and_only_reviewed_replacement(self):
        before = ('// fixture\n'+s.OLD+'// end\n').encode()
        helper = b'// fixture helper\n'
        after = before.replace(s.OLD.encode(),s.NEW.encode())+b'\n'+helper
        manifest = {'before_sha256':s.digest(before),'after_sha256':s.digest(after)}
        with mock.patch.object(s,'delta',return_value=(manifest,helper)):
            self.assertEqual(s.patch_source(before),after)
            for bad in (before+b' ',before.replace(b'dispose',b'Dispose'),before+before):
                with self.assertRaisesRegex(p.PolicyError,'sdk_delta_before'):s.patch_source(bad)
            manifest['after_sha256']='0'*64
            with self.assertRaisesRegex(p.PolicyError,'sdk_delta_after'):s.patch_source(before)

    def test_inventory_rejects_paths_modes_duplicates_and_missing_source(self):
        entries={s.TARGET:b'old','packages/flutter_tools/bin/flutter_tools.dart':b'main',
                 'packages/flutter_tools/pubspec.yaml':b'pub'}
        raw=''.join('100644 blob '+blob(value)+'\t'+name+'\0' for name,value in entries.items())
        self.assertEqual(set(s.inventory(raw)),set(entries))
        for bad in ('',raw+raw,raw.replace('100644','120000'),raw.replace(s.TARGET,'../escape'),
                    raw.replace(s.TARGET,s.TARGET.upper()),raw.replace('blob','tree')):
            with self.subTest(case=bad[:20]),self.assertRaises((p.PolicyError,ValueError)):s.inventory(bad)

    def test_source_crlf_symlinks_drift_and_overlay_extra_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve();base=root/'sdk';base.mkdir()
            attrs=b'*.bat text eol=crlf\n*.ps1 text eol=crlf\n'
            (base/'.gitattributes').write_bytes(attrs)
            (base/'tool.bat').write_bytes(b'line\r\n')
            entries={'.gitattributes':blob(attrs),'tool.bat':blob(b'line\n')}
            baseline=s.snapshot(base,entries)
            config=base/'packages/flutter_tools/.dart_tool/package_config.json'
            config.parent.mkdir(parents=True);config.write_bytes(b'{}')
            dest=root/'overlay';dest.mkdir();(dest/'x').write_bytes(b'ok')
            overlay=s.Overlay(base,dest,entries,baseline,b'{}',{'x':s.digest(b'ok')})
            overlay.verify()
            for kind in ('extra','symlink','missing','edit','sdk','config'):
                with self.subTest(kind=kind):
                    if kind=='extra':(dest/'extra').write_bytes(b'bad')
                    elif kind=='symlink':(dest/'x').unlink();(dest/'x').symlink_to(config)
                    elif kind=='missing':(dest/'x').unlink()
                    elif kind=='edit':(dest/'x').write_bytes(b'bad')
                    elif kind=='sdk':(base/'tool.bat').write_bytes(b'changed')
                    else:config.write_bytes(b'changed')
                    with self.assertRaises(p.PolicyError):overlay.verify()
                    if (dest/'extra').exists():(dest/'extra').unlink()
                    if (dest/'x').is_symlink():(dest/'x').unlink()
                    (dest/'x').write_bytes(b'ok');(base/'tool.bat').write_bytes(b'line\r\n');config.write_bytes(b'{}')
            (base/'tool.bat').unlink();(base/'tool.bat').symlink_to(config)
            with self.assertRaises(p.PolicyError):s.snapshot(base,entries)

    def test_package_config_changes_only_tool_root_and_rejects_remote_duplicate(self):
        original=Path('/sdk/packages/flutter_tools/.dart_tool/package_config.json')
        data={'configVersion':2,'packages':[{'name':'flutter_tools','rootUri':'../','packageUri':'lib/'},
                                         {'name':'dependency','rootUri':'file:///cache/dep','packageUri':'lib/'}]}
        out=json.loads(s.package_config(json.dumps(data).encode(),original,Path('/overlay/tool')))
        self.assertEqual(out['packages'][0]['rootUri'],'file:///overlay/tool/')
        self.assertEqual(out['packages'][1],data['packages'][1])
        for kind in ('remote','duplicate','wrong_tool'):
            item=json.loads(json.dumps(data))
            if kind=='remote':item['packages'][1]['rootUri']='https://invalid.example/pkg'
            elif kind=='duplicate':item['packages'].append(item['packages'][0])
            else:item['packages'][0]['rootUri']='file:///other'
            with self.assertRaises(p.PolicyError):s.package_config(json.dumps(item).encode(),original,Path('/overlay'))

    def test_prepare_checks_revision_before_copy(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(s.shutil,'which',return_value=tmp+'/bin/flutter'):
            calls=[]
            def run(label,argv,**kwargs):calls.append(label);return '0'*40
            with self.assertRaisesRegex(p.PolicyError,'sdk_source_revision'):s.prepare(Path(tmp),run)
            self.assertEqual(calls,['sdk_head'])
            self.assertFalse((Path(tmp)/'analyzer_overlay').exists())

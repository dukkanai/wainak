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
        pair=''.join('100644 blob '+blob(b'fixture')+'\tpackages/flutter_tools/lib/'+name+'\0' for name in ('Extra.dart','extra.dart'))
        with self.assertRaisesRegex(p.PolicyError,'sdk_inventory_case_collision'):s.inventory(raw+pair)
        for bad in ('',raw+raw,raw.replace('100644','120000'),raw.replace(s.TARGET,'../escape'),
                    raw.replace(s.TARGET,s.TARGET.upper()),raw.replace('blob','tree')):
            with self.subTest(case=bad[:20]),self.assertRaises((p.PolicyError,ValueError)):s.inventory(bad)

    def test_source_crlf_symlinks_drift_and_overlay_extra_files(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(s,'delta',return_value=({'tool_pubspec_lock_sha256':s.digest(b'fixturelock')},b'')):
            root=Path(tmp).resolve();base=root/'sdk';base.mkdir()
            attrs=b'*.bat text eol=crlf\n*.ps1 text eol=crlf\n'
            (base/'.gitattributes').write_bytes(attrs)
            (base/'tool.bat').write_bytes(b'line\r\n')
            entries={'.gitattributes':blob(attrs),'tool.bat':blob(b'line\n')}
            baseline=s.snapshot(base,entries)
            config=base/'packages/flutter_tools/.dart_tool/package_config.json'
            config.parent.mkdir(parents=True);config.write_bytes(b'{}')
            (config.parent.parent/'pubspec.lock').write_bytes(b'fixturelock')
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

class ColdSdkPreparation(unittest.TestCase):
    def test_cold_and_warm_provider_generate_isolated_locked_dependencies(self):
        for warm in (False,True):
            with self.subTest(warm=warm):self.exercise(warm)

    def test_every_boundary_fails_at_specific_stage_without_sdk_mutation(self):
        for failure,reason in [('lock','sdk_tool_lock_hash'),('dependencies','OTHER'),
            ('changed_lock','sdk_tool_lock_changed'),('missing_config','sdk_generated_config_missing'),
            ('missing_graph','sdk_generated_file'),('extra','sdk_overlay_drift'),('source_drift','sdk_source_drift'),
            ('config_symlink','sdk_generated_config_missing'),('wrong_root','sdk_package_tool_root')]:
            with self.subTest(failure=failure):self.exercise(False,failure,reason)

    def exercise(self,warm,failure=None,reason=None):
        import io
        from contextlib import redirect_stdout
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve();base=root/'sdk';work=root/'work';work.mkdir()
            original=('// fixture\n'+s.OLD).encode();helper=b'// fixture helper\n';lock=b'fixture pinned lock'
            data={s.TARGET:original,'packages/flutter_tools/bin/flutter_tools.dart':b'main',
                'packages/flutter_tools/pubspec.yaml':b'name: flutter_tools\n','bin/flutter':b'fixture'}
            for name,value in data.items():
                file=base/name;file.parent.mkdir(parents=True,exist_ok=True);file.write_bytes(value)
            (base/'packages/flutter_tools/pubspec.lock').write_bytes(b'changed' if failure=='lock' else lock)
            config=base/'packages/flutter_tools/.dart_tool/package_config.json'
            if warm:config.parent.mkdir();config.write_bytes(b'provider untouched config')
            baseline={x.relative_to(base).as_posix():x.read_bytes() for x in base.rglob('*') if x.is_file()}
            manifest={'framework_revision':'a'*40,'before_sha256':s.digest(original),
                'after_sha256':s.digest(original.replace(s.OLD.encode(),s.NEW.encode())+b'\n'+helper),
                'tool_pubspec_lock_sha256':s.digest(lock)}
            raw=''.join('100644 blob '+blob(value)+'\t'+name+'\0' for name,value in data.items())
            calls=[]
            def run(label,argv,**kw):
                calls.append(label)
                if label=='sdk_head':
                    self.assertEqual(argv,['git','rev-parse','HEAD']);self.assertEqual(kw['cwd'],base)
                    return manifest['framework_revision']
                if label=='sdk_inventory':
                    self.assertEqual(argv,['git','ls-tree','-rz','HEAD','--',*s.SOURCE_PATHS]);self.assertEqual(kw['cwd'],base)
                    return raw
                self.assertEqual(label,'sdk_dependencies')
                target=work/'analyzer_overlay/flutter_tools'
                self.assertEqual(argv,[base/'bin/cache/dart-sdk/bin/dart','pub','get','--enforce-lockfile','--no-precompile'])
                self.assertEqual(kw['cwd'],target)
                if failure=='dependencies':raise RuntimeError('CANARY')
                generated=target/'.dart_tool';generated.mkdir()
                if failure!='missing_config':
                    c={'configVersion':2,'packages':[{'name':'flutter_tools','rootUri':'../' if failure!='wrong_root' else 'file:///wrong','packageUri':'lib/'}]}
                    (generated/'package_config.json').write_text(json.dumps(c))
                if failure!='missing_graph':(generated/'package_graph.json').write_text('{}')
                if failure=='changed_lock':(target/'pubspec.lock').write_bytes(b'changed')
                if failure=='extra':(target/'unexpected.dart').write_bytes(b'CANARY')
                if failure=='source_drift':(base/'bin/flutter').write_bytes(b'changed')
                if failure=='config_symlink':
                    (generated/'package_config.json').unlink();(generated/'package_config.json').symlink_to(target/'pubspec.lock')
                return 'CANARY'
            with mock.patch.object(s,'delta',return_value=(manifest,helper)), \
                 mock.patch.object(s.shutil,'which',return_value=str(base/'bin/flutter')), redirect_stdout(io.StringIO()) as output:
                if failure:
                    with self.assertRaises((p.PolicyError,RuntimeError)):s.prepare(work,run)
                    rows=[json.loads(line) for line in output.getvalue().splitlines()]
                    self.assertEqual(rows[-1]['outcome'],'FAILED');self.assertEqual(rows[-1]['safe_reason'],reason)
                    expected_stage={'lock':'source_snapshot','dependencies':'tool_dependencies',
                        'changed_lock':'tool_dependencies','source_drift':'tool_dependencies',
                        'extra':'final_verification'}.get(failure,'package_config')
                    self.assertEqual(rows[-1]['stage'],expected_stage)
                else:
                    result=s.prepare(work,run);result.verify()
                    self.assertEqual(result.config_bytes,b'provider untouched config' if warm else None)
                    self.assertEqual(calls,['sdk_head','sdk_inventory','sdk_dependencies'])
                    derived=json.loads((result.destination/'package_config.json').read_text())
                    self.assertEqual(derived['packages'][0]['rootUri'],(result.destination/'flutter_tools').as_uri()+'/')
                self.assertNotIn('CANARY',output.getvalue());self.assertNotIn(str(root),output.getvalue())
            if failure!='source_drift':
                self.assertEqual({x.relative_to(base).as_posix():x.read_bytes() for x in base.rglob('*') if x.is_file()},baseline)

    def test_policy_reason_catalog_covers_every_sdk_guard_and_hides_canaries(self):
        import ast
        tree=ast.parse(Path(s.__file__).read_text())
        labels={ast.literal_eval(node.args[1]) for node in ast.walk(tree) if isinstance(node,ast.Call)
            and isinstance(node.func,ast.Attribute) and node.func.attr=='require'}
        self.assertEqual(labels, s.SAFE_POLICY_REASONS)
        self.assertEqual(s.safe_reason(p.PolicyError('CANARY')),'OTHER')
        self.assertEqual(s.safe_reason(RuntimeError('sdk_tool_lock_hash')),'OTHER')
        for label in labels:self.assertEqual(s.safe_reason(p.PolicyError(label)),label)

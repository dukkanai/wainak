"""Unsigned simulator controls and synthetic OS metadata; no signing/compiler/run."""
import contextlib
import copy
import io
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

CI = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CI / 'ios'))
import build as b
import check_unsigned as c
import unsigned_diagnostics as d
import verify as v

CANARY = 'PRIVATE_PATH_IDENTITY_CANARY'


def macho(signature=False):
    commands = struct.pack('<IIII', 0x1d, 16, 48, 16) if signature else b''
    return struct.pack('<8I', 0xfeedfacf, 0x100000c, 0, 2, int(signature),
                       len(commands), 0, 0) + commands + (bytes(16) if signature else b'')


class LinkerPolicyTests(unittest.TestCase):
    def settings(self, sdk):
        names = ['Runner', 'RunnerTests'] if sdk == 'iphonesimulator' else ['Runner']
        value = v.unsigned_linker_setting(sdk).split('=', 1)[1]
        return [{'target': n, 'buildSettings': {'OTHER_LDFLAGS': value}} for n in names]

    def test_device_setting_identical_to_baseline(self):
        self.assertEqual(v.unsigned_linker_setting('iphoneos'),
            'OTHER_LDFLAGS=$(inherited) -framework Archivebridge -framework Foundation')

    def test_simulator_only_appends_no_adhoc(self):
        self.assertEqual(v.unsigned_linker_setting('iphonesimulator'),
            v.unsigned_linker_setting('iphoneos') + ' -Wl,-no_adhoc_codesign')

    def test_settings_and_matching_compile_share_control(self):
        for sdk in ('iphoneos', 'iphonesimulator'):
            base = ['/usr/bin/xcodebuild', v.unsigned_linker_setting(sdk), *b.SIGNING]
            settings, command = b.xcode_commands(base, sdk)
            self.assertEqual(settings[:-2], command)
            self.assertEqual(command.count(v.unsigned_linker_setting(sdk)), 1)
            for signing in b.SIGNING:
                self.assertIn(signing, command)

    def test_both_platform_settings_validate(self):
        self.assertEqual(v.unsigned_linker_settings(self.settings('iphoneos'), 'iphoneos'),
            {'targets_checked': 1, 'implicit_linker_signing': 'unchanged_device_default'})
        self.assertEqual(v.unsigned_linker_settings(self.settings('iphonesimulator'), 'iphonesimulator'),
            {'targets_checked': 2, 'implicit_linker_signing': 'disabled_for_simulator'})

    def test_every_simulator_target_must_have_control(self):
        for index in (0, 1):
            rows = self.settings('iphonesimulator')
            rows[index]['buildSettings']['OTHER_LDFLAGS'] = '-framework Archivebridge'
            with self.subTest(index=index), self.assertRaises(v.GateError):
                v.unsigned_linker_settings(rows, 'iphonesimulator')

    def test_adhoc_or_duplicate_or_wrong_control_rejected(self):
        for suffix in (' -Wl,-adhoc_codesign', ' -Xlinker -adhoc_codesign',
                       ' -Wl,-no_adhoc_codesign', ' -no_adhoc_codesign'):
            rows = self.settings('iphonesimulator')
            rows[0]['buildSettings']['OTHER_LDFLAGS'] += suffix
            with self.subTest(suffix=suffix), self.assertRaises(v.GateError):
                v.unsigned_linker_settings(rows, 'iphonesimulator')

    def test_simulator_control_rejected_on_device(self):
        rows = self.settings('iphoneos')
        rows[0]['buildSettings']['OTHER_LDFLAGS'] += ' -Wl,-no_adhoc_codesign'
        with self.assertRaises(v.GateError):
            v.unsigned_linker_settings(rows, 'iphoneos')

    def test_missing_tests_duplicate_runner_unknown_sdk_rejected(self):
        rows = self.settings('iphonesimulator')
        for value, sdk in ((rows[:1], 'iphonesimulator'), (rows + rows[:1], 'iphonesimulator'),
                           (rows, 'macosx'), ([], 'iphoneos')):
            with self.subTest(sdk=sdk), self.assertRaises(v.GateError):
                v.unsigned_linker_settings(value, sdk)
        with self.assertRaises(v.GateError):
            v.unsigned_linker_setting('macosx')

    def test_malformed_shapes_and_quoting_fail_closed(self):
        for rows in (None, {}, [None], [{}], [{'target': 3}],
                     [{'target': 'Runner', 'buildSettings': {'OTHER_LDFLAGS': []}}],
                     [{'target': 'Runner', 'buildSettings': {'OTHER_LDFLAGS': '"broken'}}]):
            with self.subTest(rows=rows), self.assertRaises(v.GateError):
                v.unsigned_linker_settings(rows, 'iphoneos')

    def test_receipt_does_not_export_target_names(self):
        rows = self.settings('iphonesimulator')
        rows.append({'target': CANARY, 'buildSettings': rows[0]['buildSettings']})
        self.assertNotIn(CANARY, json.dumps(v.unsigned_linker_settings(rows, 'iphonesimulator')))


class UnsignedHelperTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.app = self.root / 'Runner.app'
        self.app.mkdir()
        (self.app/'Runner').write_bytes(macho())

    def invoke(self, code=1, output=b'code object is not signed at all', error=None):
        stream = io.StringIO()
        result = subprocess.CompletedProcess([], code, stdout=output)
        with patch.object(c.subprocess, 'run', side_effect=error, return_value=result) as run, \
             contextlib.redirect_stdout(stream):
            status = c.check(self.app)
        return status, stream.getvalue(), run

    def report(self, output):
        self.assertNotIn(CANARY, output)
        row = d.unsigned_summary(output.encode())
        self.assertEqual(row['availability'], 'present')
        return row

    def test_unsigned_requires_exact_existing_success_sentinel(self):
        status, output, run = self.invoke()
        self.assertEqual(status, 0)
        self.assertEqual(output.strip(), 'PASS_UNSIGNED_APP')
        args = run.call_args.args[0]
        self.assertEqual(args[:3], ['/usr/bin/codesign', '-d', '--verbose=4'])
        self.assertNotIn('-s', args)
        self.assertEqual(run.call_args.kwargs['timeout'], 15)

    def test_detected_adhoc_remains_failure(self):
        status, output, _ = self.invoke(0, b'Signature=adhoc\nIdentifier='+CANARY.encode())
        self.assertEqual(status, 1)
        row = self.report(output)
        self.assertEqual(row['category'], 'signature_present')
        self.assertEqual(row['signature_class'], 'adhoc')
        self.assertEqual(row['codesign_returncode'], 0)

    def test_identity_signature_remains_failure_and_redacted(self):
        status, output, _ = self.invoke(0, b'Authority='+CANARY.encode())
        self.assertEqual(status, 1)
        self.assertEqual(self.report(output)['signature_class'], 'other_or_unknown_signature')

    def test_success_exit_never_accepted_even_with_unsigned_message(self):
        status, output, _ = self.invoke(0, b'code object is not signed at all')
        self.assertEqual(status, 1)
        self.assertTrue(self.report(output)['unsigned_sentinel'])

    def test_nonzero_unknown_error_is_not_unsigned(self):
        status, output, _ = self.invoke(1, CANARY.encode())
        self.assertEqual(status, 1)
        self.assertEqual(self.report(output)['category'], 'unexpected_codesign_output')

    def test_macho_signature_is_rejected_even_with_unsigned_tool_message(self):
        (self.app/'Runner').write_bytes(macho(True))
        status, output, _ = self.invoke()
        self.assertEqual(status, 1)
        self.assertEqual(self.report(output)['macho_signature'], 'present')

    def test_signed_codesign_text_cannot_be_erased_by_unsigned_phrase(self):
        status, output, _ = self.invoke(1, b'Signature=adhoc\ncode object is not signed at all')
        self.assertEqual(status, 1)
        row = self.report(output)
        self.assertEqual(row['category'], 'signature_present')
        self.assertEqual(row['signature_class'], 'adhoc')
        self.assertTrue(row['unsigned_sentinel'])

    def test_code_directory_metadata_is_also_positive_signature_evidence(self):
        status, output, _ = self.invoke(1, b'CodeDirectory v=20400 flags=0x0\ncode object is not signed at all')
        self.assertEqual(status, 1)
        self.assertEqual(self.report(output)['signature_class'], 'other_or_unknown_signature')

    def test_signature_then_malformed_tail_remains_positive(self):
        data = struct.pack('<8I', 0xfeedfacf, 0x100000c, 0, 2, 2, 24, 0, 0)
        data += struct.pack('<4I', 0x1d, 16, 64, 4) + struct.pack('<2I', 1, 0)
        (self.app/'Runner').write_bytes(data)
        self.assertEqual(d.macho_signature(self.app), 'present')
        status, output, _ = self.invoke()
        self.assertEqual(status, 1)
        self.assertEqual(self.report(output)['macho_signature'], 'present')

    def test_timeout_is_fixed_failure_without_raw_exception(self):
        status, output, _ = self.invoke(error=subprocess.TimeoutExpired(CANARY, 15, output=CANARY.encode()))
        self.assertEqual(status, 1)
        self.assertEqual(self.report(output)['category'], 'codesign_timeout')

    def test_tool_error_is_fixed_failure_without_path(self):
        status, output, _ = self.invoke(error=PermissionError(13, CANARY, CANARY))
        self.assertEqual(status, 1)
        self.assertEqual(self.report(output)['category'], 'codesign_tool_error')

    def test_oversized_tool_output_is_rejected_and_not_exported(self):
        status, output, _ = self.invoke(1, CANARY.encode() * 6000)
        self.assertEqual(status, 1)
        self.assertLess(len(output), 1024)
        self.assertEqual(self.report(output)['category'], 'codesign_output_bound')

    def test_root_metadata_and_dangling_metadata_symlinks_rejected(self):
        for name in ('_CodeSignature', 'embedded.mobileprovision'):
            marker = self.app/name
            marker.symlink_to(self.root/'absent')
            status, output, run = self.invoke()
            self.assertEqual(status, 1)
            run.assert_not_called()
            self.assertEqual(self.report(output)['category'], 'bundle_metadata')
            marker.unlink()

    def test_app_symlink_rejected_before_tool(self):
        original = self.app
        self.app = self.root/'linked.app'
        self.app.symlink_to(original, target_is_directory=True)
        status, output, run = self.invoke()
        self.assertEqual(status, 1)
        run.assert_not_called()
        self.assertEqual(self.report(output)['category'], 'bundle_metadata')

    def test_invalid_arguments_emit_no_supplied_values(self):
        stream = io.StringIO()
        with contextlib.redirect_stdout(stream):
            self.assertEqual(c.main([CANARY, CANARY]), 1)
        self.assertEqual(self.report(stream.getvalue())['category'], 'invalid_arguments')


class MachOMetadataTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.app = Path(self.tmp.name)/'Runner.app'
        self.app.mkdir()
        self.binary = self.app/'Runner'

    def test_real_tiny_files_present_and_absent(self):
        self.binary.write_bytes(macho())
        self.assertEqual(d.macho_signature(self.app), 'absent')
        self.binary.write_bytes(macho(True))
        self.assertEqual(d.macho_signature(self.app), 'present')

    def test_truncated_unknown_and_command_bounds(self):
        cases = [(b'', 'malformed'), (b'x'*32, 'unsupported'),
                 (struct.pack('<8I', 0xfeedfacf, 0x100000c, 0, 2, 4097, 0, 0, 0), 'malformed'),
                 (struct.pack('<8I', 0xfeedfacf, 0x100000c, 0, 2, 1, d.MAX_COMMAND_BYTES+1, 0, 0), 'malformed'),
                 (macho(True)[:40], 'malformed')]
        for data, expected in cases:
            self.binary.write_bytes(data)
            with self.subTest(expected=expected):
                self.assertEqual(d.macho_signature(self.app), expected)

    def test_malformed_command_size_and_trailing_bytes(self):
        self.binary.write_bytes(struct.pack('<8I', 0xfeedfacf, 0x100000c, 0, 2, 1, 8, 0, 0)
                                + struct.pack('<II', 0x1d, 8))
        self.assertEqual(d.macho_signature(self.app), 'present')
        self.binary.write_bytes(struct.pack('<8I', 0xfeedfacf, 0x100000c, 0, 2, 0, 8, 0, 0)+bytes(8))
        self.assertEqual(d.macho_signature(self.app), 'malformed')

    def test_binary_symlink_is_not_followed(self):
        external = self.app.parent/'external'
        external.write_text(CANARY)
        self.binary.symlink_to(external)
        with patch.object(d.os, 'pread') as read:
            self.assertEqual(d.macho_signature(self.app), 'unavailable')
            read.assert_not_called()

    def test_fifo_is_never_read_or_blocked(self):
        os.mkfifo(self.binary)
        with patch.object(d.os, 'pread') as read:
            self.assertEqual(d.macho_signature(self.app), 'unavailable')
            read.assert_not_called()

    def test_permission_failure_redacted_and_descriptors_closed(self):
        self.binary.write_bytes(macho())
        before = len(os.listdir('/dev/fd'))
        for _ in range(30):
            with patch.object(d.os, 'pread', side_effect=PermissionError(13, CANARY)):
                self.assertEqual(d.macho_signature(self.app), 'unavailable')
        self.assertEqual(len(os.listdir('/dev/fd')), before)


class UnsignedProjectionTests(unittest.TestCase):
    def row(self):
        return {'category': 'signature_present', 'codesign_returncode': 0,
                'unsigned_sentinel': False, 'signature_class': 'adhoc', 'macho_signature': 'present'}

    def encode(self, row):
        return (d.PREFIX + json.dumps(row) + '\n').encode()

    def test_only_fixed_schema_is_projected(self):
        self.assertEqual(d.unsigned_summary(self.encode(self.row())),
                         {'availability': 'present', **self.row()})
        self.assertEqual(d.unsigned_summary(b'PASS_UNSIGNED_APP\n'), {'availability': 'pass_sentinel'})

    def test_arbitrary_text_extra_fields_and_unknown_values_are_not_exported(self):
        values = [CANARY.encode(), self.encode({**self.row(), 'path': CANARY}),
                  self.encode({**self.row(), 'category': CANARY}),
                  self.encode({**self.row(), 'category': []}),
                  self.encode({**self.row(), 'codesign_returncode': True}),
                  self.encode({**self.row(), 'codesign_returncode': 10000}),
                  self.encode({**self.row(), 'unsigned_sentinel': 'true'}),
                  self.encode({**self.row(), 'signature_class': CANARY}),
                  self.encode({**self.row(), 'macho_signature': CANARY})]
        for data in values:
            with self.subTest(data=data[:30]):
                got = d.unsigned_summary(data)
                self.assertEqual(got, {'availability': 'invalid'})
                self.assertNotIn(CANARY, json.dumps(got))

    def test_duplicate_json_multiple_lines_and_oversize_rejected(self):
        duplicate = (d.PREFIX + '{"category":"signature_present","category":"bundle_metadata"}').encode()
        for data in (duplicate, self.encode(self.row())*2, b'x'*8193, b'\xff'):
            self.assertEqual(d.unsigned_summary(data), {'availability': 'invalid'})

    def test_deep_json_cannot_replace_primary_failure(self):
        nested = (d.PREFIX + '[' * 1001 + '0' + ']' * 1001).encode()
        self.assertLess(len(nested), 2048)
        self.assertEqual(d.unsigned_summary(nested), {'availability': 'invalid'})

    def test_missing_output_and_linker_flag_classification(self):
        self.assertEqual(d.unsigned_summary(b''), {'availability': 'missing'})
        self.assertEqual(d.signature_class(b'CodeDirectory flags=0x20002(adhoc,linker-signed)', 0), 'adhoc')
        self.assertEqual(d.signature_class(b'code object is not signed at all', 1), 'not_reported')

    def test_outer_runner_exports_only_projected_failure(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root/'logs').mkdir()
            runner = b.Runner.__new__(b.Runner)
            runner.work = root
            runner.flutter = root
            runner.sources = runner.flutter_sources = {'fixture': 'hash'}
            runner.sequence = 0
            runner.results = []
            runner.cancelled = False
            runner.guard = Mock()
            runner.env = {}
            # Harmless host Python emits a synthetic fixed report and exits; never Mach-O.
            code = 'import sys;sys.stdout.buffer.write('+repr(self.encode(self.row()))+');sys.exit(1)'
            with patch.object(b, 'git_snapshot', return_value={'fixture': 'hash'}), \
                 patch.object(b, 'emit') as emit:
                with self.assertRaisesRegex(b.GateError, '^command_failed_unsigned-iphonesimulator$'):
                    runner.run('unsigned-iphonesimulator', [sys.executable, '-c', code], cwd=root, timeout=5)
            end = [call for call in emit.call_args_list if call.args == ('command_end',)][0]
            self.assertEqual(end.kwargs['unsigned_result'], {'availability': 'present', **self.row()})
            self.assertEqual(runner.results[-1]['unsigned_result']['signature_class'], 'adhoc')


if __name__ == '__main__':
    unittest.main()

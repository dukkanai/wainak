"""Fixed opt-in budget tests. No compiler, cloud run, network, or large file."""
import contextlib
import copy
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

CI = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CI))
sys.path.insert(0, str(CI / 'ios'))
import build as b
import resources as r
import check_preparation as prep

GIB = 1024 ** 3
FLAG = '--logical-workspace-40gib-experiment'
EXPERIMENT = 'ios-unsigned-40gib-experiment'


class BudgetSelectionTests(unittest.TestCase):
    def reject_cli(self, args):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
            b.parse_args(args)
        self.assertEqual(error.exception.code, 2)

    def test_default_is_exact_eight_gib(self):
        self.assertEqual(b.MAX_BYTES, 8 * GIB)
        self.assertEqual(r.LIMIT, 8 * GIB)
        self.assertEqual(b.select_workspace_budget(), 8 * GIB)
        self.assertEqual(b.Runner.workspace_budget_bytes, 8 * GIB)

    def test_explicit_opt_in_is_exact_forty_gib(self):
        self.assertEqual(b.EXPERIMENT_MAX_BYTES, 40 * GIB)
        self.assertEqual(b.select_workspace_budget(True), 40 * GIB)
        self.assertEqual(b.select_workspace_budget(False), 8 * GIB)

    def test_non_boolean_opt_in_rejected(self):
        for value in (None, 0, 1, 'YES', '40', 40 * GIB, {}, []):
            with self.subTest(value=value), self.assertRaises(b.GateError):
                b.select_workspace_budget(value)

    def test_invalid_runner_opt_in_fails_before_filesystem(self):
        with self.assertRaises(b.GateError):
            b.Runner(None, None, workspace_40gib_experiment='true')

    def test_fixed_policy_no_arbitrary_limit(self):
        for value in (True, False, 0, 1, 8, 40, 8 * GIB - 1, 40 * GIB + 1, '42949672960'):
            with self.subTest(value=value), self.assertRaises(b.GateError):
                b.workspace_budget_policy(value)

    def test_policy_names_match_numeric_limits(self):
        self.assertEqual(b.workspace_budget_policy(8 * GIB),
                         {'limit_bytes': 8 * GIB, 'limit_policy': 'default_8gib'})
        self.assertEqual(b.workspace_budget_policy(40 * GIB),
                         {'limit_bytes': 40 * GIB, 'limit_policy': 'cloud_40gib_experiment'})

    def test_default_cli_no_opt_in(self):
        for mode in ('--check', '--build-unsigned'):
            self.assertFalse(b.parse_args([mode]).workspace_40gib_experiment)

    def test_exact_build_flag_selects_experiment(self):
        args = b.parse_args(['--build-unsigned', FLAG])
        self.assertTrue(args.workspace_40gib_experiment)
        self.assertTrue(args.build_unsigned)

    def test_flag_cannot_be_used_with_check_or_without_mode(self):
        self.reject_cli(['--check', FLAG])
        self.reject_cli([FLAG])

    def test_conflicting_modes_rejected(self):
        self.reject_cli(['--check', '--build-unsigned', FLAG])

    def test_flag_abbreviation_and_arbitrary_values_rejected(self):
        for tail in (['--logical-workspace'], [FLAG + '=40'], [FLAG, '40'],
                     ['--workspace-budget-bytes', str(40 * GIB)]):
            self.reject_cli(['--build-unsigned', *tail])

    def test_environment_does_not_select_cap(self):
        with patch.dict(os.environ, {'WAINAK_LOGICAL_BUDGET': '42949672960',
                                     'MAX_BYTES': '42949672960',
                                     'LLVM_CAS_MAX_MAPPING_SIZE': '104857600'}):
            self.assertEqual(b.select_workspace_budget(), 8 * GIB)
            self.assertFalse(b.parse_args(['--build-unsigned']).workspace_40gib_experiment)

    def test_experiment_does_not_bypass_mac_host_gate(self):
        with patch.object(sys, 'argv', ['build.py', '--build-unsigned', FLAG]), \
             patch.object(b, 'static_check', return_value={}), \
             patch.object(b.platform, 'system', return_value='Linux'), \
             patch.object(b, 'Runner') as runner:
            with self.assertRaisesRegex(b.GateError, '^requires_darwin_arm64$'):
                b.main()
            runner.assert_not_called()

    def test_experiment_does_not_bypass_codemagic_checkout_gate(self):
        with patch.object(sys, 'argv', ['build.py', '--build-unsigned', FLAG]), \
             patch.object(b, 'static_check', return_value={}), \
             patch.object(b.platform, 'system', return_value='Darwin'), \
             patch.object(b.platform, 'machine', return_value='arm64'), \
             patch.dict(os.environ, {}, clear=True), patch.object(b, 'Runner') as runner:
            with self.assertRaisesRegex(b.GateError, '^requires_explicit_codemagic_checkout$'):
                b.main()
            runner.assert_not_called()


class SelectedBudgetGuardTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def runner(self, limit=None):
        runner = b.Runner.__new__(b.Runner)
        runner.work = runner.flutter = self.root
        runner.flutter_start = 0
        runner.cancelled = False
        if limit is not None:
            runner.workspace_budget_bytes = limit
        return runner

    def guard(self, runner, total, free=4 * GIB):
        with patch.object(b, 'size', side_effect=[total, 0, 0, 0, 0]), \
             patch.object(r.shutil, 'disk_usage', return_value=Mock(free=free)), \
             patch.object(b, 'large_file_summary', return_value={'complete': True, 'rows': []}):
            runner.guard()

    def test_default_boundary_and_one_byte_over(self):
        runner = self.runner()
        self.guard(runner, 8 * GIB)
        with self.assertRaisesRegex(b.GateError, '^workspace_budget$'):
            self.guard(runner, 8 * GIB + 1)
        self.assertEqual(runner.resource_snapshot['limit_bytes'], 8 * GIB)

    def test_experimental_boundary_and_one_byte_over(self):
        runner = self.runner(40 * GIB)
        self.guard(runner, 40 * GIB)
        with self.assertRaisesRegex(b.GateError, '^workspace_budget$'):
            self.guard(runner, 40 * GIB + 1)
        self.assertEqual(runner.resource_snapshot['limit_bytes'], 40 * GIB)
        self.assertEqual(runner.resource_snapshot['limit_policy'], 'cloud_40gib_experiment')

    def test_observed_eleventh_total_passes_only_selected_cap(self):
        total = 27459310362
        with self.assertRaisesRegex(b.GateError, '^workspace_budget$'):
            self.guard(self.runner(), total)
        selected = self.runner(40 * GIB)
        self.guard(selected, total)
        self.assertEqual(selected.resource_snapshot['total_logical_bytes'], total)

    def test_second_twentyfive_gib_cache_still_fails_forty(self):
        with self.assertRaisesRegex(b.GateError, '^workspace_budget$'):
            self.guard(self.runner(40 * GIB), 50 * GIB)

    def test_free_disk_floor_not_relaxed(self):
        for limit in (8 * GIB, 40 * GIB):
            runner = self.runner(limit)
            self.guard(runner, 1, free=4 * GIB)
            with self.subTest(limit=limit), self.assertRaisesRegex(b.GateError, '^disk_headroom$'):
                self.guard(runner, 1, free=4 * GIB - 1)
            self.assertEqual(runner.resource_snapshot['minimum_free_bytes'], 4 * GIB)

    def test_selected_limit_does_not_change_other_instances(self):
        selected, normal = self.runner(40 * GIB), self.runner()
        self.guard(selected, 9 * GIB)
        with self.assertRaisesRegex(b.GateError, '^workspace_budget$'):
            self.guard(normal, 9 * GIB)
        self.assertEqual(b.MAX_BYTES, 8 * GIB)
        self.assertEqual(r.LIMIT, 8 * GIB)

    def test_corrupt_limit_fails_closed_before_measurement(self):
        runner = self.runner(41 * GIB)
        runner.resource_snapshot = {'old': True}
        with patch.object(b, 'budget_snapshot') as measure, self.assertRaises(b.GateError):
            runner.guard()
        measure.assert_not_called()
        self.assertIsNone(runner.resource_snapshot)

    def test_permission_error_remains_fatal_and_no_stale_sample(self):
        runner = self.runner(40 * GIB)
        runner.resource_snapshot = {'old': True}
        with patch.object(b, 'size', side_effect=PermissionError(13, 'private')):
            with self.assertRaises(PermissionError):
                runner.guard()
        self.assertIsNone(runner.resource_snapshot)

    def test_cancellation_remains_fatal(self):
        runner = self.runner(40 * GIB)
        runner.cancelled = True
        with self.assertRaisesRegex(b.GateError, '^cancelled$'):
            runner.guard()

    def test_tiny_real_sparse_file_still_counts_logical_bytes(self):
        path = self.root / 'tiny-sparse'
        with path.open('wb') as file:
            file.truncate(1024 * 1024)
        runner = self.runner(40 * GIB)
        with patch.object(b, 'APP', self.root/'absent-app'), \
             patch.object(r.shutil, 'disk_usage', return_value=Mock(free=4 * GIB)):
            runner.flutter_start = b.size(self.root)
            runner.guard()
        self.assertGreaterEqual(runner.resource_snapshot['components']['work'], 1024 * 1024)
        self.assertEqual(runner.resource_snapshot['limit_bytes'], 40 * GIB)
        self.assertFalse(runner.resource_snapshot['hard_quota'])


class ExperimentalWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.config = prep.read_json(prep.ROOT / 'codemagic.yaml')

    def test_exact_two_manually_started_workflows(self):
        self.assertEqual(set(self.config['workflows']), {'ios-unsigned-archive', EXPERIMENT})
        prep.validate_workflow(self.config)
        for workflow in self.config['workflows'].values():
            self.assertEqual(workflow['instance_type'], 'mac_mini_m2')
            self.assertEqual(workflow['max_build_duration'], 45)
            self.assertEqual(workflow['environment'], {'xcode': '26.4.1', 'flutter': '3.47.8'})
            self.assertNotIn('triggering', workflow)
            self.assertNotIn('publishing', workflow)

    def test_only_experimental_compile_command_has_flag(self):
        normal = self.config['workflows']['ios-unsigned-archive']
        selected = self.config['workflows'][EXPERIMENT]
        self.assertEqual([x['script'] for x in normal['scripts']], prep.COMMANDS)
        self.assertEqual(selected['scripts'][:-1], normal['scripts'][:-1])
        self.assertEqual(selected['scripts'][-1]['script'], prep.COMMANDS[-1] + ' ' + FLAG)

    def test_workflow_missing_or_extra_rejected(self):
        for remove in (True, False):
            candidate = copy.deepcopy(self.config)
            if remove:
                del candidate['workflows'][EXPERIMENT]
            else:
                candidate['workflows']['unreviewed'] = {}
            with self.assertRaises(prep.InvalidPreparation):
                prep.validate_workflow(candidate)

    def test_opt_in_cannot_be_added_to_normal_or_removed_from_experiment(self):
        for key in ('ios-unsigned-archive', EXPERIMENT):
            candidate = copy.deepcopy(self.config)
            command = candidate['workflows'][key]['scripts'][-1]
            command['script'] = prep.COMMANDS[-1] if key == EXPERIMENT else prep.COMMANDS[-1] + ' ' + FLAG
            with self.subTest(key=key), self.assertRaises(prep.InvalidPreparation):
                prep.validate_workflow(candidate)

    def test_experimental_safety_keys_are_exact(self):
        mutations = [
            lambda w: w.update(triggering={'events': ['push']}),
            lambda w: w.update(artifacts=['**/*.ipa']),
            lambda w: w.update(publishing={}),
            lambda w: w['environment'].update(groups=['secrets']),
            lambda w: w['environment'].update(vars={'MAX_BYTES': 'unreviewed'}),
            lambda w: w.update(max_build_duration=46),
            lambda w: w.update(max_build_duration=True),
            lambda w: w.update(instance_type='linux_x2'),
            lambda w: w['scripts'][-1].update(script=prep.COMMANDS[-1] + ' ' + FLAG + '; echo extra'),
        ]
        for index, mutate in enumerate(mutations):
            candidate = copy.deepcopy(self.config)
            mutate(candidate['workflows'][EXPERIMENT])
            with self.subTest(index=index), self.assertRaises(prep.InvalidPreparation):
                prep.validate_workflow(candidate)


if __name__ == '__main__':
    unittest.main()

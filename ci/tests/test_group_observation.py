import errno
import json
import os
from pathlib import Path
import signal
import sys
import unittest
from unittest import mock
from ci.testflight import group_observation as g
from scripts import ci_process as cp


class GroupObservation(unittest.TestCase):
    def test_linux_and_darwin_states_only_aggregate_counts(self):
        text='10 1 10 Z 500\n11 10 10 S+ 500\n12 1 10 ? 501\n20 1 20 R 500\n'
        result=g.parse(text,10,500)
        self.assertEqual(result,{'status':'OK','members':3,'zombies':1,'live':1,'unknown_state':1,
            'same_uid':2,'leader':1,'parent_is_init':2})
        self.assertEqual(g.project({**result,'argv':'CANARY','env':'CANARY'}),result)
        for bad in ('CANARY','1 2 3 S CANARY','1 2 3 S 4\n1 2 3 S 4','x'*1048577):
            self.assertEqual(g.parse(bad,10,500),{'status':'MALFORMED'})
        for bad in ({'status':'CANARY'}, {'status':'OK'}, {**result,'zombies':True}, {**result,'live':20000}):
            self.assertNotIn('CANARY',json.dumps(g.project(bad)))
            self.assertNotEqual(g.project(bad)['status'],'OK')

    def test_real_ps_snapshot_has_no_process_identifiers(self):
        row=g.capture(os.getpgrp())
        self.assertEqual(row['status'],'OK')
        self.assertGreater(row['members'],0)
        self.assertEqual(set(row),{'status',*g.FIELDS})

    def test_capture_fixed_command_bounds_and_error_projection(self):
        for host in ('linux','darwin'):
            with mock.patch.object(g.sys,'platform',host),mock.patch.object(cp,'run_bounded',return_value=mock.Mock(stdout='')) as run:
                self.assertEqual(g.capture(10)['members'],0)
                self.assertEqual(run.call_args.args[0],['/bin/ps','-axo','pid=,ppid=,pgid=,stat=,uid='])
                self.assertEqual(run.call_args.kwargs['seconds'],2)
                self.assertNotIn('group_observer',run.call_args.kwargs)
        with mock.patch.object(cp,'run_bounded',side_effect=RuntimeError('CANARY')):
            self.assertEqual(g.capture(10),{'status':'UNAVAILABLE'})

    def test_observer_failure_cannot_skip_cleanup_or_hide_eperm(self):
        actual=cp.cleanup_process
        for failure in (None,PermissionError(errno.EPERM,'CANARY')):
            for observer_error in (RuntimeError('CANARY'),KeyboardInterrupt()):
                detail={};calls=[]
                def cleanup(process,selector):
                    calls.append(True);result=actual(process,selector)
                    if failure:return result+[{'operation':'verify_group_gone','type':'PermissionError','errno':1}]
                    return result
                with mock.patch.object(cp,'cleanup_process',side_effect=cleanup):
                    action=lambda:cp.run_bounded([sys.executable,'-c','pass'],cwd=Path.cwd(),seconds=5,
                        diagnostic=detail,group_observer=mock.Mock(side_effect=observer_error))
                    if failure or isinstance(observer_error,KeyboardInterrupt):
                        with self.assertRaises((RuntimeError,InterruptedError)):action()
                    else:action()
                self.assertEqual(calls,[True]);self.assertEqual(detail['cleanup_failed'],bool(failure))
                self.assertNotIn('CANARY',json.dumps(detail))

    def test_zero_member_snapshot_never_authorizes_eperm(self):
        detail={};actual=cp.cleanup_process
        def cleanup(process,selector):
            result=actual(process,selector)
            return result+[{'operation':'verify_group_gone','type':'PermissionError','errno':1}]
        with mock.patch.object(cp,'cleanup_process',side_effect=cleanup):
            with self.assertRaises(RuntimeError):cp.run_bounded([sys.executable,'-c','pass'],cwd='/',seconds=5,
                diagnostic=detail,group_observer=lambda _:g.parse('',1,1))
        self.assertTrue(detail['cleanup_failed']);self.assertEqual(detail['group_after_cleanup']['members'],0)

    def test_observer_own_cleanup_failure_is_never_swallowed(self):
        detail={}
        with self.assertRaisesRegex(RuntimeError,'cleanup could not be verified'):
            cp.run_bounded([sys.executable,'-c','pass'],cwd='/',seconds=5,diagnostic=detail,
                group_observer=lambda _: {'status':'UNAVAILABLE','observer_cleanup_failed':True})
        self.assertTrue(detail['cleanup_failed'])
        self.assertEqual(detail['cleanup_errors'][0],{'operation':'observer_cleanup','type':'UnverifiedProcessGroup'})
        def uncertain(*args,**kwargs):
            kwargs['diagnostic']['cleanup_failed']=True
            raise RuntimeError('CANARY')
        with mock.patch.object(cp,'run_bounded',side_effect=uncertain):
            self.assertEqual(g.capture(10),{'status':'UNAVAILABLE','observer_cleanup_failed':True})

"""Independent lifecycle probes for the candidate-owned subprocess group only."""
import importlib.util
import os
from pathlib import Path
import signal
import sys
import tempfile
import time
import unittest
sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('candidate_archive_runner',ROOT/'archive/run_checks.py')
runner=importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)

def qa_live(pgid):
    found=[]
    for entry in Path('/proc').iterdir():
        if not entry.name.isdigit():continue
        try:
            if os.getpgid(int(entry.name)) != pgid:continue
            state=(entry/'stat').read_text().rsplit(')',1)[1].split()[0]
            if state not in ('Z','X'):found.append(int(entry.name))
        except (ProcessLookupError,FileNotFoundError):pass
    return found

class IndependentLifecycle(unittest.TestCase):
    def probe(self,mode):
        with tempfile.TemporaryDirectory(prefix='wainak-archive-qa-lifecycle-') as tmp:
            marker=Path(tmp)/'owned-pgid'
            child='import os,signal,time;signal.signal(signal.SIGTERM,signal.SIG_IGN);'
            if mode=='closed_pipe':child+='os.close(1);os.close(2);'
            child+='time.sleep(30)'
            leader='import os,pathlib,subprocess,sys,time;pathlib.Path(sys.argv[1]).write_text(str(os.getpgrp()));subprocess.Popen([sys.executable,"-c",sys.argv[2]]);'
            if mode=='output_bound':leader+='time.sleep(.1);os.write(1,b"x"*(9*1024*1024));time.sleep(30)'
            pgid=None
            started=time.monotonic()
            try:
                with self.assertRaises(RuntimeError):
                    runner.bounded_run([sys.executable,'-c',leader,str(marker),child],str(ROOT),{'PATH':'/usr/bin:/bin'},timeout=.4 if mode=='held_pipe' else 3)
                pgid=int(marker.read_text())
                self.assertNotEqual(pgid,os.getpgrp())
                self.assertFalse(qa_live(pgid),'owned descendant remains live')
                self.assertLess(time.monotonic()-started,9)
            finally:
                # Preserve cleanup even if the subject regresses. Only the PGID
                # written by our own newly-sessioned fixture is eligible.
                if pgid is None and marker.exists():pgid=int(marker.read_text())
                if pgid is not None and pgid!=os.getpgrp() and qa_live(pgid):
                    try:os.killpg(pgid,signal.SIGKILL)
                    except ProcessLookupError:pass
    def test_exited_leader_retained_pipe(self):self.probe('held_pipe')
    def test_exited_leader_closed_pipe_live_child(self):self.probe('closed_pipe')
    def test_output_bound_reaps_group(self):self.probe('output_bound')
    def test_positive_control(self):
        code,out,_=runner.bounded_run([sys.executable,'-c','print("qa_control")'],str(ROOT),{'PATH':'/usr/bin:/bin'},2)
        self.assertEqual(code,0);self.assertEqual(out,b'qa_control\n')

if __name__=='__main__':unittest.main(verbosity=2)

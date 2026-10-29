"""Bounded host CI commands with cleanup of their own process group only."""
import os
from pathlib import Path
import selectors
import signal
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ci.ios.diagnostics import cleanup_process, project_cleanup_errors, safe_error
from scripts import security_diagnostics as security
from scripts import regression_diagnostics as regressions
from scripts import ipa_diagnostics as ipa


def run_bounded(command, *, cwd, env=None, seconds=300, maximum=16 * 1024 * 1024,
                check=False, cleanup_grace=0, diagnostic=None, group_observer=None,
                output_profile=None, stdout_only=False):
    """Capture bounded output; never print command arguments or child output.

    Default capture merges channels. stdout_only keeps stderr out of machine
    output, drains/counts it under the SAME combined limit, and never returns it.

    POSIX host tools must keep children in the inherited group. Nested fixture
    drivers additionally own their independently created sessions and containers.
    A successful direct child with a surviving descendant is also cleaned up.
    """
    if seconds <= 0 or maximum <= 0 or not 0 <= cleanup_grace <= 120:
        raise ValueError('Command limits must be positive')
    # Optional caller-owned metadata only. Never attach argv, environment,
    # exception objects or captured output; existing exception contracts remain.
    if diagnostic is not None and type(diagnostic) is not dict:
        raise TypeError('Diagnostic destination must be a plain dictionary')
    if output_profile is not None and (type(output_profile) is not str or output_profile not in {security.PROFILE,regressions.PROFILE,ipa.PROFILE}):
        raise ValueError('Unknown output diagnostic profile')
    if type(stdout_only) is not bool or (stdout_only and output_profile is not None):
        raise ValueError('Invalid channel capture mode')
    kind = 'NONE'
    code = None
    cleanup_failed = False
    cleanup_errors = []
    group_before = group_after = None
    process = selector = primary = None
    output = bytearray()
    stderr_bytes = 0
    previous = signal.getsignal(signal.SIGTERM)

    observer_cancelled = False

    def observe():
        nonlocal observer_cancelled
        if group_observer is None or process is None:
            return None
        try:
            result = group_observer(process.pid)
            if type(result) is dict and result.get('observer_cancelled') is True:
                observer_cancelled = True
            if type(result) is dict and result.get('observer_cleanup_failed') is True:
                cleanup_errors.append({'operation': 'observer_cleanup', 'type': 'UnverifiedProcessGroup'})
            return result
        except BaseException as error:
            if isinstance(error, (InterruptedError, KeyboardInterrupt, SystemExit)):
                observer_cancelled = True
            return {"status": "UNAVAILABLE"}

    def cancelled(*_):
        raise InterruptedError('Host CI command cancelled')

    signal.signal(signal.SIGTERM, cancelled)
    try:
        process = subprocess.Popen([str(value) for value in command], cwd=cwd, env=env,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE if stdout_only else subprocess.STDOUT,
                                   start_new_session=True)
        selector = selectors.DefaultSelector()
        selector.register(process.stdout, selectors.EVENT_READ)
        if stdout_only:selector.register(process.stderr, selectors.EVENT_READ)
        deadline = time.monotonic() + seconds
        while selector.get_map() or process.poll() is None:
            if time.monotonic() >= deadline:
                kind = 'TIMEOUT'
                raise TimeoutError('Host CI command exceeded its time limit')
            for key, _ in selector.select(min(.2, max(0, deadline - time.monotonic()))):
                block = os.read(key.fd, 65536)
                if not block:
                    selector.unregister(key.fileobj)
                elif len(output) + stderr_bytes + len(block) > maximum:
                    kind = 'OUTPUT_BOUND'
                    raise RuntimeError('Host CI command exceeded its output limit')
                else:
                    if stdout_only and key.fileobj is process.stderr:stderr_bytes+=len(block)
                    else:output.extend(block)
        code = process.wait(timeout=max(.01, deadline - time.monotonic()))
        if code:
            kind = 'NONZERO_EXIT'
        if check and code:
            raise RuntimeError('Host CI command failed with exit code ' + str(code))
        return subprocess.CompletedProcess([], code, bytes(output).decode('utf-8', errors='replace'), '')
    except BaseException as error:
        primary = error
        if kind == 'NONE':
            if isinstance(error, (TimeoutError, subprocess.TimeoutExpired)):
                kind = 'TIMEOUT'
            elif isinstance(error, (InterruptedError, KeyboardInterrupt, SystemExit)):
                kind = 'CANCELLED'
            elif isinstance(error, OSError):
                kind = 'SPAWN_OR_IO'
            else:
                kind = 'OTHER'
        raise
    finally:
        try:
            # Fixture drivers own nested sessions and disposable containers.
            # Let their signal handler complete finally blocks before fallback
            # group cleanup. Always reap the direct child, not just probe a PID.
            if primary is not None and process is not None and cleanup_grace:
                try:
                    process.poll()
                    os.killpg(process.pid, signal.SIGTERM)
                    end=time.monotonic()+cleanup_grace
                    while time.monotonic() < end:
                        process.poll()  # Reap the leader while its descendants finish.
                        try:
                            os.killpg(process.pid,0)
                        except ProcessLookupError:
                            break
                        time.sleep(.05)
                    process.wait(timeout=max(.01,end-time.monotonic()))
                except ProcessLookupError:
                    pass  # Owned group is already absent.
                except BaseException as error:
                    # Never let signal/probe/reap failure bypass final group cleanup
                    # or replace the original timeout/cancellation failure.
                    cleanup_errors.append({'operation': 'grace_cleanup', **safe_error(error)})
            group_before = observe()
            try:
                failures = cleanup_process(process, selector)
            except BaseException as error:
                cleanup_errors.append({'operation': 'cleanup_process', **safe_error(error)})
                cleanup_failed = True
                failures = []
            cleanup_errors.extend(failures)
            cleanup_failed = bool(cleanup_errors)
            group_after = observe()
            cleanup_failed = bool(cleanup_errors)
            if observer_cancelled and primary is None:
                kind = "CANCELLED"
                raise InterruptedError("Host CI command cancelled")
            if cleanup_failed and primary is None:
                kind = 'CLEANUP'
                raise RuntimeError('Host CI owned process cleanup could not be verified')
        finally:
            try:
                signal.signal(signal.SIGTERM, previous)
            finally:
                if diagnostic is not None:
                    diagnostic.clear()
                    diagnostic.update(failure_kind=kind, exit_code=code,
                                      output_bytes=len(output)+stderr_bytes, cleanup_failed=cleanup_failed)
                    if stdout_only:diagnostic.update(stdout_bytes=len(output),stderr_bytes=stderr_bytes)
                    diagnostic.update(project_cleanup_errors(cleanup_errors))
                    if group_observer is not None:
                        diagnostic.update(group_before_cleanup=group_before, group_after_cleanup=group_after)
                    if output_profile==security.PROFILE:
                        classified='NOT_APPLICABLE'
                        if kind=='NONZERO_EXIT' and code:
                            try:classified=security.project(security.classify(output))
                            except Exception:classified='CLASSIFIER_FAILED'
                        diagnostic['security_error']=classified
                    if output_profile==regressions.PROFILE and kind=='NONZERO_EXIT' and code:
                        try:
                            allowed=regressions.catalogue()
                            diagnostic['regression_summary']=regressions.project(regressions.classify(output,allowed),allowed)
                        except Exception:
                            diagnostic['regression_summary']={'status':'CLASSIFIER_FAILED','failures':[],'errors':[],'tests_run':None}
                    if output_profile==ipa.PROFILE:
                        try:diagnostic['ipa_summary']=ipa.project(ipa.classify(output,code is not None and kind in {'NONE','NONZERO_EXIT','CLEANUP'}))
                        except Exception:diagnostic['ipa_summary']=ipa.empty('CLASSIFIER_FAILED')

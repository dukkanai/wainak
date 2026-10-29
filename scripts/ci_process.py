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


def run_bounded(command, *, cwd, env=None, seconds=300, maximum=16 * 1024 * 1024,
                check=False, cleanup_grace=0, diagnostic=None):
    """Capture bounded merged output; never print command arguments or child output.

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
    kind = 'NONE'
    code = None
    cleanup_failed = False
    cleanup_errors = []
    process = selector = primary = None
    output = bytearray()
    previous = signal.getsignal(signal.SIGTERM)

    def cancelled(*_):
        raise InterruptedError('Host CI command cancelled')

    signal.signal(signal.SIGTERM, cancelled)
    try:
        process = subprocess.Popen([str(value) for value in command], cwd=cwd, env=env,
                                   stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                   start_new_session=True)
        selector = selectors.DefaultSelector()
        selector.register(process.stdout, selectors.EVENT_READ)
        deadline = time.monotonic() + seconds
        while selector.get_map() or process.poll() is None:
            if time.monotonic() >= deadline:
                kind = 'TIMEOUT'
                raise TimeoutError('Host CI command exceeded its time limit')
            for key, _ in selector.select(min(.2, max(0, deadline - time.monotonic()))):
                block = os.read(key.fd, 65536)
                if not block:
                    selector.unregister(key.fileobj)
                elif len(output) + len(block) > maximum:
                    kind = 'OUTPUT_BOUND'
                    raise RuntimeError('Host CI command exceeded its output limit')
                else:
                    output.extend(block)
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
            try:
                failures = cleanup_process(process, selector)
            except BaseException as error:
                cleanup_errors.append({'operation': 'cleanup_process', **safe_error(error)})
                cleanup_failed = True
                if primary is None:
                    kind = 'CLEANUP'
                    raise
                failures = []
            cleanup_errors.extend(failures)
            cleanup_failed = bool(cleanup_errors)
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
                                      output_bytes=len(output), cleanup_failed=cleanup_failed)
                    diagnostic.update(project_cleanup_errors(cleanup_errors))

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
from ci.ios.diagnostics import cleanup_process  # Reuse the reviewed group cleanup.


def run_bounded(command, *, cwd, env=None, seconds=300, maximum=16 * 1024 * 1024,
                check=False, cleanup_grace=0):
    """Capture bounded merged output; never print command arguments or child output.

    POSIX host tools must keep children in the inherited group. Nested fixture
    drivers additionally own their independently created sessions and containers.
    A successful direct child with a surviving descendant is also cleaned up.
    """
    if seconds <= 0 or maximum <= 0 or not 0 <= cleanup_grace <= 120:
        raise ValueError('Command limits must be positive')
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
                raise TimeoutError('Host CI command exceeded its time limit')
            for key, _ in selector.select(min(.2, max(0, deadline - time.monotonic()))):
                block = os.read(key.fd, 65536)
                if not block:
                    selector.unregister(key.fileobj)
                elif len(output) + len(block) > maximum:
                    raise RuntimeError('Host CI command exceeded its output limit')
                else:
                    output.extend(block)
        code = process.wait(timeout=max(.01, deadline - time.monotonic()))
        if check and code:
            raise RuntimeError('Host CI command failed with exit code ' + str(code))
        return subprocess.CompletedProcess([], code, bytes(output).decode('utf-8', errors='replace'), '')
    except BaseException as error:
        primary = error
        raise
    finally:
        try:
            # Fixture drivers own nested sessions and disposable containers.
            # Let their signal handler complete finally blocks before fallback
            # group cleanup. Always reap the direct child, not just probe a PID.
            if primary is not None and process is not None and cleanup_grace:
                try:
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
                except BaseException:
                    # Never let signal/probe/reap failure bypass final group cleanup
                    # or replace the original timeout/cancellation failure.
                    pass
            failures = cleanup_process(process, selector)
            if failures and primary is None:
                raise RuntimeError('Host CI owned process cleanup could not be verified')
        finally:
            signal.signal(signal.SIGTERM, previous)

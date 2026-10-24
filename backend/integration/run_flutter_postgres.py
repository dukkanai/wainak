#!/usr/bin/env python3
"""Opt-in Flutter -> real loopback HTTP -> disposable PostgreSQL acceptance.

No admin endpoint, external binding, real account, persistent secret, or live DB.
The external Flutter test must implement the documented non-secret marker protocol.
"""

import argparse
import hashlib
import json
import multiprocessing
import os
from pathlib import Path
import re
import signal
import stat
import subprocess
import time
import unittest
import urllib.request
from wsgiref.simple_server import WSGIRequestHandler, make_server

import run_postgres


class QuietRequests(WSGIRequestHandler):
    def log_message(self, *args):
        pass


def serve(connect, port, pipe):
    # fork creates a new application process with the private connection factory.
    # There are no open database connections at fork and no secret in process argv.
    from wainak.api import DevelopmentApplication
    from wainak.domain import DevelopmentService
    from wainak.postgres import PostgresRepository
    app = DevelopmentApplication(enable_development=True, service=DevelopmentService(
        repository=PostgresRepository(connect, enable_synthetic_persistence=True)))
    try:
        with make_server("127.0.0.1", port, app, handler_class=QuietRequests) as server:
            pipe.send(server.server_port)
            pipe.close()
            server.serve_forever()
    finally:
        pipe.close()


def start_server(connect, port=0):
    context = multiprocessing.get_context("fork")
    receiving, sending = context.Pipe(duplex=False)
    process = context.Process(target=serve, args=(connect, port, sending))
    process.start()
    sending.close()
    try:
        if not receiving.poll(15):
            raise RuntimeError("Temporary HTTP server did not report readiness")
        actual_port = receiving.recv()
        if type(actual_port) is not int or not 1024 <= actual_port <= 65535:
            raise RuntimeError("Unexpected temporary loopback port")
        # Disable proxies explicitly; this request must remain local.
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(f"http://127.0.0.1:{actual_port}/health", timeout=5) as response:
            health = json.load(response)
        if health != {"status": "ok", "mode": "synthetic_development_only", "durable_storage": True}:
            raise RuntimeError("HTTP server is not the synthetic PostgreSQL adapter")
        return process, actual_port
    except BaseException:
        stop_server(process)
        raise
    finally:
        receiving.close()


def stop_server(process):
    if process is None:
        return
    if process.is_alive():
        process.terminate()
    process.join(5)
    if process.is_alive():
        process.kill()
        process.join(5)
    if process.is_alive():
        raise RuntimeError("Temporary HTTP process did not stop")


def stop_flutter(process):
    if process is None or process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass  # The exact owned child may exit between poll and killpg.
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait(timeout=10)


def cleanup_children(process, server, drain):
    # Never let a client kill/wait/pipe failure bypass server cleanup.
    try:
        try:
            stop_flutter(process)
        finally:
            if process is not None and process.stdout is not None:
                try:
                    drain()
                finally:
                    process.stdout.close()
    finally:
        stop_server(server)


def owned_test(mobile_root, relative):
    relative = Path(relative)
    if (relative.is_absolute() or ".." in relative.parts or not relative.parts
            or relative.parts[0] != "test" or not relative.name.endswith("_test.dart")):
        raise RuntimeError("Test must be a local relative test/*_test.dart path")
    test = mobile_root / relative
    test_root = (mobile_root / "test").resolve()
    if (not test_root.is_relative_to(mobile_root.resolve()) or test.is_symlink() or not test.is_file() or test.stat().st_uid != os.getuid()
            or not test.resolve().is_relative_to(test_root)):
        raise RuntimeError("The reviewed native integration test must be an owned regular file inside test/")
    return test


def heap_flags(value):
    parts = value.split()
    names = []
    if not parts or len(parts) > 2:
        raise RuntimeError("Only explicit Dart heap-size flags may be forwarded")
    for item in parts:
        match = re.fullmatch(r"--(old_gen_heap_size|new_gen_semi_max_size)=([0-9]{1,4})", item)
        if not match:
            raise RuntimeError("Only explicit Dart heap-size flags may be forwarded")
        names.append(match[1])
    if len(set(names)) != len(names):
        raise RuntimeError("Duplicate Dart heap-size flags are not allowed")
    return value


def validate_marker(path, expected):
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_size > 32:
        raise RuntimeError("Unexpected test control marker type, owner or size")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        current = os.fstat(stream.fileno())
        if (current.st_dev, current.st_ino) != (info.st_dev, info.st_ino):
            raise RuntimeError("Test control marker changed during validation")
        if stream.read(33) != expected.encode("ascii"):
            raise RuntimeError("Unexpected test control marker content")


def create_marker(path, content):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w") as stream:
        stream.write(content)


def safe_failure_output(output):
    # Never echo a bearer credential if a future test accidentally logs one.
    output = re.sub(r"(?i)(Bearer\s+)[A-Za-z0-9._-]+", r"\1[REDACTED]", output)
    output = re.sub(r"[A-Za-z0-9_-]{32,}", "[REDACTED_LONG_VALUE]", output)
    return output[-6000:]


def git_state(root):
    # The harness itself must run as the project owner, never as root.
    head = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], check=True,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True).stdout.strip()
    dirty = subprocess.run(["git", "-C", str(root), "status", "--porcelain"], check=True,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True).stdout
    return {"commit": head, "dirty": bool(dirty)}


def run_chain(connect, restart_database, temporary, mobile_root, tools_root, relative_test):
    if os.geteuid() == 0:
        raise RuntimeError("Run the integration harness as the project owner, not root")
    test = owned_test(mobile_root, relative_test)
    test_hash = hashlib.sha256(test.read_bytes()).hexdigest()
    frontend_state, backend_state = git_state(mobile_root), git_state(run_postgres.ROOT)
    flutter = tools_root / "flutter/bin/flutter"
    if not flutter.is_file() or not os.access(flutter, os.X_OK):
        raise RuntimeError("An existing owned Flutter SDK is required; no installation is attempted")
    if not (tools_root / "flutter/bin/cache/artifacts/engine/linux-x64/flutter_tester").is_file():
        raise RuntimeError("The native Flutter test engine must already be cached; prepare it separately")
    for directory in (tools_root / "home", tools_root / "pub-cache"):
        if not directory.is_dir() or not os.access(directory, os.R_OK | os.W_OK | os.X_OK):
            raise RuntimeError("The project-owned Flutter home/cache must already be accessible")
    with connect() as connection:
        connection.execute("TRUNCATE wainak_phase1_dev.accounts CASCADE")
    control = temporary / "flutter-control"
    control.mkdir(mode=0o700)
    server, port = start_server(connect)
    server_pids = [server.pid]
    completed = []
    process = None
    output = []
    output_bytes = 0
    def drain_output():
        nonlocal output_bytes
        if process is None or process.stdout is None:
            return
        while True:
            try:
                chunk = os.read(process.stdout.fileno(), 65536)
            except BlockingIOError:
                break
            if not chunk:
                break
            if output_bytes < 128 * 1024:
                output.append(chunk[:128 * 1024 - output_bytes])
                output_bytes += len(output[-1])
    try:
        # Do not forward the owner connector's environment, DB passwords, tokens,
        # mail configuration or arbitrary network credentials to the build.
        environment = {"PATH": str(tools_root / "flutter/bin") + os.pathsep + os.defpath,
                       "HOME": str(tools_root / "home"), "PUB_CACHE": str(tools_root / "pub-cache"),
                       "FLUTTER_ROOT": str(tools_root / "flutter"), "CI": "true", "LANG": "C.UTF-8",
                       "FLUTTER_SUPPRESS_ANALYTICS": "true", "DART_SUPPRESS_ANALYTICS": "true",
                       "WAINAK_TEST_BASE_URL": f"http://127.0.0.1:{port}",
                       "WAINAK_TEST_CONTROL_DIR": str(control)}
        # Optional VM tuning is explicit caller-owned test configuration, not a
        # change to the SDK, cgroup, system service, or global environment.
        for key in ("DART_VM_OPTIONS", "FLUTTER_TOOL_ARGS"):
            if os.environ.get(key):
                environment[key] = heap_flags(os.environ[key])
        process = subprocess.Popen([str(flutter), "test", "--no-pub", "--concurrency=1", "--reporter=expanded",
                                    str(relative_test)], cwd=mobile_root,
                                   env=environment, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                   start_new_session=True)
        # Drain without a background thread: subsequent fresh WSGI forks must not
        # fork a multithreaded Python process or inherit locked reader state.
        os.set_blocking(process.stdout.fileno(), False)
        for phase in ("active", "blocked"):
            ready = control / f"{phase}.ready"
            deadline = time.monotonic() + 120
            while not ready.exists():
                drain_output()
                if process.poll() is not None:
                    raise RuntimeError(f"Flutter exited before the {phase} persistence checkpoint")
                if time.monotonic() >= deadline:
                    raise RuntimeError(f"Flutter did not reach the {phase} checkpoint in time")
                time.sleep(0.1)
            validate_marker(ready, "ready")
            stop_server(server)
            server = None
            restart_database()
            server, resumed_port = start_server(connect, port)
            if resumed_port != port:
                raise RuntimeError("Restart changed the test client's loopback address")
            server_pids.append(server.pid)
            create_marker(control / f"{phase}.resumed", "resumed")
            completed.append(phase)
        deadline = time.monotonic() + 120
        while process.poll() is None:
            drain_output()
            if time.monotonic() >= deadline:
                raise RuntimeError("Flutter did not finish after the persistence checkpoints")
            time.sleep(0.1)
        code = process.wait(timeout=1)
        drain_output()
        if code != 0:
            raise RuntimeError(f"Flutter integration test failed with exit {code}")
        if completed != ["active", "blocked"] or len(set(server_pids)) != 3:
            raise RuntimeError("Both real process/database restart checkpoints are required")
        if hashlib.sha256(test.read_bytes()).hexdigest() != test_hash:
            raise RuntimeError("Flutter test source changed during this run")
        print(json.dumps({"flutter_http_postgres_chain": "passed", "backend": backend_state,
                          "mobile": frontend_state, "test_file": str(relative_test), "test_sha256": test_hash,
                          "loopback_only": True, "application_processes": len(server_pids),
                          "database_restarts_during_flutter": 2, "checkpoints": completed,
                          "database_credentials_passed_to_flutter": False, "real_auth_or_payment": False}, sort_keys=True))
    except BaseException:
        drain_output()
        print(safe_failure_output(b"".join(output).decode("utf-8", errors="replace")))
        raise
    finally:
        cleanup_children(process, server, drain_output)
        # The enclosing disposable harness removes the private marker directory,
        # secret, volume and container in its existing verified cleanup path.


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-flutter-postgres", action="store_true")
    parser.add_argument("--mobile-root", type=Path, required=True, help="Owned apps/mobile directory")
    parser.add_argument("--tools-root", type=Path, required=True, help="Owned project-only Flutter SDK/home/pub-cache directory")
    parser.add_argument("--test-file", type=Path, default=Path("test/native_backend_integration_test.dart"),
                        help="Reviewed owned local test/*_test.dart; never a remote URL or shell command")
    args = parser.parse_args()
    if not args.run_flutter_postgres:
        parser.error("Explicit --run-flutter-postgres is required")
    mobile_root, tools_root = args.mobile_root.resolve(strict=True), args.tools_root.resolve(strict=True)
    owned_test(mobile_root, args.test_file)
    def extra(connect, restart, temporary):
        return [unittest.FunctionTestCase(lambda: run_chain(connect, restart, temporary, mobile_root, tools_root, args.test_file),
                    description="real Flutter -> HTTP -> PostgreSQL with two durable restarts")]
    return run_postgres.main(extra_test_factory=extra, argv=["--run-disposable-postgres"])


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Dart-owned disposable identity fixture. PRIVATE anonymous stdin/stdout only.

No application/admin mailbox route, supplied DB, destination, key, or password.
Do not redirect protocol stdout to a terminal, persistent file, or build log.
"""
import contextlib
import os
from pathlib import Path
import signal
import socket
import sys
import threading
import unittest
from wsgiref.simple_server import WSGIRequestHandler, WSGIServer, make_server

from identity_fixture_protocol import ProtocolError, command_loop, require_anonymous_pipe, write_message

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))


class SilentOutput:
    def write(self, value):
        return len(value)
    def flush(self):
        pass


class QuietHandler(WSGIRequestHandler):
    def log_message(self, *args):
        pass
    def get_stderr(self):
        return SilentOutput()


class BoundedServer(WSGIServer):
    active_connection = None

    def get_request(self):
        connection, address = super().get_request()
        connection.settimeout(10)
        self.active_connection = connection
        if self.stopping.is_set():
            self.close_request(connection)
            raise OSError("Owned fixture stopping")
        return connection, address

    def close_request(self, request):
        try:
            super().close_request(request)
        finally:
            if self.active_connection is request:
                self.active_connection = None

    def interrupt_owned_request(self):
        connection = self.active_connection
        if connection is not None:
            try:
                connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass


def serve_private_fixture(stop, lifetime_seconds):
    from django.core.wsgi import get_wsgi_application
    from django.db import connections
    from wainek_identity.mailbox import OUTBOX
    server = make_server("127.0.0.1", 0, get_wsgi_application(), server_class=BoundedServer, handler_class=QuietHandler)
    server.timeout = .2
    worker_stop = threading.Event()
    server.stopping = worker_stop
    def work():
        try:
            while not worker_stop.is_set():
                server.handle_request()
        finally:
            # Django connections are thread-local: close in the owning thread.
            connections.close_all()
    worker = threading.Thread(target=work, name="wainek-private-identity-http", daemon=False)
    worker.start()
    try:
        write_message(1, {"type": "ready", "mode": "identity_fixture", "private_mailbox": True,
                          "base_url": f"http://127.0.0.1:{server.server_port}", "lifetime_seconds": lifetime_seconds})
        return command_loop(0, 1, stop, OUTBOX, lifetime_seconds=lifetime_seconds)
    finally:
        worker_stop.set()
        server.interrupt_owned_request()
        # Socket reads are bounded10s and SQL statements20s. Do not kill unrelated processes.
        worker.join(40)
        server.server_close()
        connections.close_all()
        OUTBOX.clear()
        if worker.is_alive():
            raise ProtocolError("http_shutdown_unverified")


def options(argv):
    if not argv or argv[0] != "--run-disposable-identity-fixture":
        raise ProtocolError("explicit_opt_in_required")
    lifetime = 180
    if len(argv) == 3 and argv[1] == "--lifetime-seconds":
        try:
            lifetime = int(argv[2])
        except ValueError:
            raise ProtocolError("invalid_options") from None
        if not 2 <= lifetime <= 300:
            raise ProtocolError("invalid_options")
    elif len(argv) != 1:
        raise ProtocolError("invalid_options")
    return lifetime


def main(argv=None):
    try:
        lifetime = options(sys.argv[1:] if argv is None else argv)
        require_anonymous_pipe(0)
        require_anonymous_pipe(1)
    except (ProtocolError, OSError):
        # A fixed diagnostic only. Never echo argv or rejected protocol content.
        sys.stderr.write("identity_fixture_preflight_rejected\n")
        return 2
    stop = threading.Event()
    previous = {s: signal.signal(s, lambda *_: stop.set()) for s in (signal.SIGTERM, signal.SIGINT)}
    reason = "fixture_failed"
    result = 1
    cleanup_verified = False
    try:
        with contextlib.redirect_stdout(SilentOutput()), contextlib.redirect_stderr(SilentOutput()):
            import run_postgres
            def extra(connect, restart, temporary):
                from wainek_identity.bootstrap import configure, ephemeral_keys
                configure(connect, keys=ephemeral_keys())
                class PrivateFixture(unittest.TestCase):
                    def runTest(self):
                        nonlocal reason
                        if not self._outcome.result.wasSuccessful():
                            self.fail("Legacy prerequisite checks failed")
                        if stop.is_set():
                            reason = "terminated"
                            return
                        from django.core.management import call_command
                        from django.db import connection, connections
                        try:
                            call_command("migrate", interactive=False, verbosity=0)
                            call_command("check", verbosity=0)
                            with connection.cursor() as cursor:
                                cursor.execute("TRUNCATE wainak_phase1_dev.accounts CASCADE")
                            connections.close_all()
                            reason = serve_private_fixture(stop, lifetime)
                        finally:
                            connections.close_all()
                return unittest.TestSuite([PrivateFixture()])
            result = run_postgres.main(extra_test_factory=extra, argv=["--run-disposable-postgres"])
            # Returning means its exact-label container/volume AND tempdir checks passed.
            cleanup_verified = True
    except BaseException:
        # No exception repr/traceback can reveal private mail, session, or DB settings.
        reason = "fixture_failed"
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)
    try:
        write_message(1, {"type": "closed", "cleanup_verified": cleanup_verified,
                          "checks_passed": result == 0, "reason": reason})
    except (ProtocolError, OSError):
        pass
    return 0 if cleanup_verified and result == 0 and reason == "shutdown" else 2


if __name__ == "__main__":
    raise SystemExit(main())

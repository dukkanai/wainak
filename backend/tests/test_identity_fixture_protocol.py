"""No Docker/framework/secret material needed for private-fixture control tests."""
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "integration"))
import identity_fixture_protocol as protocol
import serve_identity_fixture as fixture


class FixtureProtocolTests(unittest.TestCase):
    def command(self, **changes):
        value = {"id": 1, "op": "mail", "email": "fixture@example.invalid", "purpose": "verify", "after": 0}
        value.update(changes)
        return value

    def test_exact_commands_and_fixed_opt_in(self):
        self.assertEqual(protocol.parse_command(b'{"id":1,"op":"shutdown"}')["op"], "shutdown")
        self.assertEqual(protocol.parse_command(json.dumps(self.command()).encode())["purpose"], "verify")
        self.assertEqual(fixture.options(["--run-disposable-identity-fixture"]), 180)
        self.assertEqual(fixture.options(["--run-disposable-identity-fixture", "--lifetime-seconds", "2"]), 2)

    def test_rejects_general_destination_options_and_unbounded_lifetime(self):
        for argv in ([], ["--dsn", "not-accepted"], ["--run-disposable-identity-fixture", "--host", "0.0.0.0"],
                     ["--run-disposable-identity-fixture", "--lifetime-seconds", "301"]):
            with self.subTest(kind=len(argv)), self.assertRaises(protocol.ProtocolError):
                fixture.options(argv)

    def test_duplicate_keys_unknown_fields_invalid_json_and_size_rejected(self):
        for line in (b'{"id":1,"id":2,"op":"shutdown"}', b'{"id":true,"op":"shutdown"}',
                     b'{"id":1,"op":"shutdown","extra":1}', b'[]', b'NaN', b'{', b'\xff', b'x' * 4097):
            with self.subTest(size=len(line)), self.assertRaises(protocol.ProtocolError):
                protocol.parse_command(line)

    def test_email_purpose_cursor_restricted(self):
        for changes in ({"email": "fixture@example.com"}, {"email": "x@127.0.0.1"}, {"purpose": "delete"},
                        {"after": -1}, {"after": True}, {"op": "sql"}, {"id": 1000001}, {"email": []}):
            with self.subTest(fields=list(changes)), self.assertRaises(protocol.ProtocolError):
                protocol.parse_command(json.dumps(self.command(**changes)).encode())

    def test_latest_committed_event_after_cursor_and_purpose(self):
        outbox = [{"recipient": "fixture@example.invalid", "code": "fixture-old"},
                  {"recipient": "other@example.invalid", "code": "fixture-other"},
                  {"recipient": "fixture@example.invalid", "code": "fixture-new"}]
        result = protocol.mail_response(self.command(), outbox)
        self.assertTrue(result["value"] == "fixture-new")
        self.assertEqual(result["sequence"], 3)
        self.assertFalse(protocol.mail_response(self.command(after=3), outbox)["ok"])
        self.assertFalse(protocol.mail_response(self.command(purpose="reset"), outbox)["ok"])

    def test_reset_link_is_not_followed_and_external_destination_rejected(self):
        record = {"recipient": "fixture@example.invalid", "reset_url": "https://example.invalid/reset/fixture-opaque"}
        self.assertTrue(protocol.mail_response(self.command(purpose="reset"), [record])["value"] == "fixture-opaque")
        for value in ("https://external.invalid/reset/fixture", "https://example.invalid/reset/invalid value"):
            record["reset_url"] = value
            with self.assertRaises(protocol.ProtocolError):
                protocol.mail_response(self.command(purpose="reset"), [record])

    def test_anonymous_pipes_only_no_persistent_output_or_named_fifo(self):
        read_fd, write_fd = os.pipe()
        try:
            protocol.require_anonymous_pipe(read_fd)
            protocol.require_anonymous_pipe(write_fd)
        finally:
            os.close(read_fd); os.close(write_fd)
        with tempfile.TemporaryFile() as output:
            with self.assertRaises(protocol.ProtocolError):
                protocol.require_anonymous_pipe(output.fileno())
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "named"
            os.mkfifo(path)
            fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
            try:
                with self.assertRaises(protocol.ProtocolError):
                    protocol.require_anonymous_pipe(fd)
            finally:
                os.close(fd)

    def loop(self, payload=None, *, eof=False, stopped=False, lifetime=.02, idle=60):
        read_fd, send_fd = os.pipe()
        receive_fd, write_fd = os.pipe()
        stop = threading.Event()
        if stopped: stop.set()
        try:
            if payload is not None: os.write(send_fd, payload)
            if eof:
                os.close(send_fd); send_fd = None
            return protocol.command_loop(read_fd, write_fd, stop, [], lifetime_seconds=lifetime, idle_seconds=idle)
        finally:
            for fd in (read_fd, send_fd, receive_fd, write_fd):
                if fd is not None: os.close(fd)

    def test_shutdown_eof_term_idle_and_lifetime_are_distinct(self):
        self.assertEqual(self.loop(b'{"id":1,"op":"shutdown"}\n'), "shutdown")
        self.assertEqual(self.loop(eof=True), "eof")
        self.assertEqual(self.loop(stopped=True), "terminated")
        self.assertEqual(self.loop(), "lifetime_timeout")
        self.assertEqual(self.loop(lifetime=1, idle=.02), "idle_timeout")

    def test_buffer_and_command_budget_bounded(self):
        with self.assertRaises(protocol.ProtocolError):
            self.loop(b'x' * 4097)
        with mock.patch.object(protocol, "MAX_COMMANDS", 1):
            with self.assertRaises(protocol.ProtocolError):
                self.loop(json.dumps(self.command()).encode() + b'\n' + b'{"id":2,"op":"shutdown"}\n')

    def test_broken_output_and_stalled_reader_are_bounded(self):
        read_fd, write_fd = os.pipe()
        os.close(read_fd)
        try:
            with self.assertRaises(protocol.ProtocolError):
                protocol.write_message(write_fd, {"type": "test"})
        finally:
            os.close(write_fd)
        read_fd, write_fd = os.pipe()
        try:
            os.set_blocking(write_fd, False)
            while True:
                try: os.write(write_fd, b'x' * 4096)
                except BlockingIOError: break
            started = time.monotonic()
            with self.assertRaises(protocol.ProtocolError):
                protocol.write_message(write_fd, {"type": "test"}, timeout=.02)
            self.assertLess(time.monotonic() - started, 1)
        finally:
            os.close(read_fd); os.close(write_fd)

    def test_buffered_batch_rechecks_stop_and_deadline_before_each_command(self):
        for mode in ("stop", "deadline"):
            with self.subTest(mode=mode):
                read_fd, send_fd = os.pipe()
                receive_fd, write_fd = os.pipe()
                stop = threading.Event()
                clock = [0.0]
                calls = []
                def written(fd, value, timeout):
                    calls.append(timeout)
                    if mode == "stop": stop.set()
                    else: clock[0] = .6
                try:
                    line = json.dumps(self.command()).encode() + b'\n'
                    os.write(send_fd, line + line)
                    with mock.patch.object(protocol.time, "monotonic", lambda: clock[0]), mock.patch.object(protocol, "write_message", written):
                        reason = protocol.command_loop(read_fd, write_fd, stop, [], lifetime_seconds=.5)
                    self.assertEqual(reason, "terminated" if mode == "stop" else "lifetime_timeout")
                    self.assertEqual(len(calls), 1)
                    self.assertLessEqual(calls[0], .5)
                finally:
                    for fd in (read_fd, send_fd, receive_fd, write_fd): os.close(fd)

"""Bounded private anonymous-PIPE protocol; not an application API."""
import json
import os
import re
import selectors
import stat
import time

MAX_LINE = 4096
MAX_COMMANDS = 256


class ProtocolError(Exception):
    """Only fixed reason codes, never input content, may escape this module."""


def require_anonymous_pipe(fd):
    if not stat.S_ISFIFO(os.fstat(fd).st_mode):
        raise ProtocolError("anonymous_pipe_required")
    if not os.readlink(f"/proc/self/fd/{fd}").startswith("pipe:["):
        raise ProtocolError("anonymous_pipe_required")


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ProtocolError("invalid_command")
        result[key] = value
    return result


def parse_command(line):
    if len(line) > MAX_LINE:
        raise ProtocolError("command_too_large")
    try:
        value = json.loads(line, object_pairs_hook=_unique_object,
                           parse_constant=lambda _: (_ for _ in ()).throw(ProtocolError("invalid_command")))
    except (ValueError, TypeError, RecursionError, UnicodeError):
        raise ProtocolError("invalid_command") from None
    if not isinstance(value, dict) or type(value.get("id")) is not int or not 0 <= value["id"] <= 1_000_000:
        raise ProtocolError("invalid_command")
    if value.get("op") == "shutdown" and set(value) == {"id", "op"}:
        return value
    if value.get("op") != "mail" or set(value) != {"id", "op", "email", "purpose", "after"}:
        raise ProtocolError("invalid_command")
    email = value["email"]
    if not isinstance(email, str) or not re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,63}@example\.invalid", email):
        raise ProtocolError("synthetic_email_required")
    if value["purpose"] not in ("verify", "reset") or type(value["after"]) is not int or not 0 <= value["after"] <= 1_000_000:
        raise ProtocolError("invalid_command")
    return value


def mail_response(command, outbox):
    field = "code" if command["purpose"] == "verify" else "reset_url"
    # Snapshot only the record references. Mail is appended only after DB commit.
    for index, record in reversed(list(enumerate(outbox))):
        if index + 1 <= command["after"] or record.get("recipient") != command["email"]:
            continue
        value = record.get(field)
        if not value:
            continue
        if command["purpose"] == "reset":
            prefix = "https://example.invalid/reset/"
            if not isinstance(value, str) or not value.startswith(prefix):
                raise ProtocolError("invalid_mail_fixture")
            value = value[len(prefix):]
        if not isinstance(value, str) or not 1 <= len(value) <= 1024 or any(c.isspace() for c in value):
            raise ProtocolError("invalid_mail_fixture")
        return {"id": command["id"], "ok": True, "sequence": index + 1, "value": value}
    return {"id": command["id"], "ok": False, "error": "not_ready"}


def write_message(fd, value, timeout=2.0):
    data = json.dumps(value, separators=(",", ":"), ensure_ascii=True).encode() + b"\n"
    if len(data) > MAX_LINE:
        raise ProtocolError("response_too_large")
    os.set_blocking(fd, False)
    deadline = time.monotonic() + timeout
    with selectors.DefaultSelector() as selector:
        selector.register(fd, selectors.EVENT_WRITE)
        while data:
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not selector.select(remaining):
                raise ProtocolError("output_timeout")
            try:
                count = os.write(fd, data)
            except BlockingIOError:
                continue
            except (BrokenPipeError, OSError):
                raise ProtocolError("output_closed") from None
            data = data[count:]


def command_loop(read_fd, write_fd, stop, outbox, *, lifetime_seconds, idle_seconds=60):
    started = last_input = time.monotonic()
    buffer = b""
    count = 0
    def stopped_reason():
        now = time.monotonic()
        if stop.is_set():
            return "terminated"
        if now - started >= lifetime_seconds:
            return "lifetime_timeout"
        if now - last_input >= idle_seconds:
            return "idle_timeout"
        return None
    def output(value):
        now = time.monotonic()
        remaining = min(2.0, lifetime_seconds - (now - started), idle_seconds - (now - last_input))
        write_message(write_fd, value, timeout=max(0, remaining))
    with selectors.DefaultSelector() as selector:
        selector.register(read_fd, selectors.EVENT_READ)
        while True:
            now = time.monotonic()
            reason = stopped_reason()
            if reason:
                return reason
            if not selector.select(min(.2, lifetime_seconds - (now - started), idle_seconds - (now - last_input))):
                continue
            chunk = os.read(read_fd, MAX_LINE + 1)
            if not chunk:
                return "eof"
            last_input = time.monotonic()
            buffer += chunk
            if len(buffer) > MAX_LINE and b"\n" not in buffer[:MAX_LINE + 1]:
                raise ProtocolError("command_too_large")
            while b"\n" in buffer:
                reason = stopped_reason()
                if reason:
                    return reason
                line, buffer = buffer.split(b"\n", 1)
                count += 1
                if count > MAX_COMMANDS:
                    raise ProtocolError("command_limit")
                command = parse_command(line)
                if command["op"] == "shutdown":
                    output({"id": command["id"], "ok": True, "stopping": True})
                    return "shutdown"
                output(mail_response(command, outbox))
            if len(buffer) > MAX_LINE:
                raise ProtocolError("command_too_large")

#!/usr/bin/env python3
"""Private Python client probes. Prints only fixed scenario results, never IPC/mail."""
import json
import os
from pathlib import Path
import secrets
import selectors
import signal
import socket
import subprocess
import sys
import time
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

HERE = Path(__file__).resolve().parent


def require(value, message):
    if not value:
        raise RuntimeError(message)  # All caller messages are fixed, not response data.


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None


class PrivateClient:
    def __init__(self, *, lifetime=180):
        self.buffer = b""
        self.process = subprocess.Popen([sys.executable, str(HERE / "serve_identity_fixture.py"),
            "--run-disposable-identity-fixture", "--lifetime-seconds", str(lifetime)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            env={"PATH": "/usr/bin:/bin", "HOME": os.environ.get("HOME", "/tmp"), "LANG": "C.UTF-8",
                 "PYTHONDONTWRITEBYTECODE": "1", "PYTHONUNBUFFERED": "1"})
        self.opener = build_opener(ProxyHandler({}), NoRedirect())

    def receive(self, timeout=120):
        deadline = time.monotonic() + timeout
        with selectors.DefaultSelector() as selector:
            selector.register(self.process.stdout, selectors.EVENT_READ)
            while b"\n" not in self.buffer:
                remaining = deadline - time.monotonic()
                require(remaining > 0 and bool(selector.select(max(0, remaining))), "Private fixture response timed out")
                chunk = os.read(self.process.stdout.fileno(), 4096)
                require(bool(chunk), "Private fixture ended before its terminal acknowledgement")
                self.buffer += chunk
                require(len(self.buffer) <= 8192, "Private fixture response exceeded its bound")
        line, self.buffer = self.buffer.split(b"\n", 1)
        try:
            return json.loads(line)
        except (ValueError, UnicodeError):
            raise RuntimeError("Private fixture returned invalid bounded JSON") from None

    def ready(self):
        message = self.receive()
        require(message.get("type") == "ready" and message.get("private_mailbox") is True, "Fixture did not become ready")
        parts = urlsplit(message.get("base_url", ""))
        require(parts.scheme == "http" and parts.hostname == "127.0.0.1" and parts.port is not None
                and not parts.username and not parts.password and not parts.path and not parts.query and not parts.fragment,
                "Fixture destination was not exact local loopback")
        self.base_url = message["base_url"]
        return parts.port

    def send(self, message):
        self.process.stdin.write(json.dumps(message, separators=(",", ":")).encode() + b"\n")
        self.process.stdin.flush()

    def call(self, method, path, data=None, token=None):
        require(path.startswith("/") and not path.startswith("//"), "Only local relative API paths are accepted")
        headers = {"Content-Type": "application/json"}
        if token: headers["X-Session-Token"] = token
        request = Request(self.base_url + path, json.dumps(data or {}).encode(), headers, method=method)
        try:
            response = self.opener.open(request, timeout=35)
        except HTTPError as error:
            response = error
        with response:
            status = response.status
            content = response.read(16385)
        require(len(content) <= 16384, "HTTP fixture response exceeded bound")
        try:
            return status, json.loads(content)
        except ValueError:
            raise RuntimeError("Expected JSON without echoing HTTP content") from None

    def finish(self, expected_reason, expected_code):
        message = self.receive()
        require(message.get("type") == "closed" and message.get("cleanup_verified") is True
                and message.get("checks_passed") is True and message.get("reason") == expected_reason,
                "Fixture cleanup/terminal status was not verified")
        require(self.process.wait(timeout=10) == expected_code, "Unexpected fixture exit status")
        # Private stdout was consumed in RAM; no diagnostics may contain credentials.
        require(not self.buffer and not self.process.stdout.read(), "Unexpected trailing protocol output")
        require(not self.process.stderr.read(), "Unexpected fixture diagnostics (not displayed)")

    def close(self):
        try:
            if self.process.stdin and not self.process.stdin.closed: self.process.stdin.close()
            if self.process.poll() is None:
                try: self.process.wait(timeout=120)  # EOF gives the owned runner time to verify cleanup.
                except subprocess.TimeoutExpired:
                    self.process.terminate()
                    try: self.process.wait(timeout=120)
                    except subprocess.TimeoutExpired:
                        self.process.kill(); self.process.wait(timeout=10)
                        raise RuntimeError("Owned child required force termination; cleanup is NOT verified") from None
        finally:
            for stream in (self.process.stdin, self.process.stdout, self.process.stderr):
                if stream and not stream.closed: stream.close()


def normal_journey(client):
    auth = "/_allauth/app/v1/"
    email = "pipe-" + secrets.token_hex(5) + "@example.invalid"
    password = secrets.token_urlsafe(24) + "!7aZ"
    status, body = client.call("POST", auth + "auth/signup", {"email": email, "password": password,
        "birth_date": "1995-01-01", "is_muslim": True, "terms_version": "dev-2026-10-24", "privacy_version": "dev-2026-10-24"})
    require(status == 401 and body.get("meta", {}).get("is_authenticated") is False, "Signup must remain pending")
    token = body.get("meta", {}).get("session_token")
    require(isinstance(token, str), "Pending session was not supplied")
    client.send({"id": 1, "op": "mail", "email": email, "purpose": "verify", "after": 0})
    message = client.receive()
    require(message.get("ok") is True and isinstance(message.get("value"), str), "Fake verification mail was not committed")
    status, body = client.call("POST", auth + "auth/email/verify", {"key": message["value"]}, token)
    require(status == 200 and body.get("meta", {}).get("is_authenticated") is True, "Real framework verification failed")
    token = body.get("meta", {}).get("session_token", token)
    client.send({"id": 2, "op": "mail", "email": email, "purpose": "verify", "after": message["sequence"]})
    require(client.receive().get("ok") is False, "Mail cursor replayed an old event")
    status, _ = client.call("PUT", "/v1/me/profile", {"gender": "male", "country": "SA", "marital_status": "single",
        "declared_wives": 0, "marriage_goal": "build_family", "discoverable": True}, token)
    require(status == 200, "Authenticated profile bridge failed")
    status, body = client.call("POST", auth + "auth/login", {"email": email, "password": password})
    require(status == 200, "Second independent login failed")
    second = body.get("meta", {}).get("session_token")
    status, _ = client.call("POST", "/identity/v1/logout-all", {}, token)
    require(status == 200, "Global revocation failed")
    status, _ = client.call("GET", "/identity/v1/me", token=second)
    require(status == 401, "Other session survived revocation")
    status, body = client.call("POST", auth + "auth/login", {"email": email, "password": password})
    require(status == 200, "Login after revocation failed")
    token = body.get("meta", {}).get("session_token")
    status, _ = client.call("POST", "/identity/v1/reauthenticate", {"password": password}, token)
    require(status == 200, "Reauthentication failed")
    status, body = client.call("DELETE", "/identity/v1/me", {"confirmation": "DELETE"}, token)
    require(status == 200 and body.get("identity_erased") is True, "Verified account was not erased")
    status, _ = client.call("GET", "/identity/v1/me", token=token)
    require(status == 401, "Deleted session remained usable")
    client.send({"id": 3, "op": "shutdown"})
    require(client.receive().get("stopping") is True, "Shutdown was not acknowledged")
    client.finish("shutdown", 0)


def artifact_inventory():
    label = "com.wainak.disposable-postgres-test"
    def listed(arguments):
        result = subprocess.run(arguments, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
        require(result.returncode == 0, "Cannot verify owned fixture resource inventory")
        return tuple(sorted(result.stdout.decode("ascii").split()))
    directories = tuple(sorted(entry.name for entry in os.scandir("/tmp")
        if entry.name.startswith("wainak-postgres-test-") and entry.is_dir(follow_symlinks=False)
        and entry.stat(follow_symlinks=False).st_uid == os.getuid()))
    return (listed(["docker", "ps", "-aq", "--filter", "label=" + label]),
            listed(["docker", "volume", "ls", "-q", "--filter", "label=" + label]), directories)


def main():
    if sys.argv[1:] != ["--run-disposable-fixture-probes"]:
        print("Explicit disposable fixture probe opt-in required", file=sys.stderr)
        return 2
    baseline = artifact_inventory()
    for scenario in ("normal", "eof", "term_slow_http", "timeout", "broken_pipe"):
        client = PrivateClient(lifetime=2 if scenario == "timeout" else 180)
        try:
            port = client.ready()
            if scenario == "normal":
                normal_journey(client)
            elif scenario == "eof":
                client.process.stdin.close()
                client.finish("eof", 2)
            elif scenario == "term_slow_http":
                with socket.create_connection(("127.0.0.1", port), timeout=3) as connection:
                    connection.sendall(b"POST /_allauth/app/v1/auth/login HTTP/1.1\r\nHost: localhost\r\n")
                    time.sleep(.1)
                    client.process.send_signal(signal.SIGTERM)
                    client.finish("terminated", 2)
            elif scenario == "timeout":
                client.finish("lifetime_timeout", 2)
            else:
                client.process.stdout.close()
                client.send({"id": 1, "op": "mail", "email": "absent@example.invalid", "purpose": "verify", "after": 0})
                require(client.process.wait(timeout=120) == 2, "Broken PIPE did not terminate owned fixture")
                require(not client.process.stderr.read(), "Unexpected broken-PIPE diagnostics (not displayed)")
                # Closed acknowledgement cannot be read after deliberate pipe loss.
                # The independent metadata inventory below is mandatory for this scenario.
        finally:
            client.close()
            require(artifact_inventory() == baseline, "Fixture resource inventory did not return to its original state")
        print("private_identity_fixture_probe=" + scenario + " PASS cleanup_verified", flush=True)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        print("private_identity_fixture_probe FAILED (private details withheld)", file=sys.stderr)
        raise SystemExit(1) from None

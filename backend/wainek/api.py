"""Bounded JSON adapter. DevelopmentApplication is deliberately opt-in only."""

import json
import re
from http import HTTPStatus

from .domain import DevelopmentService, DomainError, fail

MAX_BODY_BYTES = 16_384


def relationship_cursor(method, path, query):
    """Only an exact opaque cursor on this read route may appear in a query.

    Do not decode or normalize: duplicate keys, credentials, encoded delimiters,
    alternative parameter spellings and query parameters on other routes fail.
    """
    if not query:
        return None
    if (method == "GET" and path == "/v1/relationships" and isinstance(query, str)
            and re.fullmatch(r"cursor=rel_[0-9a-f]{32}", query)):
        return query[len("cursor="):]
    fail(400, "query_not_supported", "Only the relationship continuation cursor is supported.")


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            fail(400, "invalid_json", "Duplicate JSON keys are not accepted.")
        result[key] = value
    return result


class DevelopmentApplication:
    def __init__(self, *, enable_development=False, service=None):
        if enable_development is not True:
            raise RuntimeError("Development mode must be explicitly enabled; there is no production adapter.")
        self.service = service or DevelopmentService()

    def _body(self, environ):
        if environ.get("CONTENT_TYPE", "").split(";", 1)[0].strip().lower() != "application/json":
            fail(415, "json_required", "Use application/json.")
        length = environ.get("CONTENT_LENGTH", "")
        if not isinstance(length, str) or not length.isascii() or not length.isdigit():
            fail(400, "invalid_body_length", "A valid Content-Length is required.")
        if len(length) > 8 or int(length) > MAX_BODY_BYTES:
            fail(413, "body_too_large", "The request body exceeds the development limit.")
        raw = environ["wsgi.input"].read(int(length))
        if len(raw) != int(length):
            fail(400, "invalid_json", "The JSON body is incomplete.")
        try:
            data = json.loads(raw.decode("utf-8"), object_pairs_hook=unique_object,
                              parse_constant=lambda _: fail(400, "invalid_json", "Finite JSON values are required."))
        except (ValueError, UnicodeError, RecursionError):
            fail(400, "invalid_json", "The JSON body could not be read.")
        if not isinstance(data, dict):
            fail(400, "invalid_json", "A JSON object is required.")
        return data

    def dispatch(self, environ):
        method = environ.get("REQUEST_METHOD", "GET")
        path = environ.get("PATH_INFO", "")
        host = environ.get("HTTP_HOST", "localhost").lower()
        if not re.fullmatch(r"(?:localhost|127\.0\.0\.1)(?::[0-9]{1,5})?", host):
            fail(403, "local_only", "Only the local development host is allowed.")
        # No browser cross-origin use, including write-only requests.
        if environ.get("HTTP_ORIGIN"):
            fail(403, "origin_not_allowed", "Browser cross-origin access is disabled.")
        cursor = relationship_cursor(method, path, environ.get("QUERY_STRING", ""))
        if method == "GET" and path == "/health":
            return 200, {"status": "ok", "mode": "synthetic_development_only",
                         "durable_storage": self.service.repository.durable}
        data = self._body(environ) if method in ("POST", "PUT", "DELETE") else None
        if method == "POST" and path == "/v1/dev/accounts":
            return 201, self.service.register(data)
        authorization = environ.get("HTTP_AUTHORIZATION", "")
        if not authorization.startswith("Bearer ") or authorization.count(" ") != 1:
            fail(401, "unauthenticated", "A current development session is required.")
        actor = self.service.authenticate(authorization[7:])
        routes = {
            ("GET", "/v1/me"): lambda: self.service.me(actor),
            ("DELETE", "/v1/me"): lambda: self.service.delete_account(actor, data),
            ("POST", "/v1/dev/verify-email"): lambda: self.service.verify_email(actor, data),
            ("PUT", "/v1/me/profile"): lambda: self.service.update_profile(actor, data),
            ("PUT", "/v1/me/preferences"): lambda: self.service.update_preferences(actor, data),
            ("GET", "/v1/me/assessment"): lambda: self.service.assessment(actor),
            ("POST", "/v1/me/assessment/answers"): lambda: self.service.answer(actor, data),
            ("GET", "/v1/candidates"): lambda: self.service.candidates(actor),
            ("GET", "/v1/relationships"): lambda: self.service.list_relationships(actor, cursor),
            ("POST", "/v1/relationships"): lambda: self.service.request(actor, data, environ.get("HTTP_IDEMPOTENCY_KEY")),
            ("POST", "/v1/blocks"): lambda: self.service.block(actor, data),
            ("POST", "/v1/reports"): lambda: self.service.report(actor, data),
        }
        route = routes.get((method, path))
        if route:
            return (201 if method == "POST" and path in ("/v1/relationships", "/v1/reports") else 200), route()
        match = re.fullmatch(r"/v1/candidates/(usr_[0-9a-f]{32})", path)
        if match and method == "GET":
            return 200, self.service.candidate(actor, match[1])
        match = re.fullmatch(r"/v1/relationships/(rel_[0-9a-f]{32})(?:/(respond|cancel|end|cards|exclusive/request|exclusive/respond))?", path)
        if match:
            identifier, action = match.groups()
            if method == "GET" and action is None:
                return 200, self.service.relationship(actor, identifier)
            if method == "GET" and action == "cards":
                return 200, self.service.content(actor, identifier)
            actions = {"respond": self.service.respond, "cancel": self.service.cancel, "end": self.service.end,
                       "exclusive/request": self.service.request_exclusive,
                       "exclusive/respond": self.service.respond_exclusive}
            if method == "POST" and action in actions:
                return 200, actions[action](actor, identifier, data)
        match = re.fullmatch(r"/v1/dev/relationships/(rel_[0-9a-f]{32})/activate", path)
        if match and method == "POST":
            return 200, self.service.activate(actor, match[1], data)
        fail(404, "not_found", "The resource is not available.")

    def __call__(self, environ, start_response):
        try:
            status, value = self.dispatch(environ)
        except DomainError as error:
            status, value = error.status, {"error": {"code": error.code, "message": error.message}}
        except Exception:
            # Do not echo request bodies, tokens, identifiers, or exception details.
            status, value = 500, {"error": {"code": "internal_error", "message": "An internal error occurred."}}
        payload = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        headers = [("Content-Type", "application/json; charset=utf-8"), ("Content-Length", str(len(payload))),
                   ("Cache-Control", "no-store"), ("X-Content-Type-Options", "nosniff"),
                   ("Content-Security-Policy", "default-src 'none'"), ("Referrer-Policy", "no-referrer")]
        if status == 401:
            headers.append(("WWW-Authenticate", 'Bearer realm="wainek-development"'))
        start_response(f"{status} {HTTPStatus(status).phrase}", headers)
        return [payload]

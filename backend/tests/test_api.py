import io
import json
import unittest
from datetime import date

from wainak.api import DevelopmentApplication, MAX_BODY_BYTES
from wainak.domain import DevelopmentService, POLICY_VERSION


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.service = DevelopmentService(today=lambda: date(2026, 10, 24))
        self.app = DevelopmentApplication(enable_development=True, service=self.service)

    def call(self, method, path, data=None, token=None, raw=None, **headers):
        encoded = raw if raw is not None else json.dumps(data if data is not None else {}).encode()
        environ = {"REQUEST_METHOD": method, "PATH_INFO": path, "HTTP_HOST": "localhost:8089",
                   "CONTENT_TYPE": "application/json", "CONTENT_LENGTH": str(len(encoded)),
                   "wsgi.input": io.BytesIO(encoded)}
        if token:
            environ["HTTP_AUTHORIZATION"] = "Bearer " + token
        environ.update(headers)
        result = {}
        def start_response(status, response_headers):
            result.update(status=int(status.split()[0]), headers=dict(response_headers))
        value = json.loads(b"".join(self.app(environ, start_response)))
        return result["status"], value, result["headers"]

    def account(self, name="test"):
        status, value, _ = self.call("POST", "/v1/dev/accounts", {"email": name + "@example.invalid", "birth_date": "1996-01-01",
                                                                "is_muslim": True, "terms_version": POLICY_VERSION, "privacy_version": POLICY_VERSION})
        self.assertEqual(status, 201)
        return value["access_token"], value["account"]["id"]

    def test_production_default_refused(self):
        with self.assertRaises(RuntimeError):
            DevelopmentApplication()

    def test_health_explicitly_synthetic_and_not_durable(self):
        status, value, headers = self.call("GET", "/health")
        self.assertEqual(status, 200)
        self.assertEqual(value["mode"], "synthetic_development_only")
        self.assertFalse(value["durable_storage"])
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertEqual(headers["X-Content-Type-Options"], "nosniff")

    def test_authentication_required_and_actor_injection_rejected(self):
        self.assertEqual(self.call("GET", "/v1/me")[0], 401)
        token, identifier = self.account()
        self.assertEqual(self.call("GET", "/v1/me", token=token)[1]["id"], identifier)
        status, _, _ = self.call("POST", "/v1/dev/verify-email", {"simulate_verified": True, "actor_id": "other"}, token)
        self.assertEqual(status, 400)

    def test_untrusted_host_and_cross_origin_refused(self):
        for headers in ({"HTTP_HOST": "evil.example"}, {"HTTP_HOST": "localhost.evil.example"},
                        {"HTTP_ORIGIN": "https://evil.example"}, {"HTTP_ORIGIN": "null"}):
            with self.subTest(headers=headers):
                self.assertEqual(self.call("GET", "/health", **headers)[0], 403)

    def test_duplicate_keys_nonfinite_values_invalid_utf8_and_depth_refused(self):
        for raw in (b'{"x":1,"x":2}', b'{"x":NaN}', b'{"x":Infinity}', b'\xff', b'[]', b'null', b'{', b'[' * 1200):
            with self.subTest(raw=raw[:30]):
                self.assertEqual(self.call("POST", "/v1/dev/accounts", raw=raw)[0], 400)

    def test_content_type_body_length_and_oversize_refused(self):
        self.assertEqual(self.call("POST", "/v1/dev/accounts", CONTENT_TYPE="text/plain")[0], 415)
        for length in ("", "-1", "abc", "²"):
            self.assertEqual(self.call("POST", "/v1/dev/accounts", CONTENT_LENGTH=length)[0], 400)
        self.assertEqual(self.call("POST", "/v1/dev/accounts", CONTENT_LENGTH=str(MAX_BODY_BYTES + 1))[0], 413)
        self.assertEqual(self.call("POST", "/v1/dev/accounts", CONTENT_LENGTH="9")[0], 400)

    def test_unimplemented_upload_chat_and_identity_routes_fail_closed(self):
        token, _ = self.account()
        for path in ("/v1/messages", "/v1/reports/evidence", "/v1/photos", "/v1/disclosures", "/v1/payments"):
            with self.subTest(path=path):
                self.assertEqual(self.call("POST", path, {"text": "never store this"}, token)[0], 404)
        self.assertEqual(self.service.reports, {})

    def test_query_filters_refused_including_hidden_health(self):
        token, _ = self.account()
        self.assertEqual(self.call("GET", "/v1/candidates", token=token, QUERY_STRING="health=diabetes")[0], 400)

    def test_unknown_fields_never_reflected_in_error_or_saved(self):
        token, _ = self.account()
        marker = "PRIVATE-CONTENT-NOT-FOR-LOGS"
        status, result, _ = self.call("POST", "/v1/reports", {"conversation": marker}, token)
        self.assertEqual(status, 400)
        self.assertNotIn(marker, json.dumps(result))
        self.assertNotIn(marker, json.dumps(self.service.reports))

    def test_synthetic_account_lifecycle_and_revocation_via_api(self):
        token, identifier = self.account()
        status, value, _ = self.call("POST", "/v1/dev/verify-email", {"simulate_verified": True}, token)
        self.assertEqual(status, 200)
        self.assertTrue(value["dev_email_verified"])
        status, value, _ = self.call("DELETE", "/v1/me", {"confirmation": "DELETE"}, token)
        self.assertEqual(status, 200)
        self.assertTrue(value["deleted"])
        self.assertEqual(self.call("GET", "/v1/me", token=token)[0], 401)

    def test_internal_exception_response_contains_no_exception_or_request_details(self):
        token, _ = self.account()
        def broken(_):
            raise RuntimeError("sensitive-internal-information")
        self.service.me = broken
        status, value, _ = self.call("GET", "/v1/me", token=token)
        self.assertEqual(status, 500)
        self.assertNotIn("sensitive", json.dumps(value))


if __name__ == "__main__":
    unittest.main()

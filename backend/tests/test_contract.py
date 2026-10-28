"""Cross-layer examples validate the supported JSON Schema subset, not OAS certification."""

import importlib.util
import json
import re
import unittest
from datetime import date, datetime
from pathlib import Path

import test_api

ROOT = Path(__file__).resolve().parents[2]
CONTRACT = json.loads((ROOT / "contracts/phase1.openapi.json").read_text())


def validate(value, schema):
    if "$ref" in schema:
        return validate(value, CONTRACT["components"]["schemas"][schema["$ref"].split("/")[-1]])
    if "anyOf" in schema:
        for candidate in schema["anyOf"]:
            try:
                validate(value, candidate)
                return
            except (AssertionError, ValueError, TypeError):
                pass
        raise AssertionError("Value does not match any permitted schema")
    kind = schema.get("type")
    types = {"object": dict, "array": list, "string": str, "integer": int, "boolean": bool, "null": type(None)}
    assert kind in types and type(value) is types[kind], f"Expected {kind}, got {type(value).__name__}"
    if "enum" in schema:
        assert value in schema["enum"]
    if "const" in schema:
        assert value == schema["const"]
    if kind == "object":
        assert set(schema.get("required", [])) <= value.keys()
        properties = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            assert not set(value) - properties.keys()
        for key, item in value.items():
            validate(item, properties[key])
    if kind == "array":
        assert schema.get("minItems", 0) <= len(value) <= schema.get("maxItems", 1_000_000)
        if schema.get("uniqueItems"):
            assert len({json.dumps(item, sort_keys=True) for item in value}) == len(value)
        for item in value:
            validate(item, schema["items"])
    if kind == "integer":
        assert schema.get("minimum", -1_000_000) <= value <= schema.get("maximum", 1_000_000)
    if kind == "string":
        assert schema.get("minLength", 0) <= len(value) <= schema.get("maxLength", 1_000_000)
        if "pattern" in schema:
            assert re.fullmatch(schema["pattern"], value)
        if schema.get("format") == "date":
            date.fromisoformat(value)
        if schema.get("format") == "date-time":
            datetime.fromisoformat(value)


class ContractTests(unittest.TestCase):
    def setUp(self):
        self.client = test_api.ApiTests()
        self.client.setUp()
        self.covered = set()

    def call(self, method, path, data=None, token=None, expected=200, **headers):
        template = next((key for key in CONTRACT["paths"] if re.fullmatch(re.sub(r"\{[^}]+\}", "[^/]+", key), path)), None)
        self.assertIsNotNone(template, path)
        definition = CONTRACT["paths"][template][method.lower()]
        if data is not None:
            validate(data, definition["requestBody"]["content"]["application/json"]["schema"])
        status, response, _ = self.client.call(method, path, data, token, **headers)
        self.assertEqual(status, expected, (method, path, response))
        response_schema = definition["responses"].get(str(status), definition["responses"]["default"])
        validate(response, response_schema["content"]["application/json"]["schema"])
        self.covered.add((method.lower(), template))
        return response

    def register(self, name, gender):
        result = self.call("POST", "/v1/dev/accounts", {"email": f"{name}@example.invalid", "birth_date": "1996-01-01",
                           "is_muslim": True, "terms_version": "dev-2026-10-24", "privacy_version": "dev-2026-10-24"}, expected=201)
        token = result["access_token"]
        self.call("POST", "/v1/dev/verify-email", {"simulate_verified": True}, token)
        self.call("PUT", "/v1/me/profile", {"gender": gender, "country": "SA", "marital_status": "single",
                  "declared_wives": 0, "marriage_goal": "build_family", "discoverable": True}, token)
        self.call("PUT", "/v1/me/preferences", {"min_age": 18, "max_age": 80, "countries": [], "marital_statuses": ["single", "married"]}, token)
        return token, result["account"]["id"]

    def test_every_documented_operation_and_response_through_json_adapter(self):
        self.call("GET", "/health")
        a, aid = self.register("alpha", "male")
        b, bid = self.register("beta", "female")
        self.call("GET", "/v1/me", token=a)
        self.call("GET", "/v1/me/assessment", token=a)
        for question, answer in (("family_plan", "children"), ("parenting", "shared_planning"), ("communication", "listen_first")):
            self.call("POST", "/v1/me/assessment/answers", {"question_id": question, "option_id": answer}, a)
        result = self.call("GET", "/v1/candidates", token=a)
        self.assertEqual([c["id"] for c in result["items"]], [bid])
        self.call("GET", f"/v1/candidates/{bid}", token=a)
        rel = self.call("POST", "/v1/relationships", {"candidate_id": bid}, a, expected=201, HTTP_IDEMPOTENCY_KEY="journey-001")["id"]
        path = f"/v1/relationships/{rel}"
        self.call("GET", "/v1/relationships", token=b)
        self.call("GET", path, token=b)
        self.call("POST", path + "/respond", {"decision": "accept"}, b)
        self.call("POST", f"/v1/dev/relationships/{rel}/activate", {"simulate_entitlement": True}, a)
        self.call("GET", path + "/cards", token=a)
        self.call("POST", path + "/exclusive/request", {"confirm": True}, a)
        self.call("POST", path + "/exclusive/respond", {"decision": "accept"}, b)
        self.call("POST", path + "/end", {"confirm": True}, b)
        self.call("POST", "/v1/blocks", {"target_id": aid}, b)
        self.call("POST", "/v1/reports", {"target_id": aid, "category": "harassment", "relationship_id": rel}, b, expected=201)
        c, cid = self.register("gamma", "female")
        pending = self.call("POST", "/v1/relationships", {"candidate_id": cid}, a, expected=201, HTTP_IDEMPOTENCY_KEY="journey-002")["id"]
        self.call("POST", f"/v1/relationships/{pending}/cancel", {}, a)
        self.call("DELETE", "/v1/me", {"confirmation": "DELETE"}, a)
        self.call("GET", "/v1/me", token=a, expected=401)
        expected = {(method, path) for path, operations in CONTRACT["paths"].items() for method in operations}
        self.assertEqual(self.covered, expected)

    def test_structural_references_unique_operations_and_explicit_development_security(self):
        self.assertEqual(CONTRACT["openapi"], "3.1.0")
        self.assertIn("NOT PRODUCTION", CONTRACT["info"]["description"])
        operations = [operation for path in CONTRACT["paths"].values() for operation in path.values()]
        self.assertEqual(len({operation["operationId"] for operation in operations}), len(operations))
        def walk(value):
            if isinstance(value, dict):
                if "$ref" in value:
                    self.assertIn(value["$ref"].split("/")[-1], CONTRACT["components"]["schemas"])
                for item in value.values():
                    walk(item)
            elif isinstance(value, list):
                for item in value:
                    walk(item)
        walk(CONTRACT)

    def test_generated_artifact_matches_builder(self):
        spec = importlib.util.spec_from_file_location("contract_builder", ROOT / "contracts/build_contract.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.assertEqual(CONTRACT, module.build())


if __name__ == "__main__":
    unittest.main()

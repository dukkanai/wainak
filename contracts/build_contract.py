"""Build the language-neutral phase-one OpenAPI contract without dependencies."""

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).parent


def obj(properties, optional=()):
    return {"type": "object", "additionalProperties": False, "properties": properties,
            "required": [key for key in properties if key not in optional]}


def ref(name):
    return {"$ref": f"#/components/schemas/{name}"}


def nullable(schema):
    return {"anyOf": [schema, {"type": "null"}]}


def array(schema, **constraints):
    return {"type": "array", "items": schema, **constraints}


def enum(*values):
    return {"type": "string", "enum": list(values)}


def build():
    string, boolean = {"type": "string"}, {"type": "boolean"}
    yes, no = {"type": "boolean", "const": True}, {"type": "boolean", "const": False}
    uid = {"type": "string", "pattern": "^usr_[0-9a-f]{32}$"}
    rid = {"type": "string", "pattern": "^rel_[0-9a-f]{32}$"}
    mode = enum("synthetic_development_only")
    age = {"type": "integer", "minimum": 18, "maximum": 120}
    country = {"type": "string", "pattern": "^[A-Z]{2}$"}
    marital = enum("single", "married", "divorced", "widowed")
    schemas = {
        "Error": obj({"error": obj({"code": string, "message": string})}),
        "Register": obj({"email": {"type": "string", "pattern": "^[a-z0-9._-]{1,64}@example\\.invalid$", "maxLength": 100},
                         "birth_date": {"type": "string", "format": "date"}, "is_muslim": yes,
                         "terms_version": enum("dev-2026-10-24"), "privacy_version": enum("dev-2026-10-24")}),
        "Profile": obj({"gender": enum("male", "female"), "country": country, "marital_status": marital,
                        "declared_wives": {"type": "integer", "minimum": 0, "maximum": 4},
                        "marriage_goal": enum("build_family", "companionship"), "discoverable": boolean}),
        "Preferences": obj({"min_age": age, "max_age": age, "countries": array(country, maxItems=20, uniqueItems=True),
                            "marital_statuses": array(marital, minItems=1, maxItems=4, uniqueItems=True)}),
        "Account": obj({"id": uid, "alias": string, "email": string, "age": age, "dev_email_verified": boolean,
                        "consents": obj({"terms_version": string, "privacy_version": string, "accepted_at": {"type": "string", "format": "date-time"}}),
                        "profile": nullable(ref("Profile")), "preferences": nullable(ref("Preferences")),
                        "eligible_for_discovery": boolean, "mode": mode}),
        "Registration": obj({"account": ref("Account"), "access_token": string, "token_type": enum("Bearer"), "mode": mode}),
        "Candidate": obj({"id": uid, "alias": string, "age": age, "country": country, "marital_status": marital,
                          "marriage_goal": enum("build_family", "companionship"),
                          "rating": obj({"state": enum("insufficient_data")}), "synthetic": yes}),
        "Candidates": obj({"items": array(ref("Candidate"), maxItems=20), "mode": mode}),
        "Question": obj({"id": enum("family_plan", "parenting", "life_priorities", "communication"),
                         "prompt_ar": string, "options": array(string)}),
        "Assessment": obj({"answers": {"type": "object", "additionalProperties": False, "properties": {
                            "family_plan": enum("children", "discuss_together", "prefer_not_to_say"),
                            "parenting": enum("shared_planning", "discuss_roles", "not_applicable"),
                            "life_priorities": enum("home", "work", "family", "prefer_not_to_say"),
                            "communication": enum("quiet_time", "listen_first", "scheduled_talk")}},
                           "next_question": nullable(ref("Question")), "answered_count": {"type": "integer", "minimum": 0, "maximum": 3},
                           "complete": boolean, "disclaimer": string}),
        "Answer": obj({"question_id": enum("family_plan", "parenting", "life_priorities", "communication"), "option_id": string}),
        "Relationship": obj({"id": rid, "initiator_id": uid, "recipient_id": uid,
                             "status": enum("requested", "accepted_pending_activation", "active_cards", "exclusive_cards", "frozen", "declined", "cancelled", "ended", "blocked"),
                             "peer": nullable(ref("Candidate")), "exclusive_requested_by": nullable(uid),
                             "permissions": obj({"can_send_cards": boolean, "can_send_text": no, "can_send_media": no, "can_disclose_identity": no}),
                             "activation_mode": enum("development_simulation_only")}),
        "Relationships": obj({"items": array(ref("Relationship"))}),
        "RelationshipRequest": obj({"candidate_id": uid}),
        "Decision": obj({"decision": enum("accept", "decline")}),
        "Confirm": obj({"confirm": yes}),
        "Empty": obj({}),
        "VerifySimulation": obj({"simulate_verified": yes}),
        "ActivationSimulation": obj({"simulate_entitlement": yes}),
        "Block": obj({"target_id": uid}),
        "Blocked": obj({"blocked": yes}),
        "Report": obj({"target_id": uid, "category": enum("harassment", "threat", "impersonation", "child_safety", "other_safety"),
                       "relationship_id": rid}, optional=("relationship_id",)),
        "ReportReceipt": obj({"id": {"type": "string", "pattern": "^rpt_[0-9a-f]{32}$"},
                              "status": enum("recorded_development_only"), "evidence_uploaded": no, "notice": string}),
        "Delete": obj({"confirmation": enum("DELETE")}),
        "Deleted": obj({"deleted": yes, "mode": mode, "notice": string}),
        "Cards": obj({"items": array(obj({"id": string, "title_ar": string, "prompt_ar": string, "options": array(string), "free": yes})),
                      "answers_transport": enum("not_implemented"), "server_stores_dialogue_answers": no}),
        "Health": obj({"status": enum("ok"), "mode": mode, "durable_storage": boolean}),
    }
    paths = {}
    def route(method, path, operation, response, request=None, status=200, public=False, parameters=()):
        schema = {"operationId": operation, "summary": operation.replace("_", " "),
                  "responses": {str(status): {"description": "Development result", "content": {"application/json": {"schema": ref(response)}}},
                                "default": {"description": "Rejected input, authorization, transition, or internal error; do not treat as success.",
                                            "content": {"application/json": {"schema": ref("Error")}}}}}
        if public:
            schema["security"] = []
        if request:
            schema["requestBody"] = {"required": True, "content": {"application/json": {"schema": ref(request)}}}
        params = list(parameters)
        if "{relationship_id}" in path:
            params.append({"name": "relationship_id", "in": "path", "required": True, "schema": rid})
        if "{candidate_id}" in path:
            params.append({"name": "candidate_id", "in": "path", "required": True, "schema": uid})
        if params:
            schema["parameters"] = params
        paths.setdefault(path, {})[method.lower()] = schema

    route("GET", "/health", "development_health", "Health", public=True)
    route("POST", "/v1/dev/accounts", "create_synthetic_account", "Registration", "Register", status=201, public=True)
    route("POST", "/v1/dev/verify-email", "simulate_email_verification", "Account", "VerifySimulation")
    route("GET", "/v1/me", "get_own_account", "Account")
    route("DELETE", "/v1/me", "delete_own_synthetic_account", "Deleted", "Delete")
    route("PUT", "/v1/me/profile", "replace_own_profile", "Account", "Profile")
    route("PUT", "/v1/me/preferences", "replace_own_preferences", "Account", "Preferences")
    route("GET", "/v1/me/assessment", "get_own_assessment", "Assessment")
    route("POST", "/v1/me/assessment/answers", "answer_current_assessment_question", "Assessment", "Answer")
    route("GET", "/v1/candidates", "list_mutually_eligible_candidates", "Candidates")
    route("GET", "/v1/candidates/{candidate_id}", "get_allowed_candidate_projection", "Candidate")
    route("GET", "/v1/relationships", "list_own_relationships", "Relationships")
    route("POST", "/v1/relationships", "request_card_only_relationship", "Relationship", "RelationshipRequest", status=201,
          parameters=[{"name": "Idempotency-Key", "in": "header", "required": True, "schema": {"type": "string", "pattern": "^[A-Za-z0-9_-]{8,64}$"}}])
    route("GET", "/v1/relationships/{relationship_id}", "get_own_relationship", "Relationship")
    route("POST", "/v1/relationships/{relationship_id}/respond", "recipient_respond_to_request", "Relationship", "Decision")
    route("POST", "/v1/relationships/{relationship_id}/cancel", "initiator_cancel_pending_request", "Relationship", "Empty")
    route("POST", "/v1/dev/relationships/{relationship_id}/activate", "simulate_initiator_entitlement", "Relationship", "ActivationSimulation")
    route("POST", "/v1/relationships/{relationship_id}/exclusive/request", "request_exclusivity", "Relationship", "Confirm")
    route("POST", "/v1/relationships/{relationship_id}/exclusive/respond", "respond_to_exclusivity", "Relationship", "Decision")
    route("POST", "/v1/relationships/{relationship_id}/end", "end_relationship", "Relationship", "Confirm")
    route("GET", "/v1/relationships/{relationship_id}/cards", "read_sample_library_cards_without_answers", "Cards")
    route("POST", "/v1/blocks", "block_account_without_payment", "Blocked", "Block")
    route("POST", "/v1/reports", "record_metadata_only_development_report", "ReportReceipt", "Report", status=201)
    return {"openapi": "3.1.0", "info": {"title": "Wainak phase-one synthetic development contract", "version": "0.1.0-dev",
            "description": "NOT PRODUCTION. Loopback only; default volatile memory, optional marked disposable PostgreSQL repository; synthetic @example.invalid accounts; no real email, authentication, payments, chat transport, medical data, moderation team, evidence upload, or production deletion pipeline. Current permissions override stale UI state. Unknown fields are rejected. JSON body limit: 16384 bytes. No query parameters or browser Origin headers."},
            "servers": [{"url": "http://127.0.0.1:8089", "description": "Manual loopback-only preview, never auto-started"}],
            "security": [{"developmentBearer": []}], "paths": paths,
            "components": {"securitySchemes": {"developmentBearer": {"type": "http", "scheme": "bearer",
                "description": "Ephemeral opaque development session. Not production authentication; invalidated at deletion or process exit."}}, "schemas": schemas}}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    content = json.dumps(build(), ensure_ascii=False, indent=2) + "\n"
    destination = ROOT / "phase1.openapi.json"
    if args.check:
        if not destination.exists() or destination.read_text() != content:
            raise SystemExit("OpenAPI contract differs from its builder; regenerate it.")
        print("OpenAPI artifact is synchronized.")
    else:
        destination.write_text(content)


if __name__ == "__main__":
    main()

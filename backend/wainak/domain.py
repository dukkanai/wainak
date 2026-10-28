"""Isolated synthetic domain slice. Never connect this development API to real users.

All reads and writes use one repository transaction, including eligibility checks.
The default repository is volatile memory. An optional PostgreSQL adapter is limited
to explicitly marked disposable databases; it is not production infrastructure.
"""

from __future__ import annotations

import copy
import hashlib
import re
import secrets
import threading
import uuid
from datetime import date, datetime, timezone
from functools import wraps

from .repository import MemoryRepository

POLICY_VERSION = "dev-2026-10-24"
RELATIONSHIP_PAGE_SIZE = 20
MARITAL = {"single", "married", "divorced", "widowed"}
GOALS = {"build_family", "companionship"}
REPORT_CATEGORIES = {"harassment", "threat", "impersonation", "child_safety", "other_safety"}
QUESTIONS = {
    "family_plan": {"id": "family_plan", "prompt_ar": "ما الأقرب لتصورك للحياة الأسرية؟", "options": ["children", "discuss_together", "prefer_not_to_say"]},
    "parenting": {"id": "parenting", "prompt_ar": "كيف تفضل مناقشة مسؤوليات الأبناء؟", "options": ["shared_planning", "discuss_roles", "not_applicable"]},
    "life_priorities": {"id": "life_priorities", "prompt_ar": "ما الموضوع الذي تود مناقشته أولًا؟", "options": ["home", "work", "family", "prefer_not_to_say"]},
    "communication": {"id": "communication", "prompt_ar": "كيف تفضل بدء النقاش عند الاختلاف؟", "options": ["quiet_time", "listen_first", "scheduled_talk"]},
}
CARDS = [
    {"id": "dialogue-001", "title_ar": "الحوار عند الاختلاف", "prompt_ar": "كيف تفضل بدء النقاش؟", "options": ["quiet_time", "listen_first", "scheduled_talk"], "free": True},
    {"id": "dialogue-002", "title_ar": "الحياة المشتركة", "prompt_ar": "ما أول موضوع تريدان مناقشته؟", "options": ["home", "work", "family"], "free": True},
]


class DomainError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


def fail(status=400, code="invalid_input", message="The submitted fields are not valid."):
    raise DomainError(status, code, message)


def fields(data, required, optional=()):
    if not isinstance(data, dict) or not set(required) <= data.keys() or set(data) - set(required) - set(optional):
        fail()


def choice(value, allowed):
    if not isinstance(value, str) or value not in allowed:
        fail()
    return value


def integer(value, low, high):
    if type(value) is not int or not low <= value <= high:
        fail()
    return value


def country(value):
    # Syntax only: country/region catalogs and localization are later work.
    if not isinstance(value, str) or len(value) != 2 or not value.isascii() or not value.isalpha() or value != value.upper():
        fail()
    return value


def locked(method):
    @wraps(method)
    def wrapped(self, *args, **kwargs):
        with self._lock:
            if self._transaction_depth:
                return copy.deepcopy(method(self, *args, **kwargs))
            with self.repository.transaction() as state:
                for name in state.__dataclass_fields__:
                    setattr(self, name, getattr(state, name))
                self._transaction_depth = 1
                try:
                    result = copy.deepcopy(method(self, *args, **kwargs))
                    for name in state.__dataclass_fields__:
                        setattr(state, name, getattr(self, name))
                finally:
                    self._transaction_depth = 0
            return result
    return wrapped


class DevelopmentService:
    """Synthetic accounts only, with explicit transactional repository injection."""

    def __init__(self, today=None, repository=None):
        self.today = today or date.today
        self._lock = threading.RLock()
        self._transaction_depth = 0
        self.repository = repository or MemoryRepository()
        self.accounts = {}
        self.sessions = {}
        self.relationships = {}
        self.blocks = set()
        self.reports = {}
        self.idempotency = {}

    @staticmethod
    def _id(prefix):
        return f"{prefix}_{uuid.uuid4().hex}"

    @staticmethod
    def _token_hash(token):
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    def _account(self, actor):
        account = self.accounts.get(actor)
        if account is None or account["deleted"]:
            fail(401, "unauthenticated", "A current development session is required.")
        return account

    def _age(self, account):
        born = date.fromisoformat(account["birth_date"])
        today = self.today()
        return today.year - born.year - ((today.month, today.day) < (born.month, born.day))

    def _eligible(self, account, allow_exclusive=None):
        profile = account.get("profile")
        if account["deleted"] or not account["dev_email_verified"] or not profile or not account["preferences"]:
            return False
        if self._age(account) < 18 or not account["is_muslim"]:
            return False
        if account["exclusive_relationship_id"] not in (None, allow_exclusive):
            return False
        if profile["gender"] == "female" and profile["marital_status"] == "married":
            return False
        return profile["declared_wives"] < 4

    def _blocked(self, a, b):
        return (a, b) in self.blocks or (b, a) in self.blocks

    def _accepts(self, a, b):
        prefs, profile = a["preferences"], b["profile"]
        return (prefs["min_age"] <= self._age(b) <= prefs["max_age"]
                and (not prefs["countries"] or profile["country"] in prefs["countries"])
                and profile["marital_status"] in prefs["marital_statuses"])

    def _pair_eligible(self, a, b, relationship_id=None):
        return (a != b and a in self.accounts and b in self.accounts
                and self._eligible(self.accounts[a], relationship_id)
                and self._eligible(self.accounts[b], relationship_id)
                and self.accounts[a]["profile"]["gender"] != self.accounts[b]["profile"]["gender"]
                and not self._blocked(a, b))

    def _discoverable(self, a, b):
        return (self._pair_eligible(a, b)
                and self.accounts[a]["profile"]["discoverable"]
                and self.accounts[b]["profile"]["discoverable"]
                and self._accepts(self.accounts[a], self.accounts[b])
                and self._accepts(self.accounts[b], self.accounts[a]))

    def _public(self, account):
        profile = account["profile"]
        return {"id": account["id"], "alias": account["alias"], "age": self._age(account),
                "country": profile["country"], "marital_status": profile["marital_status"],
                "marriage_goal": profile["marriage_goal"],
                "rating": {"state": "insufficient_data"}, "synthetic": True}

    def _relationship(self, actor, relationship_id):
        self._account(actor)
        rel = self.relationships.get(relationship_id)
        if rel is None or actor not in (rel["initiator_id"], rel["recipient_id"]):
            fail(404, "not_found", "The resource is not available.")
        return rel

    def _release_exclusivity(self, rel):
        for member in (rel["initiator_id"], rel["recipient_id"]):
            if self.accounts[member]["exclusive_relationship_id"] == rel["id"]:
                self.accounts[member]["exclusive_relationship_id"] = None
        rel["exclusive_requested_by"] = None

    def _view_relationship(self, actor, rel):
        peer = rel["recipient_id"] if actor == rel["initiator_id"] else rel["initiator_id"]
        enabled = rel["status"] in ("active_cards", "exclusive_cards") and self._pair_eligible(actor, peer, rel["id"])
        peer_account = self.accounts[peer]
        public_peer = None if peer_account["deleted"] or self._blocked(actor, peer) else self._public(peer_account)
        status = rel["status"]
        if status in ("active_cards", "exclusive_cards") and not enabled:
            status = "frozen"
        return {"id": rel["id"], "initiator_id": rel["initiator_id"], "recipient_id": rel["recipient_id"],
                "status": status, "peer": public_peer,
                "exclusive_requested_by": rel["exclusive_requested_by"],
                "permissions": {"can_send_cards": enabled, "can_send_text": False,
                                "can_send_media": False, "can_disclose_identity": False},
                "activation_mode": "development_simulation_only"}

    @locked
    def register(self, data):
        fields(data, {"email", "birth_date", "is_muslim", "terms_version", "privacy_version"})
        email = data["email"]
        if not isinstance(email, str) or len(email) > 100 or not email.endswith("@example.invalid"):
            fail(400, "synthetic_email_required", "Only synthetic @example.invalid addresses are accepted.")
        local = email.removesuffix("@example.invalid")
        if not local or len(local) > 64 or any(c not in "abcdefghijklmnopqrstuvwxyz0123456789._-" for c in local):
            fail()
        try:
            if not isinstance(data["birth_date"], str) or len(data["birth_date"]) != 10:
                fail()
            born = date.fromisoformat(data["birth_date"])
        except (ValueError, TypeError):
            fail()
        age = self.today().year - born.year - ((self.today().month, self.today().day) < (born.month, born.day))
        if not 18 <= age <= 120 or data["is_muslim"] is not True:
            fail(403, "not_eligible", "This development journey requires the stated adult eligibility.")
        if data["terms_version"] != POLICY_VERSION or data["privacy_version"] != POLICY_VERSION:
            fail(400, "consent_required", "Explicit acceptance of the current development policies is required.")
        if any(a.get("email") == email and not a["deleted"] for a in self.accounts.values()):
            fail(409, "account_exists", "This synthetic account already exists.")
        identifier, token = self._id("usr"), secrets.token_urlsafe(32)
        account = {"id": identifier, "alias": f"حساب تجريبي {identifier[-6:]}", "email": email,
                   "birth_date": born.isoformat(), "is_muslim": True, "dev_email_verified": False,
                   "consents": {"terms_version": POLICY_VERSION, "privacy_version": POLICY_VERSION,
                                "accepted_at": datetime.now(timezone.utc).isoformat()},
                   "profile": None, "preferences": None, "assessment_answers": {},
                   "exclusive_relationship_id": None, "deleted": False}
        self.accounts[identifier] = account
        self.sessions[self._token_hash(token)] = identifier
        return {"account": self.me(identifier), "access_token": token,
                "token_type": "Bearer", "mode": "synthetic_development_only"}

    @locked
    def authenticate(self, token):
        if not isinstance(token, str) or not 20 <= len(token) <= 256:
            fail(401, "unauthenticated", "A current development session is required.")
        actor = self.sessions.get(self._token_hash(token))
        self._account(actor)
        return actor

    @locked
    def me(self, actor):
        account = self._account(actor)
        return {"id": account["id"], "alias": account["alias"], "email": account["email"],
                "age": self._age(account), "dev_email_verified": account["dev_email_verified"],
                "consents": account["consents"], "profile": account["profile"],
                "preferences": account["preferences"], "eligible_for_discovery": self._eligible(account),
                "mode": "synthetic_development_only"}

    @locked
    def verify_email(self, actor, data):
        fields(data, {"simulate_verified"})
        if data["simulate_verified"] is not True:
            fail()
        self._account(actor)["dev_email_verified"] = True
        return self.me(actor)

    @locked
    def update_profile(self, actor, data):
        account = self._account(actor)
        fields(data, {"gender", "country", "marital_status", "declared_wives", "marriage_goal", "discoverable"})
        gender = choice(data["gender"], {"male", "female"})
        marital = choice(data["marital_status"], MARITAL)
        wives = integer(data["declared_wives"], 0, 4)
        country(data["country"])
        choice(data["marriage_goal"], GOALS)
        if type(data["discoverable"]) is not bool:
            fail()
        if (gender != "male" or marital != "married") and wives != 0:
            fail()
        if gender == "male" and marital == "married" and wives == 0:
            fail()
        account["profile"] = copy.deepcopy(data)
        # Marital declaration is never modified by unlink/block/delete.
        return self.me(actor)

    @locked
    def update_preferences(self, actor, data):
        account = self._account(actor)
        fields(data, {"min_age", "max_age", "countries", "marital_statuses"})
        integer(data["min_age"], 18, 120)
        integer(data["max_age"], 18, 120)
        if data["min_age"] > data["max_age"]:
            fail()
        if not isinstance(data["countries"], list) or len(data["countries"]) > 20:
            fail()
        for code in data["countries"]:
            country(code)
        if len(data["countries"]) != len(set(data["countries"])):
            fail()
        if not isinstance(data["marital_statuses"], list) or not 1 <= len(data["marital_statuses"]) <= 4:
            fail()
        for status in data["marital_statuses"]:
            choice(status, MARITAL)
        if len(data["marital_statuses"]) != len(set(data["marital_statuses"])):
            fail()
        account["preferences"] = copy.deepcopy(data)
        return self.me(actor)

    def _assessment_path(self, account):
        answer = account["assessment_answers"].get("family_plan")
        return ["family_plan", "parenting" if answer == "children" else "life_priorities", "communication"]

    @locked
    def assessment(self, actor):
        account = self._account(actor)
        answers = account["assessment_answers"]
        path = self._assessment_path(account)
        next_id = next((q for q in path if q not in answers), None)
        return {"answers": answers, "next_question": QUESTIONS[next_id] if next_id else None,
                "answered_count": len(answers), "complete": next_id is None,
                "disclaimer": "Illustrative needs reflection, not a diagnosis or compatibility score."}

    @locked
    def answer(self, actor, data):
        account = self._account(actor)
        fields(data, {"question_id", "option_id"})
        qid = choice(data["question_id"], QUESTIONS)
        choice(data["option_id"], QUESTIONS[qid]["options"])
        state = self.assessment(actor)
        # Answers can be revised, but later questions cannot be skipped ahead.
        if qid not in account["assessment_answers"] and (not state["next_question"] or qid != state["next_question"]["id"]):
            fail(409, "question_not_current", "Answer the current question first.")
        changed = account["assessment_answers"].get(qid) != data["option_id"]
        account["assessment_answers"][qid] = data["option_id"]
        if changed and qid == "family_plan":
            account["assessment_answers"] = {"family_plan": data["option_id"]}
        return self.assessment(actor)

    @locked
    def candidates(self, actor):
        self._account(actor)
        candidates = [self._public(account) for identifier, account in sorted(self.accounts.items()) if self._discoverable(actor, identifier)]
        # No total, health filters, hidden reasons, or invented compatibility score.
        return {"items": candidates[:20], "mode": "synthetic_development_only"}

    @locked
    def candidate(self, actor, target):
        self._account(actor)
        if not self._discoverable(actor, target):
            fail(404, "not_found", "The resource is not available.")
        return self._public(self.accounts[target])

    @locked
    def request(self, actor, data, key):
        self._account(actor)
        fields(data, {"candidate_id"})
        target = data["candidate_id"]
        if not isinstance(target, str) or not isinstance(key, str) or not 8 <= len(key) <= 64 or not all(c.isascii() and (c.isalnum() or c in "-_") for c in key):
            fail(400, "idempotency_key_required", "Use an 8–64 character Idempotency-Key.")
        prior = self.idempotency.get((actor, key))
        if prior:
            if prior[0] != target:
                fail(409, "idempotency_conflict", "The key was already used for another request.")
            return self._view_relationship(actor, self.relationships[prior[1]])
        if not self._discoverable(actor, target):
            fail(404, "not_found", "The resource is not available.")
        # Ended/declined requests cannot be bypassed by creating another pair;
        # the separately authorized return flow has not been built in this phase.
        if any({r["initiator_id"], r["recipient_id"]} == {actor, target} for r in self.relationships.values()):
            fail(409, "relationship_exists", "Use the existing relationship; reopening is unavailable in this phase.")
        rel = {"id": self._id("rel"), "initiator_id": actor, "recipient_id": target,
               "status": "requested", "exclusive_requested_by": None}
        self.relationships[rel["id"]] = rel
        self.idempotency[(actor, key)] = (target, rel["id"])
        return self._view_relationship(actor, rel)

    @locked
    def list_relationships(self, actor, cursor=None):
        self._account(actor)
        # Stable IDs, rather than dictionary insertion order, survive a database
        # round trip. Cursor validation is actor-scoped and reveals no other pair.
        identifiers = sorted(identifier for identifier, relationship in self.relationships.items()
                             if actor in (relationship["initiator_id"], relationship["recipient_id"]))
        if cursor is not None and (not isinstance(cursor, str)
                or re.fullmatch(r"rel_[0-9a-f]{32}", cursor) is None or cursor not in identifiers):
            fail(400, "invalid_relationship_cursor", "Refresh the relationship list before continuing.")
        start = identifiers.index(cursor) + 1 if cursor is not None else 0
        page = identifiers[start:start + RELATIONSHIP_PAGE_SIZE]
        return {"items": [self._view_relationship(actor, self.relationships[identifier]) for identifier in page],
                "next_cursor": page[-1] if start + len(page) < len(identifiers) else None}

    @locked
    def relationship(self, actor, identifier):
        return self._view_relationship(actor, self._relationship(actor, identifier))

    @locked
    def respond(self, actor, identifier, data):
        fields(data, {"decision"})
        decision = choice(data["decision"], {"accept", "decline"})
        rel = self._relationship(actor, identifier)
        if actor != rel["recipient_id"]:
            fail(403, "recipient_required", "Only the recipient can respond.")
        result = "accepted_pending_activation" if decision == "accept" else "declined"
        if rel["status"] == result:
            return self._view_relationship(actor, rel)
        if rel["status"] != "requested":
            fail(409, "invalid_transition", "This request is no longer pending.")
        if decision == "accept" and not self._discoverable(rel["initiator_id"], rel["recipient_id"]):
            fail(409, "relationship_unavailable", "This relationship is not currently available.")
        rel["status"] = result
        return self._view_relationship(actor, rel)

    @locked
    def cancel(self, actor, identifier, data):
        fields(data, set())
        rel = self._relationship(actor, identifier)
        if actor != rel["initiator_id"]:
            fail(403, "initiator_required", "Only the initiator can cancel a pending request.")
        if rel["status"] not in ("requested", "cancelled"):
            fail(409, "invalid_transition", "This request is no longer pending.")
        rel["status"] = "cancelled"
        return self._view_relationship(actor, rel)

    @locked
    def activate(self, actor, identifier, data):
        fields(data, {"simulate_entitlement"})
        if data["simulate_entitlement"] is not True:
            fail()
        rel = self._relationship(actor, identifier)
        if actor != rel["initiator_id"]:
            fail(403, "initiator_required", "Only the initiator can simulate activation.")
        if rel["status"] not in ("accepted_pending_activation", "active_cards"):
            fail(409, "invalid_transition", "Mutual acceptance is required before activation.")
        if not self._pair_eligible(rel["initiator_id"], rel["recipient_id"], rel["id"]):
            fail(409, "relationship_unavailable", "This relationship is not currently available.")
        rel["status"] = "active_cards"
        return self._view_relationship(actor, rel)

    @locked
    def request_exclusive(self, actor, identifier, data):
        fields(data, {"confirm"})
        if data["confirm"] is not True:
            fail()
        rel = self._relationship(actor, identifier)
        if rel["status"] != "active_cards" or not self._pair_eligible(rel["initiator_id"], rel["recipient_id"]):
            fail(409, "relationship_unavailable", "This relationship is not currently available.")
        if rel["exclusive_requested_by"] not in (None, actor):
            fail(409, "proposal_exists", "Respond to the existing proposal instead.")
        rel["exclusive_requested_by"] = actor
        return self._view_relationship(actor, rel)

    @locked
    def respond_exclusive(self, actor, identifier, data):
        fields(data, {"decision"})
        decision = choice(data["decision"], {"accept", "decline"})
        rel = self._relationship(actor, identifier)
        if rel["status"] != "active_cards" or not rel["exclusive_requested_by"]:
            fail(409, "invalid_transition", "There is no pending exclusivity proposal.")
        if rel["exclusive_requested_by"] == actor:
            fail(403, "recipient_required", "The other participant must respond.")
        if decision == "accept":
            if not self._pair_eligible(rel["initiator_id"], rel["recipient_id"]):
                fail(409, "relationship_unavailable", "This relationship is not currently available.")
            rel["status"] = "exclusive_cards"
            for member in (rel["initiator_id"], rel["recipient_id"]):
                self.accounts[member]["exclusive_relationship_id"] = identifier
        rel["exclusive_requested_by"] = None
        return self._view_relationship(actor, rel)

    @locked
    def end(self, actor, identifier, data):
        fields(data, {"confirm"})
        if data["confirm"] is not True:
            fail()
        rel = self._relationship(actor, identifier)
        if rel["status"] not in ("accepted_pending_activation", "active_cards", "exclusive_cards", "ended"):
            fail(409, "invalid_transition", "This relationship cannot be ended in its current state.")
        rel["status"] = "ended"
        self._release_exclusivity(rel)
        return self._view_relationship(actor, rel)

    def _can_address(self, actor, target):
        return (isinstance(target, str) and actor != target and target in self.accounts
                and not self.accounts[target]["deleted"]
                and (self._discoverable(actor, target) or self._blocked(actor, target)
                     or any({r["initiator_id"], r["recipient_id"]} == {actor, target} for r in self.relationships.values())))

    @locked
    def block(self, actor, data):
        self._account(actor)
        fields(data, {"target_id"})
        target = data["target_id"]
        if not self._can_address(actor, target):
            fail(404, "not_found", "The resource is not available.")
        self.blocks.add((actor, target))
        for rel in self.relationships.values():
            if {rel["initiator_id"], rel["recipient_id"]} == {actor, target}:
                rel["status"] = "blocked"
                self._release_exclusivity(rel)
        return {"blocked": True}

    @locked
    def report(self, actor, data):
        self._account(actor)
        fields(data, {"target_id", "category"}, {"relationship_id"})
        choice(data["category"], REPORT_CATEGORIES)
        target = data["target_id"]
        if not self._can_address(actor, target):
            fail(404, "not_found", "The resource is not available.")
        if "relationship_id" in data:
            if not isinstance(data["relationship_id"], str):
                fail()
            rel = self._relationship(actor, data["relationship_id"])
            if {rel["initiator_id"], rel["recipient_id"]} != {actor, target}:
                fail(404, "not_found", "The resource is not available.")
        report = {"id": self._id("rpt"), "reporter_id": actor, "target_id": target,
                  "category": data["category"], "relationship_id": data.get("relationship_id"),
                  "status": "recorded_development_only", "evidence_uploaded": False}
        self.reports[report["id"]] = report
        return {"id": report["id"], "status": report["status"], "evidence_uploaded": False,
                "notice": "No live moderation team is connected. This simulation applies no public penalty."}

    @locked
    def delete_account(self, actor, data):
        account = self._account(actor)
        fields(data, {"confirmation"})
        if data["confirmation"] != "DELETE":
            fail(400, "confirmation_required", "Confirm account deletion explicitly.")
        for rel in self.relationships.values():
            if actor in (rel["initiator_id"], rel["recipient_id"]):
                rel["status"] = "ended"
                self._release_exclusivity(rel)
        self.sessions = {token: member for token, member in self.sessions.items() if member != actor}
        self.idempotency = {key: value for key, value in self.idempotency.items() if key[0] != actor}
        self.blocks = {pair for pair in self.blocks if actor not in pair}
        self.reports = {key: value for key, value in self.reports.items() if actor not in (value["reporter_id"], value["target_id"])}
        account.clear()
        account.update({"id": actor, "deleted": True, "exclusive_relationship_id": None})
        return {"deleted": True, "mode": "synthetic_development_only",
                "notice": "Synthetic profile/session erased from this repository. This does not change a real marital status or cancel a store subscription."}

    @locked
    def content(self, actor, identifier):
        rel = self._relationship(actor, identifier)
        if not self._view_relationship(actor, rel)["permissions"]["can_send_cards"]:
            fail(409, "relationship_unavailable", "This relationship is not currently available.")
        return {"items": CARDS, "answers_transport": "not_implemented", "server_stores_dialogue_answers": False}

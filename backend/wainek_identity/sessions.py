"""Framework session backend: SHA256 lookup + standard Fernet payload encryption.

Fixture encryption/signing keys live in the harness parent's memory only. Nothing
here provisions production key storage, recovery, rotation or an E2EE identity.
"""
import hashlib
import hmac
import json
from datetime import timedelta

from asgiref.sync import sync_to_async
from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.contrib.auth import SESSION_KEY
from django.contrib.sessions.backends.db import SessionStore as DatabaseSessionStore
from django.utils import timezone


def digest_token(token):
    if not isinstance(token, str) or not 20 <= len(token) <= 256:
        return None
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def email_fingerprint(email):
    return hmac.new(settings.WAINEK_RATE_KEY, ("session-email\0" + email.lower()).encode(), hashlib.sha256).hexdigest()


def decode_payload(encoded, expected_digest):
    try:
        plaintext = Fernet(settings.WAINEK_SESSION_ENCRYPTION_KEY).decrypt(encoded.encode("ascii"))
        envelope = json.loads(plaintext)
        if envelope["digest"] != expected_digest or not isinstance(envelope["data"], dict):
            return {}
        return envelope["data"]
    except (InvalidToken, ValueError, KeyError, TypeError, UnicodeError):
        return {}


class SessionStore(DatabaseSessionStore):
    @classmethod
    def get_model_class(cls):
        from .models import DigestSession
        return DigestSession

    def _get_session_from_db(self):
        digest = digest_token(self.session_key)
        if digest:
            now = timezone.now()
            try:
                return self.model.objects.get(
                    session_key=digest, expire_date__gt=now,
                    created_at__gt=now - timedelta(seconds=settings.WAINEK_SESSION_ABSOLUTE_SECONDS),
                    last_seen_at__gt=now - timedelta(seconds=settings.WAINEK_SESSION_IDLE_SECONDS))
            except self.model.DoesNotExist:
                pass
        self._session_key = None
        return None

    def load(self):
        row = self._get_session_from_db()
        if row is None:
            return {}
        data = decode_payload(row.session_data, row.session_key)
        if not data:
            self._session_key = None  # Corruption/key loss fails closed, never authenticates.
            return {}
        # Valid read activity extends the idle window, NEVER the absolute cap.
        # HTTP calls hold the outer transaction/lock before reaching this load.
        now = timezone.now()
        row.last_seen_at = now
        row.expire_date = min(now + timedelta(seconds=settings.WAINEK_SESSION_IDLE_SECONDS),
                              row.created_at + timedelta(seconds=settings.WAINEK_SESSION_ABSOLUTE_SECONDS),
                              self.get_expiry_date(modification=now, expiry=data.get("_session_expiry")))
        row.save(update_fields=["last_seen_at", "expire_date"])
        return data

    def exists(self, session_key):
        digest = digest_token(session_key)
        return bool(digest) and self.model.objects.filter(session_key=digest).exists()

    def create_model_instance(self, data):
        raw = self._get_or_create_session_key()
        digest = digest_token(raw)
        now = timezone.now()
        old = self.model.objects.filter(session_key=digest).first()
        created = old.created_at if old else now
        expires = min(self.get_expiry_date(), created + timedelta(seconds=settings.WAINEK_SESSION_ABSOLUTE_SECONDS),
                      now + timedelta(seconds=settings.WAINEK_SESSION_IDLE_SECONDS))
        envelope = json.dumps({"digest": digest, "data": data}, separators=(",", ":"), ensure_ascii=True).encode()
        encrypted = Fernet(settings.WAINEK_SESSION_ENCRYPTION_KEY).encrypt(envelope).decode("ascii")
        from .models import User
        from django.core.exceptions import ValidationError
        pending = data.get("account_email_verification_code", {})
        identifier = data.get(SESSION_KEY) or pending.get("user_id")
        try:
            owner = User.objects.filter(pk=identifier).first() if identifier else None
        except (ValueError, ValidationError):
            owner = None
        email = owner.email if owner else pending.get("email")
        return self.model(session_key=digest, session_data=encrypted, expire_date=expires,
                          created_at=created, last_seen_at=now, user=owner,
                          subject_email_digest=email_fingerprint(email) if email else None)

    def encode(self, session_dict):
        raise RuntimeError("Use create_model_instance for row-bound encryption")

    def decode(self, session_data):
        raise RuntimeError("Use decode_payload with the expected row digest")

    def delete(self, session_key=None):
        digest = digest_token(self.session_key if session_key is None else session_key)
        if digest:
            self.model.objects.filter(session_key=digest).delete()

    # Override ALL raw-key database async fallbacks; use the same supported sync
    # implementation. The current HTTP harness itself is synchronous WSGI only.
    async def aload(self):
        return await sync_to_async(self.load, thread_sensitive=True)()

    async def aexists(self, session_key):
        return await sync_to_async(self.exists, thread_sensitive=True)(session_key)

    async def acreate(self):
        return await sync_to_async(self.create, thread_sensitive=True)()

    async def asave(self, must_create=False):
        return await sync_to_async(self.save, thread_sensitive=True)(must_create=must_create)

    async def adelete(self, session_key=None):
        return await sync_to_async(self.delete, thread_sensitive=True)(session_key)

    async def _aget_session_from_db(self):
        return await sync_to_async(self._get_session_from_db, thread_sensitive=True)()

    async def acreate_model_instance(self, data):
        return await sync_to_async(self.create_model_instance, thread_sensitive=True)(data)

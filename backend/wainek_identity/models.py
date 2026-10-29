import uuid
from django.contrib.auth.models import AbstractUser, UserManager
from django.contrib.sessions.base_session import AbstractBaseSession
from django.db import models
from django.db.models.functions import Lower


class IdentityUserManager(UserManager):
    def _create_user(self, username, email, password, **extra):
        if not email:
            raise ValueError("An email address is required")
        user = self.model(email=email.strip().lower(), **extra)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email, password=None, **extra):
        extra.setdefault("is_staff", False)
        extra.setdefault("is_superuser", False)
        return self._create_user(None, email, password, **extra)

    def create_superuser(self, *args, **kwargs):
        raise RuntimeError("Persistent/admin accounts are outside the synthetic identity harness")


class User(AbstractUser):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    username = None
    first_name = None
    last_name = None
    email = models.EmailField(max_length=100, unique=True)
    domain_id = models.CharField(max_length=36, unique=True, null=True)
    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []
    objects = IdentityUserManager()

    class Meta:
        constraints = [models.UniqueConstraint(Lower("email"), name="identity_email_case_unique")]

    def __str__(self):
        return "Synthetic identity account"


class DigestSessionManager(models.Manager):
    def encode(self, session_dict):
        raise RuntimeError("Use SessionStore: encrypted payloads must be row-bound")

    def save(self, session_key, session_dict, expire_date):
        raise RuntimeError("Use SessionStore: raw session keys must never reach the model")


class DigestSession(AbstractBaseSession):
    # This is a digest lookup key, NEVER the client's raw session secret.
    session_key = models.CharField(max_length=64, primary_key=True)
    objects = DigestSessionManager()
    user = models.ForeignKey(User, null=True, on_delete=models.CASCADE)
    subject_email_digest = models.CharField(max_length=64, null=True, db_index=True)
    created_at = models.DateTimeField()
    last_seen_at = models.DateTimeField()

    class Meta:
        constraints = [models.CheckConstraint(condition=models.Q(session_key__regex=r"^[0-9a-f]{64}$"),
                                              name="identity_session_digest_format")]

    def __str__(self):
        return "Encrypted synthetic session"

    @classmethod
    def get_session_store_class(cls):
        from .sessions import SessionStore
        return SessionStore

    def get_decoded(self):
        from .sessions import decode_payload
        return decode_payload(self.session_data, self.session_key)


class RateBucket(models.Model):
    key = models.CharField(max_length=64, primary_key=True)
    count = models.PositiveIntegerField()
    expires_at = models.DateTimeField(db_index=True)


class MutationReceipt(models.Model):
    actor = models.ForeignKey(User, on_delete=models.CASCADE)
    operation = models.CharField(max_length=32)
    key_digest = models.CharField(max_length=64)
    payload_digest = models.CharField(max_length=64)
    resource_id = models.CharField(max_length=40)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["actor", "operation", "key_digest"], name="identity_mutation_key_unique")]


class DeletionReceipt(models.Model):
    # Minimal synthetic tombstone; no email, DOB, credentials or dialogue content.
    account_id = models.UUIDField(primary_key=True)
    domain_id = models.CharField(max_length=36)
    deleted_at = models.DateTimeField()
    policy = models.CharField(max_length=64, default="synthetic-purge-v1-not-production-retention")

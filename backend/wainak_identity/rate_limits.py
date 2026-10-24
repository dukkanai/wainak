"""Atomic PostgreSQL counters shared by independent processes; no local cache."""
import hashlib
import hmac
from datetime import timedelta
from django.conf import settings
from django.db import connection
from django.utils import timezone
from .models import RateBucket


def subject_digest(action, kind, subject):
    value = f"{action}\0{kind}\0{subject}".encode()
    return hmac.new(settings.WAINAK_RATE_KEY, value, hashlib.sha256).hexdigest()


def consume(action, kind, subject, limit, seconds, *, now=None):
    now = now or timezone.now()
    key = subject_digest(action, kind, subject)
    table = connection.ops.quote_name(RateBucket._meta.db_table)
    # Single statement wins/loses atomically even without the outer HTTP lock.
    with connection.cursor() as cursor:
        cursor.execute(f'''INSERT INTO {table} (key,count,expires_at) VALUES (%s,1,%s)
            ON CONFLICT (key) DO UPDATE SET
                count=CASE WHEN {table}.expires_at<=%s THEN 1 ELSE {table}.count+1 END,
                expires_at=CASE WHEN {table}.expires_at<=%s THEN EXCLUDED.expires_at ELSE {table}.expires_at END
            WHERE {table}.expires_at<=%s OR {table}.count<%s RETURNING count''',
            (key, now+timedelta(seconds=seconds), now, now, now, limit))
        return cursor.fetchone() is not None


def prune_expired_security_state():
    from .models import DigestSession
    now = timezone.now()
    RateBucket.objects.filter(expires_at__lte=now).delete()
    DigestSession.objects.filter(expire_date__lte=now).delete()

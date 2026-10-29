from django.dispatch import receiver
from allauth.account import signals
from .models import DigestSession


@receiver(signals.email_confirmed)
def email_confirmed(sender, request, email_address, **kwargs):
    from .repository import service
    if email_address.user.domain_id:
        service().verify_email(email_address.user.domain_id, {"simulate_verified": True})


@receiver(signals.password_reset)
@receiver(signals.password_changed)
def revoke_password_sessions(sender, request, user, **kwargs):
    from django.db.models import Q
    from .sessions import email_fingerprint, digest_token
    affected = DigestSession.objects.filter(Q(user=user) | Q(subject_email_digest=email_fingerprint(user.email)))
    # A public reset may be submitted while a DIFFERENT account is signed in.
    # Flush only the affected authenticated/pending request session before the
    # allauth context's final save; do not revoke an unrelated actor's session.
    current = digest_token(request.session.session_key)
    flush_current = bool(current) and affected.filter(session_key=current).exists()
    affected.delete()
    if flush_current:
        from django.contrib.auth import logout
        logout(request)

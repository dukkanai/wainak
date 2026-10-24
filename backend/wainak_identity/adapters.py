import re
from django.core.exceptions import ValidationError
from django.utils import timezone
from allauth.account.adapter import DefaultAccountAdapter
from allauth.headless.adapter import DefaultHeadlessAdapter


def canonical_email(value):
    value = value.strip().lower()
    if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,63}@example\.invalid", value) or len(value) > 100:
        raise ValidationError("Only synthetic @example.invalid addresses are accepted.", code="synthetic_email_required")
    # No provider-specific dot/plus rewriting and no account merging.
    return value


class AccountAdapter(DefaultAccountAdapter):
    def clean_email(self, email):
        return canonical_email(email)

    def get_client_ip(self, request):
        return request.META.get("REMOTE_ADDR", "unknown")  # Ignore every forwarded header.

    def login(self, request, user):
        super().login(request, user)
        request.session["recent_auth_at"] = timezone.now().timestamp()

    def send_mail(self, template_prefix, email, context):
        canonical_email(email)
        from django.conf import settings
        if settings.EMAIL_BACKEND != "django.core.mail.backends.locmem.EmailBackend":
            raise RuntimeError("Real email backends are disabled in this milestone")
        from django.db import transaction
        from .mailbox import OUTBOX
        message = self.render_mail(template_prefix, email, context)
        record = {"recipient": email, "template": template_prefix,
                  "code": context.get("code"), "reset_url": context.get("password_reset_url")}
        def deliver_fake():
            message.send()
            OUTBOX.append(record)
        transaction.on_commit(deliver_fake)


class HeadlessAdapter(DefaultHeadlessAdapter):
    def serialize_user(self, user):
        # Framework payloads can be used in partially authenticated flows.
        # Do not expose an account identifier until this request is authenticated.
        if not self.request.user.is_authenticated:
            return {}
        return {"id": str(user.pk), "domain_id": user.domain_id, "email": user.email}

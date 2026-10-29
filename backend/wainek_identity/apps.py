from django.apps import AppConfig


class IdentityConfig(AppConfig):
    name = "wainek_identity"
    # Persisted label preserves existing tables, content types and migration history.
    label = "wainak_identity"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        from . import signals  # noqa: F401

from django.apps import AppConfig


class IdentityConfig(AppConfig):
    name = "wainak_identity"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        from . import signals  # noqa: F401

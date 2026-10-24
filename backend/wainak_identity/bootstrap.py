"""Only the disposable harness configures this application, using in-memory keys."""
import secrets
from cryptography.fernet import Fernet


def ephemeral_keys():
    return {"signing": secrets.token_urlsafe(64), "sessions": Fernet.generate_key(), "rate": secrets.token_bytes(32)}


def configure(connect=None, *, keys=None, schema_artifact_only=False):
    from django.conf import settings
    if settings.configured:
        raise RuntimeError("Identity settings must be configured once in an isolated process")
    if schema_artifact_only:
        database = {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}
    else:
        if connect is None:
            raise RuntimeError("Only a private disposable database connection factory is accepted")
        from wainak.migrations import require_disposable_database
        with connect() as connection:
            require_disposable_database(connection)
            marker = connection.execute("SELECT mode FROM wainak_phase1_dev.schema_metadata WHERE singleton=true").fetchone()
            if marker != ("synthetic_development_only",):
                raise RuntimeError("The reviewed disposable schema marker is required")
            info = connection.info
            database = {"ENGINE": "django.db.backends.postgresql", "NAME": info.dbname,
                        "HOST": info.host, "PORT": info.port, "USER": info.user, "PASSWORD": info.password,
                        "CONN_MAX_AGE": 0, "OPTIONS": {"connect_timeout": 3}}
    keys = keys or ephemeral_keys()
    settings.configure(
        SECRET_KEY=keys["signing"], DEBUG=False, DATABASES={"default": database},
        INSTALLED_APPS=["django.contrib.auth", "django.contrib.contenttypes", "django.contrib.sessions",
                        "django.contrib.messages", "wainak_identity.apps.IdentityConfig", "allauth",
                        "allauth.account", "allauth.headless"],
        MIDDLEWARE=["wainak_identity.middleware.SyntheticBoundary",
                    "django.contrib.sessions.middleware.SessionMiddleware",
                    "django.contrib.auth.middleware.AuthenticationMiddleware",
                    "django.contrib.messages.middleware.MessageMiddleware",
                    "allauth.account.middleware.AccountMiddleware"],
        ROOT_URLCONF="wainak_identity.urls", AUTH_USER_MODEL="wainak_identity.User",
        AUTHENTICATION_BACKENDS=["allauth.account.auth_backends.AuthenticationBackend"],
        SESSION_ENGINE="wainak_identity.sessions", SESSION_COOKIE_SECURE=True,
        SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Strict", SESSION_SAVE_EVERY_REQUEST=False,
        SESSION_COOKIE_AGE=86400, WAINAK_SESSION_ABSOLUTE_SECONDS=86400,
        WAINAK_SESSION_IDLE_SECONDS=1800, WAINAK_REAUTH_SECONDS=300,
        WAINAK_SESSION_ENCRYPTION_KEY=keys["sessions"], WAINAK_RATE_KEY=keys["rate"],
        WAINAK_IDENTITY_SANDBOX=not schema_artifact_only, WAINAK_DISABLE_LIMITS_FOR_FIXTURES=False,
        ALLOWED_HOSTS=["localhost", "127.0.0.1"], USE_TZ=True, TIME_ZONE="UTC",
        DEFAULT_AUTO_FIELD="django.db.models.BigAutoField",
        TEMPLATES=[{"BACKEND": "django.template.backends.django.DjangoTemplates", "APP_DIRS": True,
                    "OPTIONS": {"context_processors": ["django.template.context_processors.request"]}}],
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend", DEFAULT_FROM_EMAIL="noreply@example.invalid",
        PASSWORD_HASHERS=["django.contrib.auth.hashers.Argon2PasswordHasher"],
        AUTH_PASSWORD_VALIDATORS=[{"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 12}},
                                  {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
                                  {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"}],
        ACCOUNT_ADAPTER="wainak_identity.adapters.AccountAdapter",
        HEADLESS_ADAPTER="wainak_identity.adapters.HeadlessAdapter",
        ACCOUNT_SIGNUP_FORM_CLASS="wainak_identity.forms.EligibilityForm",
        ACCOUNT_USER_MODEL_USERNAME_FIELD=None, ACCOUNT_LOGIN_METHODS={"email"},
        ACCOUNT_SIGNUP_FIELDS=["email*", "password1*"], ACCOUNT_UNIQUE_EMAIL=True,
        ACCOUNT_EMAIL_VERIFICATION="mandatory", ACCOUNT_EMAIL_VERIFICATION_BY_CODE_ENABLED=True,
        ACCOUNT_EMAIL_VERIFICATION_BY_CODE_TIMEOUT=600, ACCOUNT_EMAIL_VERIFICATION_BY_CODE_MAX_ATTEMPTS=5,
        ACCOUNT_EMAIL_VERIFICATION_SUPPORTS_RESEND=3, ACCOUNT_EMAIL_VERIFICATION_SUPPORTS_CHANGE=False,
        ACCOUNT_PREVENT_ENUMERATION=True, ACCOUNT_LOGIN_ON_EMAIL_CONFIRMATION=True,
        ACCOUNT_LOGIN_ON_PASSWORD_RESET=False, ACCOUNT_LOGOUT_ON_PASSWORD_CHANGE=True,
        ACCOUNT_PASSWORD_RESET_BY_CODE_ENABLED=False, PASSWORD_RESET_TIMEOUT=600,
        ACCOUNT_RATE_LIMITS=False,  # Replaced by the atomic database boundary; never a local cache.
        HEADLESS_ONLY=True, HEADLESS_CLIENTS=("app",), HEADLESS_SERVE_SPECIFICATION=False,
        HEADLESS_FRONTEND_URLS={"account_confirm_email": "https://example.invalid/verify/{key}",
                               "account_reset_password": "https://example.invalid/reset",
                               "account_reset_password_from_key": "https://example.invalid/reset/{key}",
                               "account_signup": "https://example.invalid/signup"},
        LOGGING={"version": 1, "disable_existing_loggers": True,
                 "handlers": {"null": {"class": "logging.NullHandler"}},
                 "root": {"handlers": ["null"], "level": "CRITICAL"}},
    )
    import django
    django.setup()

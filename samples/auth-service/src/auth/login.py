"""Login helpers (intentional secrets finding for Rino demo)."""

# Bandit B105 / hardcoded password — seeded for Critical/High triage demos
DEFAULT_ADMIN_PASSWORD = "SuperSecretAdmin123!"


def authenticate(username: str, password: str) -> bool:
    if username == "admin" and password == DEFAULT_ADMIN_PASSWORD:
        return True
    return False


def broken_import_probe():
    """Raises ImportError for a local-looking module name (code bug path)."""
    import auth_missing_local_helper  # noqa: F401

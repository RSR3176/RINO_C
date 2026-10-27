from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://rino:rino@localhost:5432/rino"
    redis_url: str = "redis://localhost:6379/0"

    frontend_url: str = "http://localhost:3000"
    backend_url: str = "http://localhost:8000"

    session_secret: str = "change-me-to-a-long-random-string"
    cookie_secure: bool = False
    cookie_samesite: str = "lax"
    session_cookie_name: str = "rino_session"
    session_max_age_seconds: int = 60 * 60 * 24 * 14

    github_client_id: str = ""
    github_client_secret: str = ""

    # GitHub App (Repository Setup / install)
    github_app_id: str = ""
    github_app_slug: str = ""
    github_app_client_id: str = ""
    github_app_client_secret: str = ""
    # PEM contents (use \n for newlines) OR path via github_app_private_key_path
    github_app_private_key: str = ""
    github_app_private_key_path: str = ""
    github_app_webhook_secret: str = ""

    bootstrap_admin_github_usernames: str = ""
    default_org_name: str = "Rino"
    default_org_slug: str = "rino"

    # --- LLM (Step 5: root-cause only; never sets severity/actions) ---
    anthropic_api_key: str = ""
    llm_model: str = "claude-sonnet-4-20250514"
    # USD per million tokens (override if pricing changes)
    llm_input_cost_per_mtok: float = 3.0
    llm_output_cost_per_mtok: float = 15.0
    # When true (default), confirm-issue works without GitHub App via dry-run URLs
    github_issue_dry_run: bool = True
    # When true (default), Approve & Open Draft PR records dry-run:// without push
    github_pr_dry_run: bool = True
    # When true (default), GitHubActionsRunner uses fixture JUnit (no live dispatch)
    github_actions_dry_run: bool = True

    def anthropic_configured(self) -> bool:
        return bool(self.anthropic_api_key.strip())

    @property
    def bootstrap_admins(self) -> set[str]:
        return {
            name.strip().lower()
            for name in self.bootstrap_admin_github_usernames.split(",")
            if name.strip()
        }

    def github_app_configured(self) -> bool:
        return bool(self.github_app_id and self.resolve_github_app_private_key())

    def resolve_github_app_private_key(self) -> str:
        if self.github_app_private_key.strip():
            return self.github_app_private_key.replace("\\n", "\n").strip()
        if self.github_app_private_key_path.strip():
            with open(self.github_app_private_key_path, encoding="utf-8") as fh:
                return fh.read().strip()
        return ""

    def github_app_install_url(self, state: str | None = None) -> str:
        slug = self.github_app_slug.strip()
        if not slug:
            raise ValueError("GITHUB_APP_SLUG is not configured")
        base = f"https://github.com/apps/{slug}/installations/new"
        if state:
            from urllib.parse import urlencode

            return f"{base}?{urlencode({'state': state})}"
        return base


@lru_cache
def get_settings() -> Settings:
    return Settings()

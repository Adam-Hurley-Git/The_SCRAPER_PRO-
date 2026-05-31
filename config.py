from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class AppSettings:
    app_host: str = os.getenv("APP_HOST", "127.0.0.1")
    app_port: int = int(os.getenv("APP_PORT", "3000"))
    scraper_db_path: Path = Path(os.getenv("SCRAPER_DB_PATH", "./data/scraper.db"))
    export_dir: Path = Path(os.getenv("EXPORT_DIR", "./data/exports"))
    gosom_base_url: str = os.getenv("GOSOM_BASE_URL", "http://localhost:8080/api/v1")
    groq_api_key: str = os.getenv("GROQ_API_KEY", "")
    companies_house_api_key: str = os.getenv("COMPANIES_HOUSE_API_KEY", "")

    def validate_phase2_env(self) -> None:
        missing = []
        if not self.groq_api_key:
            missing.append("GROQ_API_KEY")
        if not self.companies_house_api_key:
            missing.append("COMPANIES_HOUSE_API_KEY")
        if missing:
            joined = ", ".join(missing)
            raise RuntimeError(f"Missing required Phase 2 env vars: {joined}")


def get_settings() -> AppSettings:
    return AppSettings()

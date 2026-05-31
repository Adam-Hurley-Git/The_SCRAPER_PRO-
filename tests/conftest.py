from __future__ import annotations

from pathlib import Path

import pytest

from database import init_db


@pytest.fixture()
def temp_db(tmp_path: Path) -> Path:
    db_path = tmp_path / "test_scraper.db"
    init_db(db_path)
    return db_path

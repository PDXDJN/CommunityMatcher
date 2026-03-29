from __future__ import annotations
import os
from pathlib import Path
from pydantic import BaseModel

# Load .env files if present (project root, then community_collector/).
# This ensures FEATHERLESS_API / CM_LLM_* vars are available before any
# module reads os.getenv at import time.
try:
    from dotenv import load_dotenv
    _root = Path(__file__).parent.parent.parent
    load_dotenv(_root / ".env", override=False)
    load_dotenv(_root / "community_collector" / ".env", override=False)
except ImportError:
    pass

# Canonical SQLite path — shared by the DB connection layer and the live collector.
# Override with CM_SQLITE_DB_PATH if the database lives elsewhere.
_DEFAULT_SQLITE_DB = str(
    Path(__file__).parent.parent.parent
    / "community_collector" / "output" / "communitymatcher.db"
)


class Settings(BaseModel):
    model_id: str = "claude-sonnet-4-6"
    use_bedrock: bool = False
    anthropic_api_key: str = ""
    database_url: str = ""  # postgresql://user:pass@host:5432/dbname
    sqlite_db_path: str = _DEFAULT_SQLITE_DB  # overridable via CM_SQLITE_DB_PATH
    log_level: str = "INFO"
    max_questions_per_turn: int = 3
    sufficiency_threshold: float = 0.6

    # Scoring weights (CLAUDE.md formula)
    weight_interest_alignment: float = 0.25
    weight_vibe_alignment: float = 0.20
    weight_newcomer_friendliness: float = 0.15
    weight_logistics_fit: float = 0.10
    weight_language_fit: float = 0.10
    weight_values_fit: float = 0.10
    weight_recurrence_strength: float = 0.05
    weight_risk_sanity: float = 0.05

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            model_id=os.getenv("MODEL_ID", "claude-sonnet-4-6"),
            use_bedrock=os.getenv("USE_BEDROCK", "false").lower() == "true",
            anthropic_api_key=os.getenv("ANTHROPIC_API_KEY", ""),
            database_url=os.getenv("DATABASE_URL", ""),
            sqlite_db_path=os.getenv("CM_SQLITE_DB_PATH", _DEFAULT_SQLITE_DB),
            log_level=os.getenv("LOG_LEVEL", "INFO"),
        )


settings = Settings.from_env()

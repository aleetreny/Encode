import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


@dataclass
class Settings:
    data_dir: Path = field(
        default_factory=lambda: Path(os.getenv("GRIDPILOT_DATA_DIR", ROOT / "data"))
    )
    db_path: Path = field(
        default_factory=lambda: Path(os.getenv("GRIDPILOT_DB_PATH", ROOT / "var/runs.sqlite3"))
    )
    public_origin: str = field(
        default_factory=lambda: os.getenv("PUBLIC_ORIGIN", "https://andes-a38.pages.dev").rstrip("/")
    )
    cors_origins: list[str] = field(
        default_factory=lambda: [
            o.strip()
            for o in os.getenv(
                "CORS_ORIGINS",
                "https://andes-a38.pages.dev,http://localhost:5173,http://127.0.0.1:5173",
            ).split(",")
            if o.strip()
        ]
    )
    api_token: str = field(default_factory=lambda: os.getenv("GRIDPILOT_API_TOKEN", ""))
    agent_callable: str = field(
        default_factory=lambda: os.getenv("GRIDPILOT_AGENT_CALLABLE", "agent:run_investigation")
    )
    solve_callable: str = field(
        default_factory=lambda: os.getenv("GRIDPILOT_SOLVE_CALLABLE", "backend.p3_adapter:solve")
    )
    validate_callable: str = field(
        default_factory=lambda: os.getenv(
            "GRIDPILOT_VALIDATE_CALLABLE", "backend.p3_adapter:validate"
        )
    )
    timeout_seconds: float = field(
        default_factory=lambda: float(os.getenv("GRIDPILOT_TIMEOUT_SECONDS", "90"))
    )
    queue_limit: int = 8
    worker_enabled: bool = True

    def __post_init__(self):
        if os.getenv("GRIDPILOT_ENV") == "production" and len(self.api_token) < 24:
            raise ValueError("production requires GRIDPILOT_API_TOKEN of at least 24 characters")
        if self.timeout_seconds <= 0 or self.queue_limit < 1:
            raise ValueError("invalid resource limits")

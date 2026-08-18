from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    host: str = "127.0.0.1"
    port: int = 8080
    database_path: Path = Path("spurline.sqlite3")
    verify_signatures: bool = True
    public_url: str | None = None

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            host=os.getenv("SPURLINE_HOST", "127.0.0.1"),
            port=int(os.getenv("SPURLINE_PORT", "8080")),
            database_path=Path(os.getenv("SPURLINE_DATABASE", "spurline.sqlite3")),
            verify_signatures=_env_bool("SPURLINE_VERIFY_SIGNATURES", default=True),
            public_url=os.getenv("SPURLINE_PUBLIC_URL") or None,
        )


def _env_bool(name: str, *, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.lower() not in {"0", "false", "no", "off"}

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from .identity import fips_ipv6_address, service_npub

SERVICE_MANAGEMENT_MODES = {"independent", "mainstay-managed"}


@dataclass(frozen=True)
class Settings:
    host: str = "127.0.0.1"
    port: int = 8080
    database_path: Path = Path("spurline.sqlite3")
    verify_signatures: bool = True
    public_url: str | None = None
    service_nsec: str | None = None
    service_management: str = "independent"
    witness_enabled: bool = False
    witness_clock_file: Path | None = None
    witness_queue_limit: int = 1000
    witness_max_delay_seconds: int = 60

    def __post_init__(self) -> None:
        if self.witness_enabled and (not self.service_nsec or not self.witness_clock_file):
            raise ValueError("witnessing requires a service key and SPURLINE_WITNESS_CLOCK_FILE")
        if self.witness_queue_limit < 1 or self.witness_max_delay_seconds < 1:
            raise ValueError("witness queue and delay limits must be positive")
        if self.service_management not in SERVICE_MANAGEMENT_MODES:
            raise ValueError("unsupported Spurline service management mode")
        if self.service_management == "mainstay-managed" and not self.service_nsec:
            raise ValueError("mainstay-managed Spurline requires SPURLINE_SERVICE_NSEC")
        if self.service_nsec:
            service_npub(self.service_nsec)

    @property
    def service_npub(self) -> str | None:
        return service_npub(self.service_nsec) if self.service_nsec else None

    @property
    def service_fips_ipv6_address(self) -> str | None:
        return fips_ipv6_address(self.service_npub) if self.service_npub else None

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            witness_enabled=_env_bool("SPURLINE_WITNESS_ENABLED", default=False),
            witness_clock_file=Path(os.environ["SPURLINE_WITNESS_CLOCK_FILE"]) if os.getenv("SPURLINE_WITNESS_CLOCK_FILE") else None,
            witness_queue_limit=int(os.getenv("SPURLINE_WITNESS_QUEUE_LIMIT", "1000")),
            witness_max_delay_seconds=int(os.getenv("SPURLINE_WITNESS_MAX_DELAY_SECONDS", "60")),
            host=os.getenv("SPURLINE_HOST", "127.0.0.1"),
            port=int(os.getenv("SPURLINE_PORT", "8080")),
            database_path=Path(os.getenv("SPURLINE_DATABASE", "spurline.sqlite3")),
            verify_signatures=_env_bool("SPURLINE_VERIFY_SIGNATURES", default=True),
            public_url=os.getenv("SPURLINE_PUBLIC_URL") or None,
            service_nsec=os.getenv("SPURLINE_SERVICE_NSEC") or None,
            service_management=os.getenv(
                "SPURLINE_SERVICE_MANAGEMENT", "independent"
            ),
        )


def _env_bool(name: str, *, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.lower() not in {"0", "false", "no", "off"}

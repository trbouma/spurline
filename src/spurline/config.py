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

    def __post_init__(self) -> None:
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

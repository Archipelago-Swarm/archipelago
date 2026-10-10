"""Read-only Vultr API v2 client. The API key is read only from VULTR_API_KEY and never surfaces."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

DEFAULT_BASE_URL = "https://api.vultr.com/v2"
KEY_ENV = "VULTR_API_KEY"
_LOOPBACK = {"127.0.0.1", "localhost", "::1"}


class VultrError(Exception):
    """Message never contains the key, request headers or response bodies."""


@dataclass(frozen=True)
class Plan:
    id: str
    monthly_cost: Decimal
    vcpu: int
    ram_mb: int


class VultrClient:
    """GET-only. Methods: account, instances, plans, regions."""

    def __init__(self, api_key: str, base_url: str = DEFAULT_BASE_URL, timeout: float = 20.0):
        if not api_key:
            raise VultrError(f"{KEY_ENV} is empty")
        parts = urllib.parse.urlsplit(base_url)
        if parts.scheme != "https" and not (parts.scheme == "http" and parts.hostname in _LOOPBACK):
            raise VultrError("base_url must be https (http only for loopback tests)")
        self._key = api_key
        self._base = base_url.rstrip("/")
        self._timeout = timeout

    @classmethod
    def from_env(cls, base_url: str = DEFAULT_BASE_URL) -> VultrClient:
        key = os.environ.get(KEY_ENV, "")
        if not key:
            raise VultrError(f"{KEY_ENV} is not set in the environment")
        return cls(key, base_url)

    def __repr__(self) -> str:
        return f"VultrClient(base_url={self._base!r}, api_key=<redacted>)"

    __str__ = __repr__

    def _get(self, path: str, params: dict[str, str] | None = None) -> dict[str, Any]:
        url = f"{self._base}{path}"
        if params:
            url += "?" + urllib.parse.urlencode(params)
        req = urllib.request.Request(  # noqa: S310 - scheme validated in __init__
            url, headers={"Authorization": f"Bearer {self._key}", "Accept": "application/json"}
        )
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:  # noqa: S310
                data = json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            raise VultrError(f"Vultr API HTTP {e.code} for {path}") from None
        except (urllib.error.URLError, TimeoutError, OSError):
            raise VultrError(f"Vultr API unreachable for {path}") from None
        except ValueError:
            raise VultrError(f"Vultr API returned invalid JSON for {path}") from None
        if not isinstance(data, dict):
            raise VultrError(f"Vultr API returned unexpected shape for {path}")
        return data

    def _list(self, path: str, key: str) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        cursor = ""
        for _ in range(100):
            data = self._get(path, {"per_page": "500", **({"cursor": cursor} if cursor else {})})
            out.extend(data.get(key, []))
            cursor = ((data.get("meta") or {}).get("links") or {}).get("next") or ""
            if not cursor:
                return out
        raise VultrError(f"pagination did not terminate for {path}")

    def account(self) -> dict[str, Any]:
        acct = self._get("/account").get("account", {})
        return {
            "balance": str(acct.get("balance", 0)),
            "pending_charges": str(acct.get("pending_charges", 0)),
        }

    def instances(self) -> list[dict[str, Any]]:
        return [
            {k: i.get(k) for k in ("id", "label", "plan", "region", "status", "date_created")}
            for i in self._list("/instances", "instances")
        ]

    def plans(self) -> list[Plan]:
        return [
            Plan(
                id=str(p["id"]),
                monthly_cost=Decimal(str(p.get("monthly_cost", 0))),
                vcpu=int(p.get("vcpu_count", 0)),
                ram_mb=int(p.get("ram", 0)),
            )
            for p in self._list("/plans", "plans")
        ]

    def regions(self) -> list[dict[str, Any]]:
        return [
            {k: r.get(k) for k in ("id", "city", "country", "continent")}
            for r in self._list("/regions", "regions")
        ]


def build_inventory(client: VultrClient, now_iso: str) -> dict[str, Any]:
    """inventory.json content: account, instances, plan prices (strings, no secrets)."""
    return {
        "generated_at": now_iso,
        "account": client.account(),
        "instances": client.instances(),
        "plans": {
            p.id: {"monthly_cost": str(p.monthly_cost), "vcpu": p.vcpu, "ram_mb": p.ram_mb}
            for p in client.plans()
        },
        "regions": [r["id"] for r in client.regions()],
    }

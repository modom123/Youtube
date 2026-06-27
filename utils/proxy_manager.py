"""
Proxy Manager — per-account proxy rotation and health checking.
Supports HTTP/HTTPS/SOCKS5 proxies with automatic rotation.
"""
from __future__ import annotations
import random
import time
import requests
from dataclasses import dataclass
from typing import Optional


@dataclass
class ProxyEntry:
    url: str
    protocol: str = "http"
    username: Optional[str] = None
    password: Optional[str] = None
    assigned_account: Optional[str] = None
    last_used: float = 0.0
    fail_count: int = 0
    is_healthy: bool = True

    @property
    def full_url(self) -> str:
        if self.username and self.password:
            proto = self.protocol
            host = self.url.replace(f"{proto}://", "")
            return f"{proto}://{self.username}:{self.password}@{host}"
        return self.url

    def as_dict(self) -> dict:
        return {
            "http": self.full_url,
            "https": self.full_url,
        }


class ProxyPool:
    """Manages a pool of proxies with rotation and assignment."""

    def __init__(self, proxies: list[dict] = None):
        self._proxies: list[ProxyEntry] = []
        self._account_map: dict[str, ProxyEntry] = {}
        if proxies:
            for p in proxies:
                self.add_proxy(p)

    def add_proxy(self, proxy: dict) -> None:
        entry = ProxyEntry(
            url=proxy["url"],
            protocol=proxy.get("protocol", "http"),
            username=proxy.get("username"),
            password=proxy.get("password"),
        )
        self._proxies.append(entry)

    def remove_proxy(self, url: str) -> None:
        self._proxies = [p for p in self._proxies if p.url != url]
        self._account_map = {
            k: v for k, v in self._account_map.items() if v.url != url
        }

    @property
    def size(self) -> int:
        return len(self._proxies)

    @property
    def healthy_count(self) -> int:
        return sum(1 for p in self._proxies if p.is_healthy)

    def get_proxy(self, account_id: str = None) -> Optional[ProxyEntry]:
        if not self._proxies:
            return None

        if account_id and account_id in self._account_map:
            proxy = self._account_map[account_id]
            if proxy.is_healthy:
                proxy.last_used = time.time()
                return proxy

        healthy = [p for p in self._proxies if p.is_healthy]
        if not healthy:
            return None

        least_used = sorted(healthy, key=lambda p: p.last_used)
        proxy = least_used[0]
        proxy.last_used = time.time()

        if account_id:
            self._account_map[account_id] = proxy
            proxy.assigned_account = account_id

        return proxy

    def rotate_proxy(self, account_id: str) -> Optional[ProxyEntry]:
        current = self._account_map.pop(account_id, None)
        healthy = [p for p in self._proxies if p.is_healthy and p != current]
        if not healthy:
            return current
        proxy = random.choice(healthy)
        proxy.last_used = time.time()
        proxy.assigned_account = account_id
        self._account_map[account_id] = proxy
        return proxy

    def mark_failed(self, proxy: ProxyEntry, max_fails: int = 3) -> None:
        proxy.fail_count += 1
        if proxy.fail_count >= max_fails:
            proxy.is_healthy = False

    def mark_success(self, proxy: ProxyEntry) -> None:
        proxy.fail_count = 0
        proxy.is_healthy = True

    def health_check(self, timeout: int = 10) -> dict:
        results = {"total": len(self._proxies), "healthy": 0, "unhealthy": 0}
        for proxy in self._proxies:
            try:
                resp = requests.get(
                    "https://httpbin.org/ip",
                    proxies=proxy.as_dict(),
                    timeout=timeout,
                )
                if resp.ok:
                    proxy.is_healthy = True
                    proxy.fail_count = 0
                    results["healthy"] += 1
                else:
                    self.mark_failed(proxy)
                    results["unhealthy"] += 1
            except Exception:
                self.mark_failed(proxy)
                results["unhealthy"] += 1
        return results

    def get_stats(self) -> dict:
        return {
            "total": len(self._proxies),
            "healthy": sum(1 for p in self._proxies if p.is_healthy),
            "unhealthy": sum(1 for p in self._proxies if not p.is_healthy),
            "assigned": len(self._account_map),
            "proxies": [
                {
                    "url": p.url,
                    "healthy": p.is_healthy,
                    "fail_count": p.fail_count,
                    "assigned_to": p.assigned_account,
                }
                for p in self._proxies
            ],
        }

    def get_playwright_proxy(self, account_id: str = None) -> Optional[dict]:
        proxy = self.get_proxy(account_id)
        if not proxy:
            return None
        result = {"server": proxy.url}
        if proxy.username:
            result["username"] = proxy.username
        if proxy.password:
            result["password"] = proxy.password
        return result


_global_pool: Optional[ProxyPool] = None


def get_pool() -> ProxyPool:
    global _global_pool
    if _global_pool is None:
        _global_pool = ProxyPool()
    return _global_pool


def init_pool(proxies: list[dict]) -> ProxyPool:
    global _global_pool
    _global_pool = ProxyPool(proxies)
    return _global_pool

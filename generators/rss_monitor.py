"""
RSS / Content Monitor — trend detection from feeds.
Monitors RSS feeds and social content for trending topics in your niche.
Discovers high-engagement content for repost and engagement opportunities.
"""
from __future__ import annotations
import hashlib
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

import requests


@dataclass
class FeedItem:
    title: str
    url: str
    published: str
    summary: str = ""
    source: str = ""
    engagement_score: float = 0.0
    tags: list[str] = field(default_factory=list)

    @property
    def id(self) -> str:
        return hashlib.md5(self.url.encode()).hexdigest()[:12]


@dataclass
class Feed:
    url: str
    name: str
    category: str = "general"
    last_fetched: Optional[str] = None
    is_active: bool = True


class RSSMonitor:
    """Monitors RSS feeds and extracts trending content."""

    def __init__(self):
        self._feeds: list[Feed] = []
        self._items_cache: dict[str, list[FeedItem]] = {}
        self._seen: set[str] = set()

    def add_feed(self, url: str, name: str = "", category: str = "general") -> Feed:
        feed = Feed(url=url, name=name or url, category=category)
        self._feeds.append(feed)
        return feed

    def remove_feed(self, url: str) -> None:
        self._feeds = [f for f in self._feeds if f.url != url]
        self._items_cache.pop(url, None)

    def list_feeds(self) -> list[dict]:
        return [
            {"url": f.url, "name": f.name, "category": f.category,
             "is_active": f.is_active, "last_fetched": f.last_fetched}
            for f in self._feeds
        ]

    def fetch_feed(self, feed: Feed, timeout: int = 15) -> list[FeedItem]:
        try:
            resp = requests.get(feed.url, timeout=timeout, headers={
                "User-Agent": "SocialOptimizeMachine/1.0 RSS Monitor",
            })
            resp.raise_for_status()
            items = self._parse_feed(resp.text, feed)
            feed.last_fetched = datetime.utcnow().isoformat()
            self._items_cache[feed.url] = items
            return items
        except Exception as e:
            print(f"[rss_monitor] Failed to fetch {feed.url}: {e}")
            return []

    def fetch_all(self) -> list[FeedItem]:
        all_items = []
        for feed in self._feeds:
            if not feed.is_active:
                continue
            items = self.fetch_feed(feed)
            all_items.extend(items)
        all_items.sort(key=lambda x: x.published, reverse=True)
        return all_items

    def get_new_items(self) -> list[FeedItem]:
        all_items = self.fetch_all()
        new_items = [item for item in all_items if item.id not in self._seen]
        for item in new_items:
            self._seen.add(item.id)
        return new_items

    def get_trending(self, min_score: float = 0.5, limit: int = 20) -> list[FeedItem]:
        all_items = []
        for items in self._items_cache.values():
            all_items.extend(items)
        trending = [i for i in all_items if i.engagement_score >= min_score]
        trending.sort(key=lambda x: x.engagement_score, reverse=True)
        return trending[:limit]

    def search_items(self, keyword: str) -> list[FeedItem]:
        keyword_lower = keyword.lower()
        results = []
        for items in self._items_cache.values():
            for item in items:
                if keyword_lower in item.title.lower() or keyword_lower in item.summary.lower():
                    results.append(item)
        return results

    def _parse_feed(self, xml_text: str, feed: Feed) -> list[FeedItem]:
        items = []
        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError:
            return items

        ns = {
            "atom": "http://www.w3.org/2005/Atom",
            "media": "http://search.yahoo.com/mrss/",
            "dc": "http://purl.org/dc/elements/1.1/",
        }

        # RSS 2.0
        for item_el in root.findall(".//item"):
            items.append(self._parse_rss_item(item_el, feed))

        # Atom
        for entry_el in root.findall(".//atom:entry", ns):
            items.append(self._parse_atom_entry(entry_el, ns, feed))

        if not items:
            for entry_el in root.findall(".//{http://www.w3.org/2005/Atom}entry"):
                items.append(self._parse_atom_entry_ns(entry_el, feed))

        return [i for i in items if i.url]

    def _parse_rss_item(self, el, feed: Feed) -> FeedItem:
        title = (el.findtext("title") or "").strip()
        link = (el.findtext("link") or "").strip()
        pub_date = (el.findtext("pubDate") or el.findtext("dc:date") or "").strip()
        desc = (el.findtext("description") or "").strip()
        desc = re.sub(r"<[^>]+>", "", desc)[:500]

        categories = [c.text for c in el.findall("category") if c.text]

        return FeedItem(
            title=title, url=link, published=pub_date,
            summary=desc, source=feed.name, tags=categories,
        )

    def _parse_atom_entry(self, el, ns: dict, feed: Feed) -> FeedItem:
        title = (el.findtext("atom:title", namespaces=ns) or "").strip()
        link_el = el.find("atom:link[@rel='alternate']", ns)
        if link_el is None:
            link_el = el.find("atom:link", ns)
        link = link_el.get("href", "") if link_el is not None else ""
        pub = (el.findtext("atom:published", namespaces=ns)
               or el.findtext("atom:updated", namespaces=ns) or "").strip()
        summary = (el.findtext("atom:summary", namespaces=ns) or "").strip()
        summary = re.sub(r"<[^>]+>", "", summary)[:500]

        return FeedItem(
            title=title, url=link, published=pub,
            summary=summary, source=feed.name,
        )

    def _parse_atom_entry_ns(self, el, feed: Feed) -> FeedItem:
        ns = "{http://www.w3.org/2005/Atom}"
        title = (el.findtext(f"{ns}title") or "").strip()
        link_el = el.find(f"{ns}link[@rel='alternate']")
        if link_el is None:
            link_el = el.find(f"{ns}link")
        link = link_el.get("href", "") if link_el is not None else ""
        pub = (el.findtext(f"{ns}published") or el.findtext(f"{ns}updated") or "").strip()
        summary = (el.findtext(f"{ns}summary") or "").strip()
        summary = re.sub(r"<[^>]+>", "", summary)[:500]

        return FeedItem(
            title=title, url=link, published=pub,
            summary=summary, source=feed.name,
        )


DEFAULT_TECH_FEEDS = [
    ("https://feeds.feedburner.com/TechCrunch/", "TechCrunch", "tech"),
    ("https://www.theverge.com/rss/index.xml", "The Verge", "tech"),
    ("https://hnrss.org/frontpage", "Hacker News", "tech"),
    ("https://www.reddit.com/r/technology/.rss", "r/technology", "tech"),
]

DEFAULT_MARKETING_FEEDS = [
    ("https://blog.hubspot.com/marketing/rss.xml", "HubSpot", "marketing"),
    ("https://feeds.feedburner.com/socialmediaexaminer", "Social Media Examiner", "marketing"),
    ("https://www.socialmediatoday.com/feed/", "Social Media Today", "marketing"),
]


def create_niche_monitor(niche: str) -> RSSMonitor:
    """Create a monitor pre-loaded with feeds for a niche."""
    monitor = RSSMonitor()
    niche_lower = niche.lower()

    if any(kw in niche_lower for kw in ["tech", "ai", "software", "programming"]):
        for url, name, cat in DEFAULT_TECH_FEEDS:
            monitor.add_feed(url, name, cat)
    if any(kw in niche_lower for kw in ["marketing", "social", "content", "growth"]):
        for url, name, cat in DEFAULT_MARKETING_FEEDS:
            monitor.add_feed(url, name, cat)

    if not monitor._feeds:
        monitor.add_feed(
            f"https://www.reddit.com/r/{niche.replace(' ', '')}/.rss",
            f"r/{niche}", "niche",
        )

    return monitor

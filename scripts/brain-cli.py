#!/usr/bin/env python3
"""
curated-brain — Structured agent knowledge base CLI.
Manages a catalog of facts with provenance and confidence.
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import sys
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import List, Optional


@dataclass
class Entry:
    id: str
    topic: str
    fact: str
    source: str
    confidence: float
    added_at: str
    last_verified: str
    deprecated: bool = False
    deprecation_reason: str = ""
    schema_version: str = "1.0"

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> Entry:
        return cls(**{k: v for k, v in d.items() if k in {f.name for f in cls.__dataclass_fields__.values()}})


class Catalog:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.entries: List[Entry] = []
        self.meta = {"schema_version": "1.0", "catalog_name": "", "description": "", "created_at": ""}
        self._load()

    def _load(self):
        if not self.path.exists():
            return
        data = json.loads(self.path.read_text(encoding="utf-8"))
        self.meta = {k: data.get(k, "") for k in self.meta}
        self.entries = [Entry.from_dict(e) for e in data.get("entries", [])]

    def _save(self):
        payload = {
            **self.meta,
            "entries": [e.to_dict() for e in self.entries],
        }
        self.path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def init(self, name: str, description: str = ""):
        self.meta["catalog_name"] = name
        self.meta["description"] = description
        self.meta["created_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        self.entries = []
        self._save()

    def add(self, topic: str, fact: str, source: str, confidence: float = 0.8) -> Entry:
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        entry = Entry(
            id=f"kb_{uuid.uuid4().hex[:8]}",
            topic=topic,
            fact=fact,
            source=source,
            confidence=max(0.0, min(1.0, confidence)),
            added_at=now,
            last_verified=now,
        )
        self.entries.append(entry)
        self._save()
        return entry

    def query(self, topic: str) -> List[Entry]:
        return [e for e in self.entries if not e.deprecated and e.topic.lower() == topic.lower()]

    def search(self, q: str) -> List[Entry]:
        qlower = q.lower()
        return [e for e in self.entries if not e.deprecated and (qlower in e.fact.lower() or qlower in e.topic.lower())]

    def recent(self, days: int = 7) -> List[Entry]:
        cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=days)
        return [e for e in self.entries if not e.deprecated and datetime.datetime.fromisoformat(e.added_at) >= cutoff]

    def audit(self, stale_days: int = 30, min_confidence: float = 0.0) -> List[Entry]:
        cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=stale_days)
        return [
            e for e in self.entries
            if not e.deprecated
            and (
                datetime.datetime.fromisoformat(e.last_verified) < cutoff
                or e.confidence < min_confidence
            )
        ]

    def deprecate(self, entry_id: str, reason: str) -> bool:
        for e in self.entries:
            if e.id == entry_id:
                e.deprecated = True
                e.deprecation_reason = reason
                self._save()
                return True
        return False


def get_default_catalog() -> Path:
    base = Path.home() / ".openclaw" / "skills" / "curated-brain"
    return base / "default-catalog.json"


def main() -> int:
    parser = argparse.ArgumentParser(description="curated-brain — agent knowledge base")
    parser.add_argument("--catalog", default=str(get_default_catalog()), help="Path to catalog JSON")
    sub = parser.add_subparsers(dest="command")

    p_init = sub.add_parser("init", help="Initialize a catalog")
    p_init.add_argument("--name", required=True)
    p_init.add_argument("--description", default="")

    p_add = sub.add_parser("add", help="Add an entry")
    p_add.add_argument("--topic", required=True)
    p_add.add_argument("--fact", required=True)
    p_add.add_argument("--source", required=True)
    p_add.add_argument("--confidence", type=float, default=0.8)

    p_query = sub.add_parser("query", help="Query by topic")
    p_query.add_argument("--topic", required=True)

    p_search = sub.add_parser("search", help="Full-text search")
    p_search.add_argument("--q", required=True)

    p_recent = sub.add_parser("recent", help="Recent entries")
    p_recent.add_argument("--days", type=int, default=7)

    p_audit = sub.add_parser("audit", help="Audit stale/low-confidence entries")
    p_audit.add_argument("--stale-days", type=int, default=30)
    p_audit.add_argument("--min-confidence", type=float, default=0.0)

    p_deprecate = sub.add_parser("deprecate", help="Deprecate an entry")
    p_deprecate.add_argument("--id", required=True)
    p_deprecate.add_argument("--reason", required=True)

    args = parser.parse_args()

    cat = Catalog(args.catalog)

    if args.command == "init":
        cat.init(args.name, args.description)
        print(f"Initialized catalog: {args.catalog}")
    elif args.command == "add":
        e = cat.add(args.topic, args.fact, args.source, args.confidence)
        print(f"Added entry {e.id} to topic '{e.topic}'")
    elif args.command == "query":
        results = cat.query(args.topic)
        if not results:
            print("No entries found.")
        for r in results:
            print(f"[{r.id}] ({r.confidence}) {r.fact} [src: {r.source}]")
    elif args.command == "search":
        results = cat.search(args.q)
        if not results:
            print("No matches.")
        for r in results:
            print(f"[{r.id}] {r.topic}: {r.fact}")
    elif args.command == "recent":
        results = cat.recent(args.days)
        if not results:
            print("No recent entries.")
        for r in results:
            print(f"[{r.added_at}] {r.topic}: {r.fact}")
    elif args.command == "audit":
        results = cat.audit(args.stale_days, args.min_confidence)
        if not results:
            print("No issues found.")
        for r in results:
            status = "stale" if r.confidence >= args.min_confidence else "low-confidence"
            print(f"[{status}] {r.id} ({r.confidence}) {r.topic}: {r.fact}")
    elif args.command == "deprecate":
        if cat.deprecate(args.id, args.reason):
            print(f"Deprecated entry {args.id}")
        else:
            print(f"Entry {args.id} not found")
            return 1
    else:
        parser.print_help()
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

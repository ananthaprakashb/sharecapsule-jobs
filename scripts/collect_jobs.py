#!/usr/bin/env python3
"""Collect and validate jobs from official employer/ATS sources.

Only records whose application URL belongs to an allow-listed official domain are
published. Greenhouse and Lever feeds produce individual openings. Official-search
sources are retained as verified employer searches when no public job feed exists.
"""
from __future__ import annotations

import json
import re
import sys
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SOURCES = ROOT / "sources.json"
OUT = ROOT / "data" / "jobs.json"
UA = "ShareCapsuleJobs/1.0 (+https://jobs.sharecapsule.app/)"

ROLE_PATTERNS = {
    "engineering": re.compile(r"software|engineer|developer|data|machine learning|artificial intelligence|\bai\b|cloud|devops|sre|security|architect|qa|test|product|program|technical|network|systems", re.I),
    "truck": re.compile(r"truck|driver|cdl|tractor|linehaul|line haul|delivery driver|route driver|transport driver", re.I),
    "warehouse": re.compile(r"warehouse|fulfillment|package handler|material handler|forklift|inventory|shipping|receiving|order selector|loader|distribution", re.I),
    "chef": re.compile(r"chef|cook|culinary|kitchen|baker|bakery|pastry|food prep|dishwasher|steward|banquet", re.I),
    "india-engineering": re.compile(r"software|engineer|developer|data|machine learning|artificial intelligence|\bai\b|cloud|devops|sre|security|architect|qa|test|product|technical|network|systems", re.I),
    "india-management": re.compile(r"manager|management|operations|program|project|product|finance|risk|sales|marketing|human resources|\bhr\b|consulting|strategy|business|category|supply chain", re.I),
}


def fetch_json(url: str) -> Any:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=35) as r:
        return json.load(r)


def validate_url(url: str, allowed_domains: list[str]) -> bool:
    try:
        p = urllib.parse.urlparse(url)
        host = (p.hostname or "").lower()
        if p.scheme != "https" or not host:
            return False
        return any(host == d or host.endswith("." + d) for d in allowed_domains)
    except Exception:
        return False


def classify(title: str, location: str, requested: list[str]) -> list[str]:
    text = f"{title} {location}"
    result = []
    for cat in requested:
        pat = ROLE_PATTERNS.get(cat)
        if pat and pat.search(text):
            result.append(cat)
    return result


def greenhouse(source: dict[str, Any]) -> list[dict[str, Any]]:
    board = source["board"]
    data = fetch_json(f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs?content=true")
    rows = []
    for j in data.get("jobs", []):
        title = str(j.get("title", "")).strip()
        location = str((j.get("location") or {}).get("name", "")).strip()
        url = str(j.get("absolute_url", "")).strip()
        cats = classify(title, location, source["categories"])
        if not cats or not validate_url(url, source["allowedDomains"]):
            continue
        rows.append({
            "id": f"{source['id']}:{j.get('id')}", "title": title,
            "company": source["company"], "location": location,
            "url": url, "categories": cats, "country": source.get("country", "US"),
            "source": source["id"], "sourceType": "official-ats",
            "updatedAt": j.get("updated_at"),
        })
    return rows


def lever(source: dict[str, Any]) -> list[dict[str, Any]]:
    site = source["site"]
    data = fetch_json(f"https://api.lever.co/v0/postings/{site}?mode=json")
    rows = []
    for j in data:
        title = str(j.get("text", "")).strip()
        location = str((j.get("categories") or {}).get("location", "")).strip()
        url = str(j.get("hostedUrl", "")).strip()
        cats = classify(title, location, source["categories"])
        if not cats or not validate_url(url, source["allowedDomains"]):
            continue
        rows.append({
            "id": f"{source['id']}:{j.get('id')}", "title": title,
            "company": source["company"], "location": location,
            "url": url, "categories": cats, "country": source.get("country", "US"),
            "source": source["id"], "sourceType": "official-ats",
            "updatedAt": j.get("createdAt"),
        })
    return rows


def official_search(source: dict[str, Any]) -> list[dict[str, Any]]:
    url = source["url"]
    if not validate_url(url, source["allowedDomains"]):
        return []
    return [{
        "id": f"search:{source['id']}", "title": source["title"],
        "company": source["company"], "location": source.get("location", "United States"),
        "url": url, "categories": source["categories"], "country": source.get("country", "US"),
        "source": source["id"], "sourceType": "official-search",
        "summary": source.get("summary", "Search current openings on the employer's official careers site."),
        "updatedAt": datetime.now(timezone.utc).isoformat(),
    }]


def main() -> int:
    config = json.loads(SOURCES.read_text(encoding="utf-8"))
    jobs: list[dict[str, Any]] = []
    report = []
    handlers = {"greenhouse": greenhouse, "lever": lever, "official-search": official_search}
    for source in config["sources"]:
        try:
            rows = handlers[source["type"]](source)
            jobs.extend(rows)
            report.append({"id": source["id"], "status": "passed", "count": len(rows)})
        except Exception as exc:
            report.append({"id": source["id"], "status": "failed", "count": 0, "error": str(exc)[:300]})
    dedup = {j["id"]: j for j in jobs}
    published = sorted(dedup.values(), key=lambda j: (j["categories"][0], j["company"], j["title"]))
    payload = {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "authenticityPolicy": "Official employer domains and official ATS feeds only; failed or non-allow-listed sources are excluded.",
        "total": len(published), "sources": report, "jobs": published,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Published {len(published)} verified records from {sum(r['status']=='passed' for r in report)} sources")
    return 0 if published else 1


if __name__ == "__main__":
    raise SystemExit(main())

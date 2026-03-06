# -*- coding: utf-8 -*-
"""
scripts/debug_params.py
=======================
Diagnostic: verify that GET /api/params reflects exactly what was POSTed.

Workflow
--------
1. GET current params — record baseline.
2. POST a known canary payload.
3. GET again — compare field by field against the canary.
4. Print a clear diff; exit 1 if any field mismatches.

Run while the server is up:

    python3 scripts/debug_params.py [--base-url http://127.0.0.1:8080]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import requests

# ---------------------------------------------------------------------------
# Canary payload — every field the UI can write
# ---------------------------------------------------------------------------

CANARY: dict = {
    "country":       "fr",
    "what":          "data engineer",
    "where":         "Paris",
    "distance":      25,
    "salary_min":    40000,
    "salary_max":    90000,
    "contract_type": "permanent",
    "category":      None,
    "sort_by":       "date",
    "max_pages":     2,
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get(base: str) -> dict:
    r = requests.get(f"{base}/api/params", timeout=5)
    r.raise_for_status()
    return r.json()


def _post(base: str, payload: dict) -> dict:
    r = requests.post(
        f"{base}/api/params",
        json=payload,
        headers={"Content-Type": "application/json"},
        timeout=5,
    )
    r.raise_for_status()
    return r.json()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="Debug POST→GET params round-trip.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8080")
    args = parser.parse_args()
    base = args.base_url.rstrip("/")

    print(f"Server : {base}")
    print("=" * 60)

    # 1. Baseline GET
    try:
        before = _get(base)
    except Exception as exc:
        print(f"[ERROR] GET /api/params failed: {exc}")
        return 1
    print("BEFORE (current params):")
    print(json.dumps({k: v for k, v in before.items() if not k.startswith("_")}, indent=2))
    print()

    # 2. POST canary
    print("POSTING canary payload:")
    print(json.dumps(CANARY, indent=2))
    print()
    try:
        post_response = _post(base, CANARY)
    except Exception as exc:
        print(f"[ERROR] POST /api/params failed: {exc}")
        return 1

    # 3. GET after POST
    try:
        after = _get(base)
    except Exception as exc:
        print(f"[ERROR] GET /api/params (after POST) failed: {exc}")
        return 1
    print("AFTER (server returned):")
    clean_after = {k: v for k, v in after.items() if not k.startswith("_")}
    print(json.dumps(clean_after, indent=2))
    print()

    # 4. Field-by-field diff
    print("DIFF (canary vs GET-after-POST):")
    print("-" * 60)
    failures = []
    all_keys = sorted(set(CANARY) | set(clean_after))

    for key in all_keys:
        sent     = CANARY.get(key, "<missing>")
        received = clean_after.get(key, "<missing>")
        match    = (sent == received)
        status   = "OK  " if match else "FAIL"
        print(f"  [{status}]  {key:<16}  sent={str(sent):<20}  got={received}")
        if not match:
            failures.append(key)

    print("-" * 60)
    if failures:
        print(f"\n[FAIL] {len(failures)} field(s) did not round-trip: {failures}")
        return 1

    print("\n[PASS] All fields round-tripped correctly.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

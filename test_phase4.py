#!/usr/bin/env python3
"""
test_phase4.py — Deployment readiness validation.

Checks:
  1. All modules import without error
  2. .env.example has all required keys
  3. SQLite DB initializes correctly
  4. DRY_RUN defaults to true
  5. deploy.sh and polybot.service exist

Run:
  python test_phase4.py
"""
from __future__ import annotations

import sys
from pathlib import Path

BASE = Path(__file__).parent


def test_all_imports() -> bool:
    print("\n[1/5] All modules import cleanly...")
    modules = [
        "config", "notifier", "sports_scanner", "edge_detector",
        "risk_manager", "stop_loss_monitor", "daily_report",
        "executor", "edge", "markets", "logger", "pipeline",
    ]
    failed = []
    for mod in modules:
        try:
            __import__(mod)
        except Exception as e:
            failed.append((mod, str(e)))

    if not failed:
        print(f"  PASS: all {len(modules)} modules imported")
        return True
    else:
        for mod, err in failed:
            print(f"  FAIL: {mod} -> {err}")
        return False


def test_env_example() -> bool:
    print("\n[2/5] .env.example has all required keys...")
    env_file = BASE / ".env.example"
    if not env_file.exists():
        print("  FAIL: .env.example not found")
        return False

    content = env_file.read_text()
    required = [
        "DRY_RUN", "POLYMARKET_API_KEY", "POLYMARKET_API_SECRET",
        "POLYMARKET_PRIVATE_KEY", "APISPORTS_KEY", "DISCORD_WEBHOOK_URL",
        "ANTHROPIC_API_KEY", "MAX_DAILY_TRADES", "EDGE_THRESHOLD",
        "STOP_LOSS_THRESHOLD", "KELLY_FRACTION", "MIN_MARKET_VOLUME",
    ]
    missing = [k for k in required if k not in content]
    if missing:
        print(f"  FAIL: missing keys: {missing}")
        return False

    print(f"  PASS: all {len(required)} required keys present")
    return True


def test_sqlite_init() -> bool:
    print("\n[3/5] SQLite DB initializes...")
    import logger as db_logger
    db_path = db_logger.DB_PATH
    if db_path.exists():
        print(f"  PASS: DB at {db_path} ({db_path.stat().st_size} bytes)")
        return True
    else:
        print(f"  FAIL: DB not created at {db_path}")
        return False


def test_dry_run_default() -> bool:
    print("\n[4/5] DRY_RUN defaults to true...")
    import config
    if config.DRY_RUN:
        print("  PASS: DRY_RUN=true (safe default)")
        return True
    else:
        print("  FAIL: DRY_RUN=false -- this is dangerous as default!")
        return False


def test_deploy_files() -> bool:
    print("\n[5/5] Deployment files exist...")
    files = {
        "deploy.sh": BASE / "deploy.sh",
        "polybot.service": BASE / "polybot.service",
        "run.py": BASE / "run.py",
        "requirements.txt": BASE / "requirements.txt",
    }
    missing = [name for name, path in files.items() if not path.exists()]
    if missing:
        print(f"  FAIL: missing files: {missing}")
        return False

    print(f"  PASS: all {len(files)} deployment files present")
    return True


def main() -> None:
    print("=" * 60)
    print("  PolyBot Phase 4 Deployment Readiness")
    print("=" * 60)

    results = [
        test_all_imports(),
        test_env_example(),
        test_sqlite_init(),
        test_dry_run_default(),
        test_deploy_files(),
    ]

    print("\n" + "=" * 60)
    passed = sum(results)
    total = len(results)
    if all(results):
        print(f"  ALL {total} CHECKS PASSED -- ready to deploy")
        sys.exit(0)
    else:
        print(f"  {passed}/{total} PASSED -- see failures above")
        sys.exit(1)


if __name__ == "__main__":
    main()

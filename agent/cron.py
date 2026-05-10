"""
Agent subsystem scheduled jobs
================================

Cron-style jobs registered with APScheduler in app.py. Each function is
defensive: any exception is logged but never bubbles, so a failed cron
won't kill the scheduler thread.

Jobs:
  audit_retention_cleanup_job   monthly (1st @ 03:30) — prune audit log
                                 entries older than AUDIT_RETENTION_DAYS

Env vars:
  AUDIT_RETENTION_DAYS   default 2555 (7 years). Healthcare/social
                         compliance default. Lower for cost-sensitive
                         non-regulated deployments.

Sprint X20.1 / Fix 4
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


def _retention_days() -> int:
    """Read retention from env each call so config changes apply without
    restart (within next cron firing)."""
    try:
        return max(1, int(os.environ.get('AUDIT_RETENTION_DAYS', '2555')))
    except (ValueError, TypeError):
        return 2555


def audit_retention_cleanup_job() -> None:
    """Prune agent_audit_log + agent_audit_access entries older than the
    configured retention. Self-logs to the audit log under actor='cron'.

    Designed to be APScheduler-safe: any exception is caught and logged,
    nothing bubbles. max_instances=1 + misfire_grace_time=3600 should be
    set in the registration site so a temporarily down dyno doesn't
    snowball cron firings.
    """
    try:
        from .audit import cleanup_old_entries, log_event
    except ImportError:
        logger.warning("[cron] audit module unavailable — skipping cleanup")
        return

    days = _retention_days()
    started = datetime.now(timezone.utc)
    logger.info(f"[cron] audit_retention_cleanup START (retention={days} days)")

    removed = 0
    error: str | None = None
    try:
        removed = cleanup_old_entries(retention_days=days) or 0
    except Exception as e:  # noqa: BLE001
        error = str(e)
        logger.error(f"[cron] audit_retention_cleanup FAILED: {e}")

    elapsed_s = (datetime.now(timezone.utc) - started).total_seconds()

    # Self-audit — append a `retention_cleanup` entry under user='system'.
    # This row will itself be eligible for cleanup in (retention) days.
    try:
        log_event(
            user_id='system',
            actor='cron',
            action='retention_cleanup',
            payload={
                'days': days,
                'removed': removed,
                'elapsed_s': round(elapsed_s, 3),
                'job': 'audit_retention_cleanup_job',
                'error': error,
            },
            severity='INFO' if error is None else 'WARNING',
        )
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[cron] audit self-log failed: {e}")

    if error is None:
        logger.info(f"[cron] audit_retention_cleanup OK — removed {removed} "
                    f"rows in {elapsed_s:.2f}s")
    return None


def federated_aggregation_job() -> None:
    """Sprint X20.7 — Weekly: rebuild agent_population_baselines for all
    persona cohorts. Drops cohorts with N < 5 (k-anonymity) and adds
    Laplace noise (ε=1.0 default) to numeric aggregates."""
    try:
        from .federated import aggregate_population_baselines, K_ANONYMITY_MIN, DEFAULT_EPSILON
    except ImportError:
        logger.warning("[cron] federated module unavailable — skipping aggregation")
        return

    started = datetime.now(timezone.utc)
    logger.info(f"[cron] federated_aggregation START "
                f"(K_min={K_ANONYMITY_MIN}, ε={DEFAULT_EPSILON})")
    upserted = 0
    error: str | None = None
    try:
        upserted = aggregate_population_baselines() or 0
    except Exception as e:  # noqa: BLE001
        error = str(e)
        logger.error(f"[cron] federated_aggregation FAILED: {e}")

    elapsed_s = (datetime.now(timezone.utc) - started).total_seconds()
    if error is None:
        logger.info(f"[cron] federated_aggregation OK — {upserted} rows "
                    f"upserted in {elapsed_s:.2f}s")

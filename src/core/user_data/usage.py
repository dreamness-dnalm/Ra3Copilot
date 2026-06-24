from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from core.user_data import user_data_path


USAGE_DB_PATH = Path(user_data_path) / "usage.sqlite3"
SCHEMA_VERSION = 1


@dataclass(frozen=True)
class TokenUsage:
    input_tokens: int = 0
    cached_input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    usage_known: bool = False

    def model_dump(self) -> dict:
        return {
            "input_tokens": self.input_tokens,
            "cached_input_tokens": self.cached_input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
            "usage_known": self.usage_known,
        }


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _day_from_iso(value: str) -> str:
    text = (value or "").strip()
    if not text:
        return _now_iso()[:10]
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        return datetime.fromisoformat(text).astimezone(timezone.utc).date().isoformat()
    except ValueError:
        return value[:10]


def _connect() -> sqlite3.Connection:
    USAGE_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(str(USAGE_DB_PATH))
    connection.row_factory = sqlite3.Row
    return connection


@contextmanager
def _open_connection():
    connection = _connect()
    try:
        yield connection
    finally:
        connection.close()


def _ensure_schema(connection: sqlite3.Connection) -> None:
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA user_version = 1")
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS usage_runs (
            run_id TEXT PRIMARY KEY,
            conversation_id TEXT NOT NULL,
            project_id TEXT NOT NULL,
            project_name TEXT NOT NULL,
            project_path TEXT NOT NULL,
            provider_name TEXT NOT NULL,
            model_name TEXT NOT NULL,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL,
            day TEXT NOT NULL,
            input_tokens INTEGER NOT NULL DEFAULT 0,
            cached_input_tokens INTEGER NOT NULL DEFAULT 0,
            output_tokens INTEGER NOT NULL DEFAULT 0,
            total_tokens INTEGER NOT NULL DEFAULT 0,
            usage_known INTEGER NOT NULL DEFAULT 0,
            cost REAL,
            currency TEXT NOT NULL DEFAULT 'CNY'
        )
        """
    )
    connection.execute("CREATE INDEX IF NOT EXISTS idx_usage_runs_day ON usage_runs(day)")
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_usage_runs_conversation ON usage_runs(conversation_id)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_usage_runs_project ON usage_runs(project_id)"
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_usage_runs_model
        ON usage_runs(provider_name, model_name)
        """
    )
    connection.commit()


def init_usage_db() -> None:
    with _open_connection() as connection:
        _ensure_schema(connection)


def _int_value(value: Any) -> int:
    try:
        return max(int(value or 0), 0)
    except (TypeError, ValueError):
        return 0


def _nested_int(mapping: dict, *keys: str) -> int:
    current: Any = mapping
    for key in keys:
        if not isinstance(current, dict):
            return 0
        current = current.get(key)
    return _int_value(current)


def normalize_token_usage(*candidates: Any) -> TokenUsage:
    for candidate in candidates:
        if not isinstance(candidate, dict) or not candidate:
            continue

        input_tokens = _int_value(
            candidate.get("input_tokens")
            or candidate.get("prompt_tokens")
            or candidate.get("input_token_count")
        )
        output_tokens = _int_value(
            candidate.get("output_tokens")
            or candidate.get("completion_tokens")
            or candidate.get("output_token_count")
        )
        total_tokens = _int_value(candidate.get("total_tokens") or candidate.get("total_token_count"))

        input_details = candidate.get("input_token_details") or candidate.get("prompt_tokens_details") or {}
        cached_input_tokens = _int_value(
            candidate.get("cached_input_tokens")
            or input_details.get("cache_read")
            or input_details.get("cached_tokens")
            or _nested_int(candidate, "input_tokens_details", "cached_tokens")
        )

        if not total_tokens and (input_tokens or output_tokens):
            total_tokens = input_tokens + output_tokens
        if input_tokens or output_tokens or total_tokens:
            return TokenUsage(
                input_tokens=input_tokens,
                cached_input_tokens=cached_input_tokens,
                output_tokens=output_tokens,
                total_tokens=total_tokens,
                usage_known=True,
            )

    return TokenUsage()


def usage_from_message(message) -> TokenUsage:
    usage_metadata = getattr(message, "usage_metadata", None)
    response_metadata = getattr(message, "response_metadata", None) or {}
    token_usage = response_metadata.get("token_usage") if isinstance(response_metadata, dict) else None
    return normalize_token_usage(usage_metadata, token_usage)


def merge_token_usage(current: TokenUsage, incoming: TokenUsage) -> TokenUsage:
    if not incoming.usage_known:
        return current
    if not current.usage_known:
        return incoming
    return TokenUsage(
        input_tokens=max(current.input_tokens, incoming.input_tokens),
        cached_input_tokens=max(current.cached_input_tokens, incoming.cached_input_tokens),
        output_tokens=max(current.output_tokens, incoming.output_tokens),
        total_tokens=max(current.total_tokens, incoming.total_tokens),
        usage_known=True,
    )


def calculate_cost(usage: TokenUsage, model_config) -> tuple[float | None, str]:
    currency = (getattr(model_config, "currency", None) or "CNY").upper()
    if currency not in {"CNY", "USD"}:
        currency = "CNY"
    if not usage.usage_known:
        return None, currency

    input_price = float(getattr(model_config, "input_price_per_million", 0) or 0)
    cached_input_price = float(getattr(model_config, "cached_input_price_per_million", 0) or 0)
    output_price = float(getattr(model_config, "output_price_per_million", 0) or 0)
    if not input_price and not cached_input_price and not output_price:
        return None, currency

    uncached_input = max(usage.input_tokens - usage.cached_input_tokens, 0)
    cost = (
        uncached_input * input_price
        + usage.cached_input_tokens * cached_input_price
        + usage.output_tokens * output_price
    ) / 1_000_000
    return round(cost, 8), currency


def record_usage_run(
    *,
    run_id: str,
    conversation_id: str,
    project,
    provider_name: str,
    model_name: str,
    status: str,
    usage: TokenUsage,
    cost: float | None,
    currency: str,
    created_at: str | None = None,
) -> dict:
    init_usage_db()
    created = created_at or _now_iso()
    project_data = project.model_dump() if hasattr(project, "model_dump") else dict(project or {})
    payload = {
        "run_id": run_id,
        "conversation_id": conversation_id,
        "project_id": str(project_data.get("id") or ""),
        "project_name": str(project_data.get("name") or ""),
        "project_path": str(project_data.get("path") or ""),
        "provider_name": provider_name or "",
        "model_name": model_name or "",
        "status": status,
        "created_at": created,
        "day": _day_from_iso(created),
        **usage.model_dump(),
        "usage_known": int(usage.usage_known),
        "cost": cost,
        "currency": (currency or "CNY").upper(),
    }

    with _open_connection() as connection:
        _ensure_schema(connection)
        connection.execute(
            """
            INSERT OR REPLACE INTO usage_runs (
                run_id, conversation_id, project_id, project_name, project_path,
                provider_name, model_name, status, created_at, day,
                input_tokens, cached_input_tokens, output_tokens, total_tokens,
                usage_known, cost, currency
            ) VALUES (
                :run_id, :conversation_id, :project_id, :project_name, :project_path,
                :provider_name, :model_name, :status, :created_at, :day,
                :input_tokens, :cached_input_tokens, :output_tokens, :total_tokens,
                :usage_known, :cost, :currency
            )
            """,
            payload,
        )
        connection.commit()
    payload["usage_known"] = bool(payload["usage_known"])
    return payload


def _costs_by_currency(rows: list[sqlite3.Row]) -> dict[str, float]:
    totals: dict[str, float] = {}
    for row in rows:
        currency = row["currency"] or "CNY"
        totals[currency] = round(totals.get(currency, 0) + float(row["cost"] or 0), 8)
    return totals


def _row_to_dict(row: sqlite3.Row) -> dict:
    data = dict(row)
    data["usage_known"] = bool(data.get("usage_known"))
    return data


def get_usage_summary(days: int = 365) -> dict:
    init_usage_db()
    days = max(int(days or 365), 1)
    start_day = (datetime.now(timezone.utc).date() - timedelta(days=days - 1)).isoformat()
    with _open_connection() as connection:
        _ensure_schema(connection)
        totals = connection.execute(
            """
            SELECT
                COUNT(*) AS run_count,
                SUM(CASE WHEN usage_known = 0 THEN 1 ELSE 0 END) AS unknown_run_count,
                SUM(input_tokens) AS input_tokens,
                SUM(cached_input_tokens) AS cached_input_tokens,
                SUM(output_tokens) AS output_tokens,
                SUM(total_tokens) AS total_tokens
            FROM usage_runs
            """
        ).fetchone()
        cost_rows = connection.execute(
            """
            SELECT currency, SUM(cost) AS cost
            FROM usage_runs
            WHERE cost IS NOT NULL
            GROUP BY currency
            """
        ).fetchall()
        daily_rows = connection.execute(
            """
            SELECT
                day,
                COUNT(*) AS run_count,
                SUM(CASE WHEN usage_known = 0 THEN 1 ELSE 0 END) AS unknown_run_count,
                SUM(input_tokens) AS input_tokens,
                SUM(cached_input_tokens) AS cached_input_tokens,
                SUM(output_tokens) AS output_tokens,
                SUM(total_tokens) AS total_tokens
            FROM usage_runs
            WHERE day >= ?
            GROUP BY day
            ORDER BY day
            """,
            (start_day,),
        ).fetchall()
        daily_cost_rows = connection.execute(
            """
            SELECT day, currency, SUM(cost) AS cost
            FROM usage_runs
            WHERE day >= ? AND cost IS NOT NULL
            GROUP BY day, currency
            """,
            (start_day,),
        ).fetchall()
        model_rows = connection.execute(
            """
            SELECT
                provider_name,
                model_name,
                currency,
                COUNT(*) AS run_count,
                SUM(input_tokens) AS input_tokens,
                SUM(cached_input_tokens) AS cached_input_tokens,
                SUM(output_tokens) AS output_tokens,
                SUM(total_tokens) AS total_tokens,
                SUM(cost) AS cost
            FROM usage_runs
            GROUP BY provider_name, model_name, currency
            ORDER BY total_tokens DESC
            """
        ).fetchall()

    daily_costs: dict[str, dict[str, float]] = {}
    for row in daily_cost_rows:
        daily_costs.setdefault(row["day"], {})[row["currency"] or "CNY"] = round(float(row["cost"] or 0), 8)

    return {
        "days": days,
        "startDay": start_day,
        "totals": {
            "run_count": _int_value(totals["run_count"] if totals else 0),
            "unknown_run_count": _int_value(totals["unknown_run_count"] if totals else 0),
            "input_tokens": _int_value(totals["input_tokens"] if totals else 0),
            "cached_input_tokens": _int_value(totals["cached_input_tokens"] if totals else 0),
            "output_tokens": _int_value(totals["output_tokens"] if totals else 0),
            "total_tokens": _int_value(totals["total_tokens"] if totals else 0),
            "costs": _costs_by_currency(cost_rows),
        },
        "daily": [
            {
                **_row_to_dict(row),
                "costs": daily_costs.get(row["day"], {}),
            }
            for row in daily_rows
        ],
        "byModel": [_row_to_dict(row) for row in model_rows],
    }


def get_conversation_usage(conversation_id: str) -> dict:
    init_usage_db()
    with _open_connection() as connection:
        _ensure_schema(connection)
        runs = connection.execute(
            """
            SELECT *
            FROM usage_runs
            WHERE conversation_id = ?
            ORDER BY created_at
            """,
            (conversation_id,),
        ).fetchall()
        cost_rows = connection.execute(
            """
            SELECT currency, SUM(cost) AS cost
            FROM usage_runs
            WHERE conversation_id = ? AND cost IS NOT NULL
            GROUP BY currency
            """,
            (conversation_id,),
        ).fetchall()

    run_dicts = [_row_to_dict(row) for row in runs]
    return {
        "conversation_id": conversation_id,
        "run_count": len(run_dicts),
        "unknown_run_count": sum(1 for run in run_dicts if not run["usage_known"]),
        "input_tokens": sum(run["input_tokens"] for run in run_dicts),
        "cached_input_tokens": sum(run["cached_input_tokens"] for run in run_dicts),
        "output_tokens": sum(run["output_tokens"] for run in run_dicts),
        "total_tokens": sum(run["total_tokens"] for run in run_dicts),
        "costs": _costs_by_currency(cost_rows),
        "runs": run_dicts,
    }

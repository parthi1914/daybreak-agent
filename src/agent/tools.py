"""The tools the agent can call while composing a brief.

Each tool is a plain function that returns JSON-serialisable data. The agent
core exposes them to Bedrock as a tool schema; Nova decides which to call and
with what arguments. Every tool is defensive: a failing data source degrades
the brief, it never fails the whole run.
"""
from __future__ import annotations

import datetime as dt
import json
import urllib.request
import urllib.error
import xml.etree.ElementTree as ET
from decimal import Decimal
from typing import Any

import boto3
from aws_lambda_powertools import Logger
from boto3.dynamodb.conditions import Key

from .config import RuntimeConfig

logger = Logger(child=True)
_dynamodb = boto3.resource("dynamodb")

# WMO weather interpretation codes -> short human labels.
_WMO = {
    0: "clear sky", 1: "mainly clear", 2: "partly cloudy", 3: "overcast",
    45: "fog", 48: "rime fog", 51: "light drizzle", 53: "drizzle",
    55: "heavy drizzle", 61: "light rain", 63: "rain", 65: "heavy rain",
    71: "light snow", 73: "snow", 75: "heavy snow", 80: "rain showers",
    81: "rain showers", 82: "violent rain showers", 95: "thunderstorm",
    96: "thunderstorm with hail", 99: "thunderstorm with heavy hail",
}


def _http_get_json(url: str, timeout: int) -> dict[str, Any]:
    req = urllib.request.Request(url, headers={"User-Agent": "DayBreakAgent/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 (trusted config URL)
        return json.loads(resp.read().decode("utf-8"))


def get_weather(cfg: RuntimeConfig) -> dict[str, Any]:
    """Today's forecast for the user's coordinates via Open-Meteo (no API key)."""
    p = cfg.profile
    url = (
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={p.latitude}&longitude={p.longitude}"
        "&daily=temperature_2m_max,temperature_2m_min,precipitation_probability_max,weather_code"
        "&current=temperature_2m,weather_code"
        f"&temperature_unit=fahrenheit&timezone={p.timezone.replace('/', '%2F')}&forecast_days=1"
    )
    try:
        data = _http_get_json(url, cfg.http_timeout_seconds)
        daily = data.get("daily", {})
        current = data.get("current", {})
        code = (daily.get("weather_code") or [current.get("weather_code", 0)])[0]
        return {
            "condition": _WMO.get(int(code), "unknown"),
            "high_f": (daily.get("temperature_2m_max") or [None])[0],
            "low_f": (daily.get("temperature_2m_min") or [None])[0],
            "current_f": current.get("temperature_2m"),
            "precip_chance_pct": (daily.get("precipitation_probability_max") or [None])[0],
        }
    except (urllib.error.URLError, ValueError, KeyError, TimeoutError) as exc:
        logger.warning("Weather lookup failed", extra={"error": str(exc)})
        return {"error": "weather unavailable"}


def _to_native(item: dict[str, Any]) -> dict[str, Any]:
    """DynamoDB returns Decimals; make them JSON-friendly."""
    out: dict[str, Any] = {}
    for k, v in item.items():
        out[k] = float(v) if isinstance(v, Decimal) else v
    return out


def get_tasks(cfg: RuntimeConfig) -> dict[str, Any]:
    """Open tasks for the user, surfacing overdue and due-today first."""
    table = _dynamodb.Table(cfg.tasks_table)
    today = cfg.run_date or dt.date.today().isoformat()
    try:
        resp = table.query(
            KeyConditionExpression=Key("userId").eq(cfg.profile.user_id),
        )
    except Exception as exc:  # noqa: BLE001 - table may be empty/unseeded
        logger.warning("Task query failed", extra={"error": str(exc)})
        return {"tasks": []}

    items = [_to_native(i) for i in resp.get("Items", []) if i.get("status", "open") == "open"]

    def sort_key(t: dict[str, Any]) -> tuple:
        due = t.get("dueDate", "9999-12-31")
        prio = {"high": 0, "medium": 1, "low": 2}.get(str(t.get("priority", "medium")).lower(), 1)
        return (due, prio)

    items.sort(key=sort_key)
    trimmed = items[: cfg.profile.max_tasks_in_brief]
    for t in trimmed:
        due = t.get("dueDate", "")
        t["state"] = "overdue" if due and due < today else ("due_today" if due == today else "upcoming")
    return {"tasks": trimmed, "today": today}


def get_stale_followups(cfg: RuntimeConfig) -> dict[str, Any]:
    """Open items untouched longer than the stale threshold, for nudge drafts."""
    table = _dynamodb.Table(cfg.tasks_table)
    base_date = dt.date.fromisoformat(cfg.run_date) if cfg.run_date else dt.date.today()
    cutoff = (base_date - dt.timedelta(days=cfg.profile.stale_after_days)).isoformat()
    try:
        resp = table.query(KeyConditionExpression=Key("userId").eq(cfg.profile.user_id))
    except Exception as exc:  # noqa: BLE001
        logger.warning("Stale query failed", extra={"error": str(exc)})
        return {"stale": []}

    stale = [
        _to_native(i)
        for i in resp.get("Items", [])
        if i.get("status", "open") == "open"
        and i.get("kind") == "thread"
        and str(i.get("updatedAt", "9999")) < cutoff
    ]
    return {"stale": stale, "cutoff": cutoff, "stale_after_days": cfg.profile.stale_after_days}


def get_headlines(cfg: RuntimeConfig) -> dict[str, Any]:
    """A few headlines from the configured RSS feed, if any."""
    if not cfg.profile.news_feed_url:
        return {"headlines": []}
    try:
        req = urllib.request.Request(
            cfg.profile.news_feed_url, headers={"User-Agent": "DayBreakAgent/1.0"}
        )
        with urllib.request.urlopen(req, timeout=cfg.http_timeout_seconds) as resp:  # noqa: S310
            xml = resp.read().decode("utf-8", errors="replace")
        root = ET.fromstring(xml)
        titles = [t.text.strip() for t in root.iter("title") if t.text and t.text.strip()]
        # First title on an RSS feed is usually the channel name; skip it.
        return {"headlines": titles[1:6] if len(titles) > 1 else titles[:5]}
    except (urllib.error.URLError, ET.ParseError, ValueError, TimeoutError) as exc:
        logger.warning("Headline fetch failed", extra={"error": str(exc)})
        return {"headlines": []}


# Registry mapping tool names (as exposed to Bedrock) to their implementations.
TOOL_IMPLS = {
    "get_weather": get_weather,
    "get_tasks": get_tasks,
    "get_stale_followups": get_stale_followups,
    "get_headlines": get_headlines,
}


def tool_config() -> dict[str, Any]:
    """The Bedrock Converse toolConfig block describing every tool."""
    empty = {"type": "object", "properties": {}, "required": []}
    return {
        "tools": [
            {
                "toolSpec": {
                    "name": "get_weather",
                    "description": "Get today's forecast (condition, high/low/current temp in F, precip chance) for the user's location.",
                    "inputSchema": {"json": empty},
                }
            },
            {
                "toolSpec": {
                    "name": "get_tasks",
                    "description": "Get the user's open tasks, already sorted with overdue and due-today first.",
                    "inputSchema": {"json": empty},
                }
            },
            {
                "toolSpec": {
                    "name": "get_stale_followups",
                    "description": "Get conversation threads that have gone quiet past the stale threshold and may need a nudge.",
                    "inputSchema": {"json": empty},
                }
            },
            {
                "toolSpec": {
                    "name": "get_headlines",
                    "description": "Get a handful of recent news headlines from the user's configured feed.",
                    "inputSchema": {"json": empty},
                }
            },
        ]
    }

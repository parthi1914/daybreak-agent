"""Configuration loading for the DayBreak agent.

Configuration is layered:
  1. A JSON document in SSM Parameter Store (source of truth, editable without redeploy).
  2. Environment variables (deploy-time defaults / infrastructure wiring).
  3. Hard-coded fallbacks (so the agent still runs before anything is seeded).

The SSM document lets an operator retune the agent (schedule copy, news feeds,
quiet hours, recipient) without a code deploy, which is the behaviour you want
for an always-on job you rarely touch.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

import boto3
from aws_lambda_powertools import Logger

logger = Logger(child=True)

_ssm = boto3.client("ssm")


@dataclass(frozen=True)
class UserProfile:
    """Everything the agent needs to know about the person it works for."""

    user_id: str
    name: str
    timezone: str
    latitude: float
    longitude: float
    recipient_email: str
    sender_email: str
    news_feed_url: str | None = None
    stale_after_days: int = 3
    max_tasks_in_brief: int = 6
    tone: str = "warm, concise, and encouraging"


@dataclass(frozen=True)
class RuntimeConfig:
    """Infrastructure wiring resolved from the environment."""

    model_id: str
    tasks_table: str
    briefs_table: str
    config_param: str
    metrics_namespace: str
    run_date: str | None = None
    max_agent_turns: int = 6
    http_timeout_seconds: int = 6
    profile: UserProfile = field(default=None)  # type: ignore[assignment]


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


@lru_cache(maxsize=1)
def _load_profile_document() -> dict[str, Any]:
    """Fetch the JSON profile from SSM once per warm container."""
    param_name = _env("CONFIG_PARAM", "/daybreak/config")
    try:
        resp = _ssm.get_parameter(Name=param_name, WithDecryption=True)
        doc = json.loads(resp["Parameter"]["Value"])
        logger.debug("Loaded profile from SSM", extra={"param": param_name})
        return doc
    except _ssm.exceptions.ParameterNotFound:
        logger.warning("Config parameter not found; using env fallbacks", extra={"param": param_name})
        return {}
    except (json.JSONDecodeError, KeyError) as exc:
        logger.exception("Malformed config parameter; using env fallbacks", extra={"error": str(exc)})
        return {}


def _build_profile(doc: dict[str, Any]) -> UserProfile:
    def pick(key: str, env: str, default: str = "") -> str:
        val = doc.get(key)
        return str(val) if val not in (None, "") else _env(env, default)

    return UserProfile(
        user_id=pick("user_id", "USER_ID", "default"),
        name=pick("name", "USER_NAME", "there"),
        timezone=pick("timezone", "TIMEZONE", "America/New_York"),
        latitude=float(pick("latitude", "LATITUDE", "33.749")),
        longitude=float(pick("longitude", "LONGITUDE", "-84.388")),
        recipient_email=pick("recipient_email", "RECIPIENT_EMAIL"),
        sender_email=pick("sender_email", "SENDER_EMAIL"),
        news_feed_url=(doc.get("news_feed_url") or _env("NEWS_FEED_URL")) or None,
        stale_after_days=int(doc.get("stale_after_days", _env("STALE_AFTER_DAYS", "3"))),
        max_tasks_in_brief=int(doc.get("max_tasks_in_brief", "6")),
        tone=str(doc.get("tone", "warm, concise, and encouraging")),
    )


def load_config() -> RuntimeConfig:
    """Assemble the full runtime configuration for one invocation."""
    profile = _build_profile(_load_profile_document())
    return RuntimeConfig(
        model_id=_env("MODEL_ID", "us.amazon.nova-lite-v1:0"),
        tasks_table=_env("TASKS_TABLE", "daybreak-tasks"),
        briefs_table=_env("BRIEFS_TABLE", "daybreak-briefs"),
        config_param=_env("CONFIG_PARAM", "/daybreak/config"),
        metrics_namespace=_env("POWERTOOLS_METRICS_NAMESPACE", "DayBreak"),
        max_agent_turns=int(_env("MAX_AGENT_TURNS", "6")),
        http_timeout_seconds=int(_env("HTTP_TIMEOUT_SECONDS", "6")),
        profile=profile,
    )


def reset_cache() -> None:
    """Testing hook to clear the memoised SSM document."""
    _load_profile_document.cache_clear()

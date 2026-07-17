"""The reasoning core: a Bedrock Converse tool-use loop.

This is what makes DayBreak an *agent* rather than a script. We hand Nova a set
of tools and a goal; Nova decides which tools to call, we execute them and feed
the results back, and it repeats until it has enough to compose the brief. A
final forced-JSON turn produces the structured payload the rest of the system
renders and stores.
"""
from __future__ import annotations

import datetime as dt
import json
import re
from dataclasses import replace
from typing import Any

import boto3
from aws_lambda_powertools import Logger
from aws_lambda_powertools.metrics import MetricUnit

from .config import RuntimeConfig
from .models import Brief
from .tools import TOOL_IMPLS, tool_config

logger = Logger(child=True)
_bedrock = boto3.client("bedrock-runtime")

SYSTEM_PROMPT = """You are DayBreak, a personal morning-brief agent. You run before the user wakes up and prepare a single, scannable brief for the day.

Rules:
- Use the tools to gather real data before writing anything. Call get_tasks and get_weather at minimum. Call get_stale_followups and get_headlines when they add value.
- Never invent tasks, meetings, weather, or headlines. If a tool returns nothing, leave that section empty.
- For each stale thread, write a short, ready-to-send follow-up draft the user could paste as-is.
- Be {tone}. Respect the user's time: no filler, no restating the obvious.
"""

# The final turn asks for exactly this shape. Kept in one place so the prompt
# and the parser can't drift apart.
BRIEF_SCHEMA_HINT = """Respond with ONLY a JSON object (no prose, no markdown fences) of this exact shape:
{
  "greeting": "one warm line addressing the user by name",
  "weather": "one sentence: condition, high/low, and whether to grab a jacket or umbrella",
  "priorities": [{"title": "...", "reason": "why it matters today", "due": "overdue|due today|<date>"}],
  "schedule": ["time - item", "..."],
  "follow_ups": [{"subject": "thread name", "draft": "a short ready-to-send message"}],
  "headlines": ["headline", "..."],
  "closing": "one encouraging line to start the day"
}
Include only sections you have real data for; use empty arrays otherwise."""


def _extract_json(text: str) -> dict[str, Any]:
    """Pull the JSON object out of the model's final message, tolerating fences."""
    text = text.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.DOTALL)
    if fenced:
        text = fenced.group(1)
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end != -1 and end > start:
        text = text[start : end + 1]
    return json.loads(text)


def _run_tool(name: str, cfg: RuntimeConfig, metrics) -> dict[str, Any]:
    impl = TOOL_IMPLS.get(name)
    if impl is None:
        return {"error": f"unknown tool {name}"}
    metrics.add_metric(name=f"tool.{name}", unit=MetricUnit.Count, value=1)
    return impl(cfg)


def compose_brief(cfg: RuntimeConfig, metrics, *, today: str | None = None) -> Brief:
    """Drive the tool-use loop and return a validated Brief."""
    today = today or dt.date.today().isoformat()
    cfg = replace(cfg, run_date=today)
    profile = cfg.profile
    system = [{"text": SYSTEM_PROMPT.format(tone=profile.tone)}]

    messages: list[dict[str, Any]] = [
        {
            "role": "user",
            "content": [
                {
                    "text": (
                        f"Prepare today's brief for {profile.name}. "
                        f"Today is {today} in timezone {profile.timezone}. "
                        "Gather the data you need, then I'll ask you to format the brief."
                    )
                }
            ],
        }
    ]

    tools = tool_config()

    # --- Tool-use loop -------------------------------------------------------
    for turn in range(cfg.max_agent_turns):
        resp = _bedrock.converse(
            modelId=cfg.model_id,
            system=system,
            messages=messages,
            toolConfig=tools,
            inferenceConfig={"maxTokens": 1200, "temperature": 0.4},
        )
        out = resp["output"]["message"]
        messages.append(out)
        stop = resp.get("stopReason")
        logger.debug("Agent turn", extra={"turn": turn, "stop_reason": stop})

        if stop != "tool_use":
            break

        tool_results = []
        for block in out.get("content", []):
            if "toolUse" not in block:
                continue
            tu = block["toolUse"]
            result = _run_tool(tu["name"], cfg, metrics)
            logger.info("Tool executed", extra={"tool": tu["name"]})
            tool_results.append(
                {
                    "toolResult": {
                        "toolUseId": tu["toolUseId"],
                        "content": [{"json": result}],
                    }
                }
            )
        messages.append({"role": "user", "content": tool_results})
    else:
        logger.warning("Hit max agent turns without natural stop")

    # --- Final forced-format turn -------------------------------------------
    messages.append({"role": "user", "content": [{"text": BRIEF_SCHEMA_HINT}]})
    final = _bedrock.converse(
        modelId=cfg.model_id,
        system=system,
        messages=messages,
        toolConfig=tools,
        inferenceConfig={"maxTokens": 1400, "temperature": 0.3},
    )
    final_text = "".join(
        b.get("text", "") for b in final["output"]["message"].get("content", [])
    )

    try:
        payload = _extract_json(final_text)
    except (json.JSONDecodeError, ValueError) as exc:
        logger.exception("Failed to parse brief JSON; emitting minimal brief", extra={"error": str(exc)})
        metrics.add_metric(name="brief.parse_failure", unit=MetricUnit.Count, value=1)
        payload = {"greeting": f"Good morning, {profile.name}.", "closing": final_text[:400]}

    metrics.add_metric(name="brief.composed", unit=MetricUnit.Count, value=1)
    return Brief.from_model_json(today, payload)

#!/usr/bin/env python3
"""Run the brief pipeline locally with every AWS dependency stubbed.

This proves the agent's control flow, tool loop, JSON parsing, and rendering
without any cloud calls. It writes the rendered HTML to /tmp so you can open it.

    python scripts/local_invoke.py
"""
from __future__ import annotations

import os
import sys
import tempfile
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

os.environ.setdefault("MODEL_ID", "us.amazon.nova-lite-v1:0")
os.environ.setdefault("SENDER_EMAIL", "agent@example.com")
os.environ.setdefault("RECIPIENT_EMAIL", "me@example.com")
os.environ.setdefault("USER_NAME", "Parthiban")

# A canned Bedrock conversation: first a tool call, then the final JSON brief.
_TOOL_TURN = {
    "output": {"message": {"role": "assistant", "content": [
        {"toolUse": {"toolUseId": "u1", "name": "get_tasks", "input": {}}},
        {"toolUse": {"toolUseId": "u2", "name": "get_weather", "input": {}}},
    ]}},
    "stopReason": "tool_use",
}
_ACK_TURN = {
    "output": {"message": {"role": "assistant", "content": [
        {"text": "I have the weather and tasks I need to write the brief."}
    ]}},
    "stopReason": "end_turn",
}
_FINAL_TURN = {
    "output": {"message": {"role": "assistant", "content": [{"text": """{
      "greeting": "Good morning, Parthiban.",
      "weather": "Partly cloudy, high 88 / low 71, low rain chance — no jacket needed.",
      "priorities": [
        {"title": "Ship the Q3 metrics dashboard", "reason": "due today and blocks the review", "due": "due today"},
        {"title": "Review Priya's PR on the billing service", "reason": "overdue and holding up a deploy", "due": "overdue"}
      ],
      "schedule": ["10:00 - Team standup", "14:00 - Design review"],
      "follow_ups": [
        {"subject": "Reply to Marcus about the API contract", "draft": "Hi Marcus - circling back on the API contract. Are the response shapes final so I can lock the client? Happy to hop on a quick call today."}
      ],
      "headlines": [],
      "closing": "Two things done before lunch and today is already a win."
    }"""}]}},
    "stopReason": "end_turn",
}


def main() -> None:
    from agent.config import load_config
    from agent.agent_core import compose_brief
    from agent.renderer import render_html
    from aws_lambda_powertools import Metrics

    converse = MagicMock(side_effect=[_TOOL_TURN, _ACK_TURN, _FINAL_TURN])

    with patch("agent.agent_core._bedrock") as bedrock, \
         patch.dict("agent.tools.TOOL_IMPLS", {
             "get_weather": MagicMock(return_value={"condition": "partly cloudy", "high_f": 88, "low_f": 71}),
             "get_tasks": MagicMock(return_value={"tasks": [], "today": "2026-07-18"}),
         }), \
         patch("agent.config._load_profile_document", return_value={
             "name": "Parthiban", "recipient_email": "me@example.com",
             "sender_email": "agent@example.com", "timezone": "America/New_York"}):
        bedrock.converse = converse
        cfg = load_config()
        brief = compose_brief(cfg, Metrics(namespace="DayBreakLocal"), today="2026-07-18")

    html = render_html(brief, "Parthiban")
    out = os.path.join(tempfile.gettempdir(), "daybreak_preview.html")
    with open(out, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"Composed brief with {len(brief.priorities)} priorities, {len(brief.follow_ups)} follow-ups.")
    print(f"Rendered preview -> {out}")


if __name__ == "__main__":
    main()

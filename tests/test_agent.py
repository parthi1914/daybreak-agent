"""Unit tests for the parts that carry real logic: JSON extraction, model
mapping, and HTML rendering. AWS-touching code is exercised via the local
harness; these tests stay pure and fast.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from agent.agent_core import _extract_json  # noqa: E402
from agent.config import RuntimeConfig, UserProfile  # noqa: E402
from agent.models import Brief  # noqa: E402
from agent.renderer import render_html, render_text, subject_line  # noqa: E402
from agent.tools import get_stale_followups, get_tasks  # noqa: E402
from agent.viewer import _matches_search, lambda_handler as viewer_handler  # noqa: E402


class _FakeTable:
    def __init__(self, items):
        self.items = items

    def query(self, **kwargs):
        return {"Items": self.items}


class _FakeDynamo:
    def __init__(self, items):
        self.items = items

    def Table(self, name):
        return _FakeTable(self.items)


def _cfg(run_date="2026-07-18"):
    profile = UserProfile(
        user_id="default",
        name="Sam",
        timezone="America/New_York",
        latitude=33.749,
        longitude=-84.388,
        recipient_email="sam@example.com",
        sender_email="agent@example.com",
        stale_after_days=3,
    )
    return RuntimeConfig(
        model_id="test-model",
        tasks_table="tasks",
        briefs_table="briefs",
        config_param="/daybreak/config",
        metrics_namespace="DayBreakTest",
        run_date=run_date,
        profile=profile,
    )


def test_extract_json_plain():
    assert _extract_json('{"greeting": "hi"}') == {"greeting": "hi"}


def test_extract_json_fenced():
    text = "Here you go:\n```json\n{\"greeting\": \"hi\", \"priorities\": []}\n```\nThanks!"
    assert _extract_json(text)["greeting"] == "hi"


def test_extract_json_with_surrounding_prose():
    text = 'Sure! {"greeting": "morning", "closing": "go"} hope that helps'
    out = _extract_json(text)
    assert out["greeting"] == "morning" and out["closing"] == "go"


def test_brief_from_model_json_tolerates_missing_fields():
    brief = Brief.from_model_json("2026-07-18", {"greeting": "hey"})
    assert brief.greeting == "hey"
    assert brief.priorities == []
    assert brief.headlines == []


def test_brief_roundtrips_to_record():
    payload = {
        "greeting": "morning",
        "priorities": [{"title": "ship", "reason": "due", "due": "today"}],
        "follow_ups": [{"subject": "s", "draft": "d"}],
        "schedule": ["10:00 standup"],
        "headlines": ["thing happened"],
        "closing": "go",
    }
    brief = Brief.from_model_json("2026-07-18", payload)
    rec = brief.to_record()
    assert rec["priorities"][0]["title"] == "ship"
    assert rec["follow_ups"][0]["subject"] == "s"


def test_render_html_contains_content_and_escapes():
    brief = Brief.from_model_json("2026-07-18", {
        "greeting": "Good morning, Sam <ok>",
        "priorities": [{"title": "Ship it", "reason": "due today", "due": "today"}],
    })
    html = render_html(brief, "Sam")
    assert "Ship it" in html
    assert "&lt;ok&gt;" in html  # escaped, not raw
    assert "<script" not in html.lower()


def test_render_text_lists_priorities():
    brief = Brief.from_model_json("2026-07-18", {
        "greeting": "hi",
        "priorities": [{"title": "A", "due": "today"}, {"title": "B"}],
    })
    text = render_text(brief, "Sam")
    assert "1. A [today]" in text
    assert "2. B" in text


def test_subject_line_counts_priorities():
    brief = Brief.from_model_json("2026-07-18", {"priorities": [{"title": "x"}]})
    assert "1 priority" in subject_line(brief)
    brief2 = Brief.from_model_json("2026-07-18", {"priorities": [{"title": "x"}, {"title": "y"}]})
    assert "2 priorities" in subject_line(brief2)


def test_empty_sections_are_omitted_from_html():
    brief = Brief.from_model_json("2026-07-18", {"greeting": "hi"})
    html = render_html(brief, "Sam")
    assert "Top priorities" not in html
    assert "Worth a glance" not in html


def test_subject_line_date_format_is_portable():
    brief = Brief.from_model_json("2026-07-18", {})
    assert "Saturday, July 18" in subject_line(brief)


def test_tools_use_scheduled_run_date(monkeypatch):
    items = [
        {"taskId": "old", "kind": "thread", "title": "Old thread", "status": "open", "updatedAt": "2026-07-14"},
        {"taskId": "today", "kind": "task", "title": "Today", "status": "open", "dueDate": "2026-07-18"},
        {"taskId": "future", "kind": "task", "title": "Future", "status": "open", "dueDate": "2026-07-19"},
    ]
    monkeypatch.setattr("agent.tools._dynamodb", _FakeDynamo(items))

    tasks = get_tasks(_cfg(run_date="2026-07-18"))["tasks"]
    stale = get_stale_followups(_cfg(run_date="2026-07-18"))

    assert tasks[0]["state"] == "due_today"
    assert stale["cutoff"] == "2026-07-15"
    assert [item["taskId"] for item in stale["stale"]] == ["old"]


def test_viewer_search_matches_nested_brief_content():
    brief = {
        "greeting": "Good morning",
        "priorities": [{"title": "Ship launch checklist"}],
        "follow_ups": [{"subject": "Vendor SOC2", "draft": "Any update?"}],
    }
    assert _matches_search(brief, "launch")
    assert _matches_search(brief, "soc2")
    assert not _matches_search(brief, "quarterly")


def test_viewer_config_requires_admin_token(monkeypatch):
    monkeypatch.setattr("agent.viewer._ADMIN_TOKEN", "secret")
    event = {
        "rawPath": "/api/config",
        "requestContext": {"http": {"method": "GET"}},
        "headers": {},
    }

    resp = viewer_handler(event, None)

    assert resp["statusCode"] == 401
    assert "admin_token_required" in resp["body"]


def test_viewer_config_disabled_without_admin_token(monkeypatch):
    monkeypatch.setattr("agent.viewer._ADMIN_TOKEN", "")
    event = {
        "rawPath": "/api/run",
        "requestContext": {"http": {"method": "POST"}},
        "headers": {},
        "body": "{}",
    }

    resp = viewer_handler(event, None)

    assert resp["statusCode"] == 403
    assert "admin_disabled" in resp["body"]

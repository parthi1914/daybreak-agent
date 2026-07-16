"""Read-only viewer for the most recent brief, exposed via a Lambda Function URL.

This is optional. The challenge's whole thesis is "the best tool is one you
never open" — the email is the product. But a public link is handy for the
submission, so this returns the latest stored brief as a standalone HTML page.
It only ever reads from the Briefs table; it can compose nothing.
"""
from __future__ import annotations

import os
from typing import Any

import boto3
from aws_lambda_powertools import Logger
from boto3.dynamodb.conditions import Key

from .models import Brief
from .renderer import render_html

logger = Logger()
_dynamodb = boto3.resource("dynamodb")

_BRIEFS_TABLE = os.environ.get("BRIEFS_TABLE", "daybreak-briefs")
_USER_ID = os.environ.get("USER_ID", "default")
_NAME = os.environ.get("USER_NAME", "there")


def _latest_brief() -> Brief | None:
    table = _dynamodb.Table(_BRIEFS_TABLE)
    resp = table.query(
        KeyConditionExpression=Key("userId").eq(_USER_ID),
        ScanIndexForward=False,  # newest date first
        Limit=1,
    )
    items = resp.get("Items", [])
    if not items:
        return None
    rec = items[0]["brief"]
    return Brief.from_model_json(items[0]["date"], _normalize(rec))


def _normalize(rec: dict[str, Any]) -> dict[str, Any]:
    """Briefs are stored with nested dicts already matching the model shape."""
    return {
        "greeting": rec.get("greeting", ""),
        "weather": rec.get("weather", ""),
        "priorities": rec.get("priorities", []),
        "schedule": rec.get("schedule", []),
        "follow_ups": rec.get("follow_ups", []),
        "headlines": rec.get("headlines", []),
        "closing": rec.get("closing", ""),
    }


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    brief = _latest_brief()
    if brief is None:
        html = (
            "<!doctype html><meta charset='utf-8'>"
            "<div style='font-family:sans-serif;max-width:600px;margin:60px auto;color:#5b6673;'>"
            "<h2 style='color:#1f3a5f;'>DayBreak</h2>"
            "No brief has been prepared yet. The agent runs on its schedule and this page "
            "will show your most recent brief.</div>"
        )
    else:
        html = render_html(brief, _NAME)
    return {
        "statusCode": 200,
        "headers": {"Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-store"},
        "body": html,
    }

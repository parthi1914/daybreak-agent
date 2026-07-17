#!/usr/bin/env python3
"""Seed richer DayBreak showcase data into DynamoDB.

The base seed is intentionally small. This script adds a broader set of
enterprise-flavored tasks and stale threads so the dashboard has enough signal
for demos, screenshots, and backfilled brief history.

Usage:
    python scripts/seed_showcase_data.py --region us-east-1 --base-date 2026-07-17
"""
from __future__ import annotations

import argparse
import datetime as dt

import boto3


def _iso(base: dt.date, offset: int) -> str:
    return (base + dt.timedelta(days=offset)).isoformat()


def seed(user_id: str, region: str, table_name: str, base_date: str) -> None:
    table = boto3.resource("dynamodb", region_name=region).Table(table_name)
    base = dt.date.fromisoformat(base_date)
    stale = _iso(base, -8)
    older = _iso(base, -13)
    recent = _iso(base, -1)

    items = [
        {
            "taskId": "showcase-release-readiness",
            "kind": "task",
            "title": "Finalize release readiness checklist for DayBreak",
            "priority": "high",
            "dueDate": _iso(base, 0),
            "status": "open",
            "updatedAt": recent,
            "area": "release",
        },
        {
            "taskId": "showcase-cost-review",
            "kind": "task",
            "title": "Review Free Tier cost guardrails before public demo",
            "priority": "high",
            "dueDate": _iso(base, 1),
            "status": "open",
            "updatedAt": recent,
            "area": "finance",
        },
        {
            "taskId": "showcase-security-check",
            "kind": "task",
            "title": "Confirm dashboard admin token is not published in article",
            "priority": "high",
            "dueDate": _iso(base, 1),
            "status": "open",
            "updatedAt": recent,
            "area": "security",
        },
        {
            "taskId": "showcase-observability",
            "kind": "task",
            "title": "Capture CloudWatch metrics screenshot after scheduled run",
            "priority": "medium",
            "dueDate": _iso(base, 2),
            "status": "open",
            "updatedAt": recent,
            "area": "observability",
        },
        {
            "taskId": "showcase-article",
            "kind": "task",
            "title": "Add deployed dashboard URL to Builder Center article",
            "priority": "high",
            "dueDate": _iso(base, 0),
            "status": "open",
            "updatedAt": recent,
            "area": "content",
        },
        {
            "taskId": "showcase-cleanup",
            "kind": "task",
            "title": "Document stack cleanup command for after the challenge",
            "priority": "low",
            "dueDate": _iso(base, 4),
            "status": "open",
            "updatedAt": recent,
            "area": "ops",
        },
        {
            "taskId": "showcase-thread-mentor",
            "kind": "thread",
            "title": "Follow up with mentor on architecture diagram feedback",
            "priority": "medium",
            "dueDate": "",
            "status": "open",
            "updatedAt": stale,
            "area": "feedback",
        },
        {
            "taskId": "showcase-thread-stakeholder",
            "kind": "thread",
            "title": "Nudge stakeholder to confirm submission screenshots",
            "priority": "high",
            "dueDate": "",
            "status": "open",
            "updatedAt": older,
            "area": "stakeholder",
        },
        {
            "taskId": "showcase-thread-ses",
            "kind": "thread",
            "title": "Ask operations to confirm SES and SNS verification emails",
            "priority": "high",
            "dueDate": "",
            "status": "open",
            "updatedAt": stale,
            "area": "ops",
        },
        {
            "taskId": "showcase-done-local-ui",
            "kind": "task",
            "title": "Build local React dashboard preview",
            "priority": "medium",
            "dueDate": _iso(base, -1),
            "status": "done",
            "updatedAt": recent,
            "area": "frontend",
        },
        {
            "taskId": "showcase-done-deploy",
            "kind": "task",
            "title": "Deploy SAM stack to AWS",
            "priority": "high",
            "dueDate": _iso(base, -1),
            "status": "done",
            "updatedAt": recent,
            "area": "cloud",
        },
    ]

    with table.batch_writer() as batch:
        for item in items:
            batch.put_item(Item={"userId": user_id, **item})
    print(f"Seeded {len(items)} showcase items for user '{user_id}' into {table_name}.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--user", default="default")
    parser.add_argument("--region", default="us-east-1")
    parser.add_argument("--table", default="daybreak-tasks")
    parser.add_argument("--base-date", default="2026-07-17")
    args = parser.parse_args()
    seed(args.user, args.region, args.table, args.base_date)

#!/usr/bin/env python3
"""Seed demo tasks so the agent has something real to reason about.

Usage:
    python scripts/seed_data.py --user default --region us-east-1

Adds a mix of tasks and "thread" items (some deliberately stale) to the
daybreak-tasks table. Safe to re-run; it upserts by taskId.
"""
from __future__ import annotations

import argparse
import datetime as dt

import boto3


def _date(offset_days: int) -> str:
    return (dt.date.today() + dt.timedelta(days=offset_days)).isoformat()


def seed(user_id: str, region: str, table_name: str) -> None:
    table = boto3.resource("dynamodb", region_name=region).Table(table_name)
    today = dt.date.today()
    stale = (today - dt.timedelta(days=6)).isoformat()
    recent = (today - dt.timedelta(days=1)).isoformat()

    items = [
        {"taskId": "t1", "kind": "task", "title": "Ship the Q3 metrics dashboard",
         "priority": "high", "dueDate": _date(0), "status": "open", "updatedAt": recent},
        {"taskId": "t2", "kind": "task", "title": "Review Priya's PR on the billing service",
         "priority": "high", "dueDate": _date(-1), "status": "open", "updatedAt": recent},
        {"taskId": "t3", "kind": "task", "title": "Draft the offsite agenda",
         "priority": "medium", "dueDate": _date(2), "status": "open", "updatedAt": recent},
        {"taskId": "t4", "kind": "task", "title": "Renew the TLS certificate",
         "priority": "low", "dueDate": _date(5), "status": "open", "updatedAt": recent},
        {"taskId": "th1", "kind": "thread", "title": "Follow up with vendor on SOC2 timeline",
         "priority": "medium", "dueDate": "", "status": "open", "updatedAt": stale},
        {"taskId": "th2", "kind": "thread", "title": "Reply to Marcus about the API contract",
         "priority": "high", "dueDate": "", "status": "open", "updatedAt": stale},
        {"taskId": "done1", "kind": "task", "title": "Book flights",
         "priority": "low", "dueDate": _date(-3), "status": "done", "updatedAt": recent},
    ]

    with table.batch_writer() as batch:
        for it in items:
            batch.put_item(Item={"userId": user_id, **it})
    print(f"Seeded {len(items)} items for user '{user_id}' into {table_name}.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--user", default="default")
    ap.add_argument("--region", default="us-east-1")
    ap.add_argument("--table", default="daybreak-tasks")
    args = ap.parse_args()
    seed(args.user, args.region, args.table)

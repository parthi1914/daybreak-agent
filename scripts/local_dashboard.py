#!/usr/bin/env python3
"""Serve the DayBreak React dashboard locally with mocked AWS dependencies.

This is a browser preview for the Lambda Function URL dashboard. It serves the
same React shell and API routes as production, but uses in-memory demo briefs,
config, and run queue responses instead of DynamoDB, SSM, and Lambda.

    python scripts/local_dashboard.py
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
os.environ.setdefault("AWS_REGION", "us-east-1")
os.environ.setdefault("POWERTOOLS_SERVICE_NAME", "daybreak-local")
os.environ.setdefault("POWERTOOLS_METRICS_NAMESPACE", "DayBreakLocal")
os.environ.setdefault("USER_NAME", "Parthiban")
os.environ.setdefault("DASHBOARD_ADMIN_TOKEN", "local-admin")

from agent import viewer  # noqa: E402


DEMO_CONFIG = {
    "user_id": "default",
    "name": "Parthiban",
    "timezone": "America/New_York",
    "latitude": 33.749,
    "longitude": -84.388,
    "recipient_email": "you@example.com",
    "sender_email": "agent@example.com",
    "news_feed_url": "https://aws.amazon.com/blogs/aws/feed/",
    "stale_after_days": 3,
    "max_tasks_in_brief": 6,
    "tone": "warm, concise, and executive-ready",
}

DEMO_BRIEFS = [
    {
        "date": "2026-07-18",
        "createdAt": "2026-07-18T10:00:04Z",
        "messageId": "local-001",
        "brief": {
            "greeting": "Good morning, Parthiban. DayBreak has the morning sorted.",
            "weather": "Partly cloudy, high 88 / low 71, low rain chance. No jacket needed.",
            "priorities": [
                {
                    "title": "Ship the DayBreak challenge submission",
                    "reason": "The challenge window is open and early submission matters.",
                    "due": "due today",
                },
                {
                    "title": "Capture proof of the scheduled run",
                    "reason": "A Scheduler screenshot makes the autonomous behavior obvious.",
                    "due": "due today",
                },
                {
                    "title": "Verify SES delivery and public dashboard link",
                    "reason": "The article needs a working app or repo link.",
                    "due": "today",
                },
            ],
            "schedule": ["09:00 - Review CloudWatch dashboard", "10:30 - Deploy final SAM stack"],
            "follow_ups": [
                {
                    "subject": "AWS Builder Center article",
                    "draft": "Hi team - I am finalizing the Weekend Agent Challenge article now. The autonomous run proof and repo link will be added before submission.",
                }
            ],
            "headlines": ["Amazon Bedrock agent patterns continue to evolve", "EventBridge Scheduler remains a simple fit for always-on workflows"],
            "closing": "Keep the deployment tight and the screenshots clear.",
        },
    },
    {
        "date": "2026-07-17",
        "createdAt": "2026-07-17T10:00:04Z",
        "messageId": "local-002",
        "brief": {
            "greeting": "Good morning, Parthiban. The build plan is ready.",
            "weather": "Clear sky, high 86 / low 70. Good morning for a clean deploy.",
            "priorities": [
                {
                    "title": "Finish the agent tool loop",
                    "reason": "Bedrock needs real tool output before writing the brief.",
                    "due": "due today",
                },
                {
                    "title": "Seed demo tasks",
                    "reason": "The dashboard needs realistic brief content for screenshots.",
                    "due": "today",
                },
            ],
            "schedule": ["08:30 - Implementation pass", "13:00 - Local validation"],
            "follow_ups": [],
            "headlines": ["AWS Free Tier credits can cover small challenge workloads"],
            "closing": "A small, working path beats a large unfinished one.",
        },
    },
]


class LocalTable:
    def query(self, **kwargs):
        return {"Items": DEMO_BRIEFS}


class LocalDynamo:
    def Table(self, name):
        return LocalTable()


class LocalSsm:
    def get_parameter(self, **kwargs):
        return {"Parameter": {"Value": json.dumps(DEMO_CONFIG)}}

    def put_parameter(self, **kwargs):
        DEMO_CONFIG.clear()
        DEMO_CONFIG.update(json.loads(kwargs["Value"]))
        return {"Version": 1}


class LocalLambda:
    def invoke(self, **kwargs):
        return {"StatusCode": 202}


viewer._dynamodb = LocalDynamo()
viewer._ssm = LocalSsm()
viewer._lambda = LocalLambda()
viewer._ADMIN_TOKEN = os.environ["DASHBOARD_ADMIN_TOKEN"]
viewer._NAME = os.environ["USER_NAME"]
viewer._SCHEDULE_NAME = "daybreak-morning"
viewer._SCHEDULE_CRON = "cron(0 6 * * ? *)"
viewer._SCHEDULE_TIMEZONE = "America/New_York"


class Handler(BaseHTTPRequestHandler):
    server_version = "DayBreakLocal/1.0"

    def do_GET(self) -> None:
        self._handle()

    def do_POST(self) -> None:
        self._handle()

    def do_PUT(self) -> None:
        self._handle()

    def do_OPTIONS(self) -> None:
        self._handle()

    def log_message(self, fmt: str, *args) -> None:
        print(f"{self.address_string()} - {fmt % args}")

    def _handle(self) -> None:
        parsed = urlparse(self.path)
        length = int(self.headers.get("content-length", "0"))
        body = self.rfile.read(length).decode("utf-8") if length else ""
        query = {k: v[-1] for k, v in parse_qs(parsed.query).items()}
        event = {
            "rawPath": parsed.path,
            "queryStringParameters": query,
            "headers": dict(self.headers.items()),
            "requestContext": {"http": {"method": self.command}},
            "body": body,
        }
        resp = viewer.lambda_handler(event, None)
        self.send_response(resp.get("statusCode", 200))
        for key, value in resp.get("headers", {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(str(resp.get("body", "")).encode("utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5173)
    args = parser.parse_args()

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"DayBreak dashboard preview: http://{args.host}:{args.port}")
    print("Admin token for local settings/test run: local-admin")
    server.serve_forever()


if __name__ == "__main__":
    main()

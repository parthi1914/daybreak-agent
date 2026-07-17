"""Delivery: send the brief by email (SES) and persist it (DynamoDB).

Persistence serves two purposes: it's the record the read-only viewer reads,
and it's a durable audit trail of what the agent decided each morning.
"""
from __future__ import annotations

import datetime as dt
import smtplib
from email.message import EmailMessage
from email.utils import make_msgid
from typing import Any

import boto3
from aws_lambda_powertools import Logger

from .config import RuntimeConfig
from .models import Brief
from .renderer import render_html, render_text, subject_line

logger = Logger(child=True)
_ses = boto3.client("ses")
_dynamodb = boto3.resource("dynamodb")

# Briefs expire from the store after this many days (TTL), keeping it cheap.
_BRIEF_TTL_DAYS = 120


def send_email(cfg: RuntimeConfig, brief: Brief) -> str:
    """Send the brief through the configured provider."""
    if cfg.delivery_provider == "gmail":
        return _send_gmail(cfg, brief)
    return _send_ses(cfg, brief)


def _send_ses(cfg: RuntimeConfig, brief: Brief) -> str:
    """Send the brief via SES. Returns the SES message id."""
    p = cfg.profile
    resp = _ses.send_email(
        Source=p.sender_email,
        Destination={"ToAddresses": [p.recipient_email]},
        Message={
            "Subject": {"Data": subject_line(brief), "Charset": "UTF-8"},
            "Body": {
                "Html": {"Data": render_html(brief, p.name), "Charset": "UTF-8"},
                "Text": {"Data": render_text(brief, p.name), "Charset": "UTF-8"},
            },
        },
    )
    message_id = resp["MessageId"]
    logger.info("Brief emailed", extra={"provider": "ses", "message_id": message_id, "to": p.recipient_email})
    return message_id


def _send_gmail(cfg: RuntimeConfig, brief: Brief) -> str:
    """Send the brief via Gmail SMTP using an app password."""
    p = cfg.profile
    username = cfg.gmail_username or p.sender_email
    if not username or not cfg.gmail_app_password:
        raise RuntimeError("Gmail delivery requires GMAIL_USERNAME and GMAIL_APP_PASSWORD")

    message_id = make_msgid(domain="daybreak-agent.local")
    msg = EmailMessage()
    msg["Subject"] = subject_line(brief)
    msg["From"] = username
    msg["To"] = p.recipient_email
    msg["Message-ID"] = message_id
    msg.set_content(render_text(brief, p.name))
    msg.add_alternative(render_html(brief, p.name), subtype="html")

    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=15) as smtp:
        smtp.login(username, cfg.gmail_app_password)
        smtp.send_message(msg)

    logger.info("Brief emailed", extra={"provider": "gmail", "message_id": message_id, "to": p.recipient_email})
    return message_id


def store_brief(cfg: RuntimeConfig, brief: Brief, message_id: str) -> None:
    """Persist the brief for the viewer and as an audit record."""
    table = _dynamodb.Table(cfg.briefs_table)
    ttl = int((dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=_BRIEF_TTL_DAYS)).timestamp())
    item: dict[str, Any] = {
        "userId": cfg.profile.user_id,
        "date": brief.date,
        "brief": brief.to_record(),
        "messageId": message_id,
        "createdAt": dt.datetime.now(dt.timezone.utc).isoformat(),
        "expiresAt": ttl,
    }
    table.put_item(Item=item)
    logger.info("Brief stored", extra={"date": brief.date})

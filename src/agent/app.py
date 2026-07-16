"""DayBreak agent — Lambda entry point.

Triggered by EventBridge Scheduler (not a button). On each run it:
  1. Loads the user's profile/config.
  2. Runs the Bedrock tool-use loop to compose a structured brief.
  3. Emails the brief (SES) and stores it (DynamoDB).

Cross-cutting concerns are handled by AWS Lambda Powertools:
  - Logger    : structured JSON logs with correlation context.
  - Metrics   : EMF metrics (no extra IAM) for tools used, briefs sent, failures.
  - Tracer    : X-Ray spans across Bedrock / DynamoDB / SES.
  - Idempotency: a scheduled run that retries (or double-fires) will not send
                 two briefs for the same date — the first result is replayed.
"""
from __future__ import annotations

import datetime as dt
import os
from typing import Any

from aws_lambda_powertools import Logger, Metrics, Tracer
from aws_lambda_powertools.metrics import MetricUnit
from aws_lambda_powertools.utilities.idempotency import (
    DynamoDBPersistenceLayer,
    IdempotencyConfig,
    idempotent_function,
)
from aws_lambda_powertools.utilities.typing import LambdaContext

from .agent_core import compose_brief
from .config import load_config
from .delivery import send_email, store_brief

logger = Logger()
tracer = Tracer()
metrics = Metrics()

# Idempotency keyed on the brief date, so at-least-once scheduling never yields
# two emails for the same morning. The persistence table is created in SAM.
_persistence = DynamoDBPersistenceLayer(table_name=os.environ.get("IDEMPOTENCY_TABLE", "daybreak-idempotency"))
_idem_config = IdempotencyConfig(event_key_jmespath="brief_date", expires_after_seconds=6 * 60 * 60)


@idempotent_function(data_keyword_argument="run", persistence_store=_persistence, config=_idem_config)
@tracer.capture_method
def _run_agent(*, run: dict[str, Any]) -> dict[str, Any]:
    """The idempotent unit of work: compose, send, store for one date."""
    cfg = load_config()
    if not cfg.profile.recipient_email or not cfg.profile.sender_email:
        raise RuntimeError("recipient_email and sender_email must be configured (SSM /daybreak/config)")

    brief = compose_brief(cfg, metrics, today=run["brief_date"])
    message_id = send_email(cfg, brief)
    store_brief(cfg, brief, message_id)

    metrics.add_metric(name="brief.sent", unit=MetricUnit.Count, value=1)
    return {
        "date": brief.date,
        "message_id": message_id,
        "priorities": len(brief.priorities),
        "follow_ups": len(brief.follow_ups),
    }


@logger.inject_lambda_context(log_event=True)
@tracer.capture_lambda_handler
@metrics.log_metrics(capture_cold_start_metric=True)
def lambda_handler(event: dict[str, Any], context: LambdaContext) -> dict[str, Any]:
    """Scheduler entry point. `event.date` may override the target day (for backfills)."""
    brief_date = (event or {}).get("date") or dt.date.today().isoformat()
    _idem_config.register_lambda_context(context)
    logger.append_keys(brief_date=brief_date)

    try:
        result = _run_agent(run={"brief_date": brief_date})
        logger.info("Run complete", extra=result)
        return {"status": "ok", **result}
    except Exception:
        # Powertools logs the traceback; metric feeds the CloudWatch alarm.
        metrics.add_metric(name="brief.failed", unit=MetricUnit.Count, value=1)
        logger.exception("Agent run failed")
        # Re-raise so Lambda marks the invocation as an error and the Scheduler
        # DLQ / retry policy engages.
        raise

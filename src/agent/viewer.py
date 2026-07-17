"""React dashboard and API for DayBreak, exposed by a Lambda Function URL.

The dashboard is intentionally serverless and small: one Lambda returns the
React shell and a few JSON endpoints. Public users can view brief history for a
submission/demo link. Administrative actions (settings updates and test runs)
are available only when a dashboard admin token is configured and supplied.
"""
from __future__ import annotations

import datetime as dt
import json
import os
from decimal import Decimal
from typing import Any

import boto3
from aws_lambda_powertools import Logger
from boto3.dynamodb.conditions import Key

logger = Logger()
_dynamodb = boto3.resource("dynamodb")
_lambda = boto3.client("lambda")
_ssm = boto3.client("ssm")

_BRIEFS_TABLE = os.environ.get("BRIEFS_TABLE", "daybreak-briefs")
_USER_ID = os.environ.get("USER_ID", "default")
_NAME = os.environ.get("USER_NAME", "there")
_CONFIG_PARAM = os.environ.get("CONFIG_PARAM", "/daybreak/config")
_AGENT_FUNCTION = os.environ.get("AGENT_FUNCTION_NAME", "daybreak-agent")
_ADMIN_TOKEN = os.environ.get("DASHBOARD_ADMIN_TOKEN", "")
_SCHEDULE_NAME = os.environ.get("SCHEDULE_NAME", "daybreak-morning")
_SCHEDULE_CRON = os.environ.get("SCHEDULE_CRON", "cron(0 6 * * ? *)")
_SCHEDULE_TIMEZONE = os.environ.get("SCHEDULE_TIMEZONE", "America/New_York")

_JSON_HEADERS = {
    "Content-Type": "application/json; charset=utf-8",
    "Cache-Control": "no-store",
}
_HTML_HEADERS = {
    "Content-Type": "text/html; charset=utf-8",
    "Cache-Control": "no-store",
}


def _json_default(value: Any) -> Any:
    if isinstance(value, Decimal):
        if value % 1 == 0:
            return int(value)
        return float(value)
    return str(value)


def _response(status: int, body: Any, headers: dict[str, str] | None = None) -> dict[str, Any]:
    if isinstance(body, (dict, list)):
        payload = json.dumps(body, default=_json_default)
        base_headers = _JSON_HEADERS
    else:
        payload = str(body)
        base_headers = _HTML_HEADERS
    return {
        "statusCode": status,
        "headers": {**base_headers, **(headers or {})},
        "body": payload,
    }


def _method(event: dict[str, Any]) -> str:
    return event.get("requestContext", {}).get("http", {}).get("method", "GET").upper()


def _path(event: dict[str, Any]) -> str:
    return event.get("rawPath") or event.get("path") or "/"


def _query(event: dict[str, Any]) -> dict[str, str]:
    return event.get("queryStringParameters") or {}


def _body(event: dict[str, Any]) -> dict[str, Any]:
    raw = event.get("body") or "{}"
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {}


def _headers(event: dict[str, Any]) -> dict[str, str]:
    return {str(k).lower(): str(v) for k, v in (event.get("headers") or {}).items()}


def _is_authorized(event: dict[str, Any]) -> bool:
    if not _ADMIN_TOKEN:
        return False
    provided = _headers(event).get("x-daybreak-admin-token", "")
    return provided == _ADMIN_TOKEN


def _require_admin(event: dict[str, Any]) -> dict[str, Any] | None:
    if not _ADMIN_TOKEN:
        return _response(403, {"error": "admin_disabled"})
    if not _is_authorized(event):
        return _response(401, {"error": "admin_token_required"})
    return None


def _normalize_brief(rec: dict[str, Any]) -> dict[str, Any]:
    return {
        "date": rec.get("date", ""),
        "greeting": rec.get("greeting", ""),
        "weather": rec.get("weather", ""),
        "priorities": rec.get("priorities", []),
        "schedule": rec.get("schedule", []),
        "follow_ups": rec.get("follow_ups", []),
        "headlines": rec.get("headlines", []),
        "closing": rec.get("closing", ""),
    }


def _matches_search(brief: dict[str, Any], query: str) -> bool:
    if not query:
        return True
    haystack = json.dumps(brief, default=_json_default).lower()
    return query.lower() in haystack


def _list_briefs(limit: int, search: str = "") -> list[dict[str, Any]]:
    table = _dynamodb.Table(_BRIEFS_TABLE)
    resp = table.query(
        KeyConditionExpression=Key("userId").eq(_USER_ID),
        ScanIndexForward=False,
        Limit=min(max(limit, 1), 50),
    )
    rows = []
    for item in resp.get("Items", []):
        brief = _normalize_brief(item.get("brief", {}))
        brief["date"] = item.get("date", brief.get("date", ""))
        if not _matches_search(brief, search):
            continue
        rows.append(
            {
                "date": item.get("date", ""),
                "createdAt": item.get("createdAt", ""),
                "messageId": item.get("messageId", ""),
                "brief": brief,
                "stats": {
                    "priorities": len(brief.get("priorities", [])),
                    "followUps": len(brief.get("follow_ups", [])),
                    "headlines": len(brief.get("headlines", [])),
                },
            }
        )
    return rows


def _get_config() -> dict[str, Any]:
    resp = _ssm.get_parameter(Name=_CONFIG_PARAM, WithDecryption=True)
    return json.loads(resp["Parameter"]["Value"])


def _put_config(payload: dict[str, Any]) -> dict[str, Any]:
    current = _get_config()
    allowed = {
        "name",
        "timezone",
        "latitude",
        "longitude",
        "recipient_email",
        "sender_email",
        "news_feed_url",
        "stale_after_days",
        "max_tasks_in_brief",
        "tone",
    }
    updates = {k: payload[k] for k in allowed if k in payload}
    if "latitude" in updates:
        updates["latitude"] = float(updates["latitude"])
    if "longitude" in updates:
        updates["longitude"] = float(updates["longitude"])
    if "stale_after_days" in updates:
        updates["stale_after_days"] = int(updates["stale_after_days"])
    if "max_tasks_in_brief" in updates:
        updates["max_tasks_in_brief"] = int(updates["max_tasks_in_brief"])

    next_config = {**current, **updates}
    _ssm.put_parameter(
        Name=_CONFIG_PARAM,
        Type="String",
        Value=json.dumps(next_config, separators=(",", ":")),
        Overwrite=True,
    )
    return next_config


def _invoke_agent(payload: dict[str, Any]) -> dict[str, Any]:
    date = payload.get("date") or dt.date.today().isoformat()
    _lambda.invoke(
        FunctionName=_AGENT_FUNCTION,
        InvocationType="Event",
        Payload=json.dumps({"date": date}).encode("utf-8"),
    )
    return {"status": "queued", "date": date}


def _api_briefs(event: dict[str, Any]) -> dict[str, Any]:
    params = _query(event)
    limit = int(params.get("limit", "20"))
    search = params.get("q", "")
    briefs = _list_briefs(limit=limit, search=search)
    return _response(
        200,
        {
            "user": {"id": _USER_ID, "name": _NAME},
            "items": briefs,
            "adminEnabled": bool(_ADMIN_TOKEN),
        },
    )


def _api_status(event: dict[str, Any]) -> dict[str, Any]:
    briefs = _list_briefs(limit=30)
    totals = {
        "briefs": len(briefs),
        "priorities": sum(item["stats"]["priorities"] for item in briefs),
        "followUps": sum(item["stats"]["followUps"] for item in briefs),
        "headlines": sum(item["stats"]["headlines"] for item in briefs),
    }
    latest = briefs[0] if briefs else None
    return _response(
        200,
        {
            "agent": {
                "name": "DayBreak",
                "userName": _NAME,
                "mode": "Always-on scheduled agent",
                "scheduleName": _SCHEDULE_NAME,
                "scheduleExpression": _SCHEDULE_CRON,
                "timezone": _SCHEDULE_TIMEZONE,
                "trigger": "Amazon EventBridge Scheduler",
                "runtime": "AWS Lambda + Amazon Bedrock Nova Lite",
                "delivery": "Amazon SES email + DynamoDB dashboard history",
            },
            "challengeFit": [
                {"label": "Morning brief agent", "status": "complete", "detail": "Runs at 6 AM and drafts the day before the user wakes up."},
                {"label": "Watcher", "status": "complete", "detail": "Watches task due dates, stale threads, weather, and optional headlines."},
                {"label": "Overnight tidy-up", "status": "complete", "detail": "Sorts the backlog into priorities, schedule items, and quick context."},
                {"label": "Stale-thread nudge", "status": "complete", "detail": "Finds quiet threads and drafts ready-to-send follow-ups."},
            ],
            "services": [
                "EventBridge Scheduler",
                "AWS Lambda",
                "Amazon Bedrock Nova Lite",
                "Amazon DynamoDB",
                "Amazon SES",
                "AWS Systems Manager Parameter Store",
                "Amazon SQS DLQ",
                "CloudWatch + SNS alarms",
            ],
            "totals": totals,
            "latest": latest,
            "adminEnabled": bool(_ADMIN_TOKEN),
        },
    )


def _api_config(event: dict[str, Any]) -> dict[str, Any]:
    denied = _require_admin(event)
    if denied:
        return denied
    if _method(event) == "GET":
        return _response(200, {"config": _get_config()})
    if _method(event) == "PUT":
        return _response(200, {"config": _put_config(_body(event))})
    return _response(405, {"error": "method_not_allowed"})


def _api_run(event: dict[str, Any]) -> dict[str, Any]:
    denied = _require_admin(event)
    if denied:
        return denied
    if _method(event) != "POST":
        return _response(405, {"error": "method_not_allowed"})
    return _response(202, _invoke_agent(_body(event)))


def _dashboard_html() -> str:
    app_config = json.dumps({"userName": _NAME, "adminEnabled": bool(_ADMIN_TOKEN)})
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>DayBreak Agent Console</title>
  <script crossorigin src="https://unpkg.com/react@18/umd/react.production.min.js"></script>
  <script crossorigin src="https://unpkg.com/react-dom@18/umd/react-dom.production.min.js"></script>
  <style>
    :root {{
      color-scheme: light;
      --ink:#172033; --muted:#657084; --line:#dde3eb; --panel:#ffffff;
      --bg:#f4f6f9; --nav:#111827; --accent:#2563eb; --accent-2:#0f766e;
      --warn:#b45309; --danger:#b91c1c;
    }}
    * {{ box-sizing:border-box; }}
    body {{ margin:0; background:var(--bg); color:var(--ink); font:14px/1.5 Inter, ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Helvetica, Arial, sans-serif; }}
    button, input, select, textarea {{ font:inherit; }}
    button {{ border:1px solid var(--line); background:#fff; color:var(--ink); border-radius:8px; padding:8px 12px; cursor:pointer; }}
    button.primary {{ background:var(--accent); border-color:var(--accent); color:#fff; }}
    button.ghost {{ background:transparent; color:#e5e7eb; border-color:#374151; }}
    button:disabled {{ opacity:.55; cursor:not-allowed; }}
    .shell {{ display:grid; grid-template-columns:260px 1fr; min-height:100vh; }}
    .sidebar {{ background:var(--nav); color:#f9fafb; padding:22px; display:flex; flex-direction:column; gap:22px; }}
    .brand {{ display:flex; align-items:center; gap:10px; font-weight:700; letter-spacing:.01em; }}
    .brandmark {{ width:34px; height:34px; border-radius:8px; display:grid; place-items:center; background:#f59e0b; color:#111827; font-weight:800; }}
    .nav {{ display:grid; gap:6px; }}
    .nav button {{ text-align:left; width:100%; }}
    .nav button.active {{ background:#fff; color:#111827; border-color:#fff; }}
    .sidefoot {{ margin-top:auto; color:#aeb7c6; font-size:12px; }}
    .main {{ min-width:0; }}
    .topbar {{ height:72px; display:flex; align-items:center; justify-content:space-between; gap:18px; padding:0 28px; border-bottom:1px solid var(--line); background:#fff; }}
    .title h1 {{ margin:0; font-size:20px; line-height:1.2; }}
    .title p {{ margin:3px 0 0; color:var(--muted); }}
    .admin {{ display:flex; align-items:center; gap:8px; }}
    .admin input {{ width:220px; padding:8px 10px; border:1px solid var(--line); border-radius:8px; }}
    .content {{ padding:24px 28px 32px; display:grid; gap:18px; }}
    .metrics {{ display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:12px; }}
    .metric, .panel, .brief, .empty {{ background:#fff; border:1px solid var(--line); border-radius:8px; }}
    .metric {{ padding:14px 16px; }}
    .metric .label {{ color:var(--muted); font-size:12px; text-transform:uppercase; letter-spacing:.08em; }}
    .metric .value {{ font-size:26px; font-weight:700; margin-top:4px; }}
    .toolbar {{ display:flex; align-items:center; justify-content:space-between; gap:12px; }}
    .hero {{ background:#fff; border:1px solid var(--line); border-radius:8px; padding:22px; display:grid; grid-template-columns:1.25fr .75fr; gap:20px; align-items:start; }}
    .hero h2 {{ margin:0; font-size:28px; line-height:1.15; }}
    .hero p {{ margin:8px 0 0; color:var(--muted); max-width:760px; }}
    .proof {{ display:grid; gap:10px; }}
    .proof-row {{ display:flex; justify-content:space-between; gap:12px; padding:10px 0; border-bottom:1px solid #edf0f4; }}
    .proof-row:last-child {{ border-bottom:0; }}
    .proof-row span:first-child {{ color:var(--muted); }}
    .proof-row strong {{ text-align:right; }}
    .showcase-grid {{ display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:12px; }}
    .usecase {{ background:#fff; border:1px solid var(--line); border-radius:8px; padding:16px; min-height:150px; }}
    .usecase h3 {{ margin:10px 0 8px; font-size:15px; }}
    .usecase p {{ margin:0; color:var(--muted); }}
    .check {{ width:28px; height:28px; border-radius:8px; display:grid; place-items:center; background:#dcfce7; color:#166534; font-weight:800; }}
    .architecture {{ display:grid; grid-template-columns:repeat(5,minmax(0,1fr)); gap:10px; }}
    .step {{ background:#fff; border:1px solid var(--line); border-radius:8px; padding:14px; position:relative; min-height:106px; }}
    .step:not(:last-child)::after {{ content:""; position:absolute; right:-10px; top:50%; width:10px; height:1px; background:#aab4c3; }}
    .step-kicker {{ color:var(--muted); font-size:11px; text-transform:uppercase; letter-spacing:.08em; }}
    .step strong {{ display:block; margin-top:6px; }}
    .services {{ display:flex; flex-wrap:wrap; gap:8px; }}
    .chip {{ display:inline-flex; align-items:center; border:1px solid var(--line); background:#fff; border-radius:999px; padding:6px 10px; color:#334155; }}
    .search {{ display:flex; gap:8px; min-width:320px; }}
    .search input {{ width:100%; padding:9px 10px; border:1px solid var(--line); border-radius:8px; }}
    .grid {{ display:grid; grid-template-columns:320px 1fr; gap:16px; align-items:start; }}
    .list {{ display:grid; gap:10px; }}
    .brief-row {{ width:100%; text-align:left; padding:12px; background:#fff; border:1px solid var(--line); border-radius:8px; }}
    .brief-row.active {{ border-color:var(--accent); box-shadow:0 0 0 2px rgba(37,99,235,.12); }}
    .row-date {{ font-weight:700; }}
    .row-sub {{ color:var(--muted); font-size:12px; margin-top:4px; }}
    .brief {{ padding:22px; }}
    .brief-head {{ display:flex; justify-content:space-between; gap:12px; border-bottom:1px solid var(--line); padding-bottom:16px; margin-bottom:16px; }}
    .brief-head h2 {{ margin:0; font-size:22px; }}
    .badge {{ display:inline-flex; align-items:center; height:24px; padding:0 8px; border-radius:999px; background:#eef2ff; color:#3730a3; font-size:12px; font-weight:600; }}
    .section {{ margin:0 0 18px; }}
    .section h3 {{ margin:0 0 8px; font-size:12px; text-transform:uppercase; letter-spacing:.08em; color:var(--muted); }}
    .priority {{ padding:10px 0; border-top:1px solid #edf0f4; }}
    .priority:first-of-type {{ border-top:0; }}
    .muted {{ color:var(--muted); }}
    .draft {{ background:#f8fafc; border:1px solid var(--line); border-radius:8px; padding:12px; margin:8px 0 0; white-space:pre-wrap; }}
    .panel {{ padding:18px; }}
    .panel h2 {{ margin:0 0 14px; font-size:18px; }}
    .form {{ display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:14px; }}
    label {{ display:grid; gap:6px; color:var(--muted); font-size:12px; font-weight:600; text-transform:uppercase; letter-spacing:.06em; }}
    input, textarea {{ width:100%; padding:9px 10px; border:1px solid var(--line); border-radius:8px; color:var(--ink); background:#fff; }}
    textarea {{ min-height:92px; resize:vertical; }}
    .full {{ grid-column:1 / -1; }}
    .actions {{ display:flex; justify-content:flex-end; gap:10px; margin-top:16px; }}
    .status {{ color:var(--muted); min-height:20px; }}
    .empty {{ padding:28px; color:var(--muted); }}
    @media (max-width: 920px) {{
      .shell {{ grid-template-columns:1fr; }}
      .sidebar {{ position:static; }}
      .metrics, .grid, .form, .hero, .showcase-grid, .architecture {{ grid-template-columns:1fr; }}
      .step:not(:last-child)::after {{ display:none; }}
      .topbar {{ height:auto; align-items:flex-start; flex-direction:column; padding:18px; }}
      .content {{ padding:18px; }}
      .search, .admin input {{ min-width:0; width:100%; }}
      .toolbar, .admin {{ align-items:stretch; flex-direction:column; }}
    }}
  </style>
</head>
<body>
  <div id="root"></div>
  <script>
    window.DAYBREAK = {app_config};
  </script>
  <script>
    const e = React.createElement;
    const api = {{
      token: () => sessionStorage.getItem("daybreakAdminToken") || "",
      async request(path, options = {{}}) {{
        const headers = Object.assign({{"Content-Type":"application/json"}}, options.headers || {{}});
        const token = api.token();
        if (token) headers["x-daybreak-admin-token"] = token;
        const res = await fetch(path, Object.assign({{}}, options, {{headers}}));
        const data = await res.json().catch(() => ({{}}));
        if (!res.ok) throw new Error(data.error || "request_failed");
        return data;
      }}
    }};
    function fmtDate(value) {{
      if (!value) return "No date";
      const parts = value.split("-").map(Number);
      return new Date(parts[0], parts[1] - 1, parts[2]).toLocaleDateString(undefined, {{weekday:"short", month:"short", day:"numeric"}});
    }}
    function Metric({{label, value}}) {{
      return e("div", {{className:"metric"}}, e("div", {{className:"label"}}, label), e("div", {{className:"value"}}, value));
    }}
    function OverviewView({{status, briefs, goHistory}}) {{
      const agent = status?.agent || {{}};
      const totals = status?.totals || {{briefs:briefs.length, priorities:0, followUps:0, headlines:0}};
      const latest = status?.latest;
      const fit = status?.challengeFit || [];
      const services = status?.services || [];
      return e(React.Fragment, null,
        e("div", {{className:"hero"}},
          e("div", null,
            e("span", {{className:"badge"}}, "Always-on AWS agent"),
            e("h2", null, "DayBreak prepares the morning before the user opens anything."),
            e("p", null, "The agent wakes on schedule, gathers real inputs, reasons with Bedrock Nova, sends the brief by email, and stores every result for this dashboard.")
          ),
          e("div", {{className:"proof"}},
            e("div", {{className:"proof-row"}}, e("span", null, "Trigger"), e("strong", null, agent.trigger || "EventBridge Scheduler")),
            e("div", {{className:"proof-row"}}, e("span", null, "Schedule"), e("strong", null, (agent.scheduleExpression || "cron(0 6 * * ? *)") + " / " + (agent.timezone || "America/New_York"))),
            e("div", {{className:"proof-row"}}, e("span", null, "Runtime"), e("strong", null, agent.runtime || "Lambda + Bedrock")),
            e("div", {{className:"proof-row"}}, e("span", null, "Reports back"), e("strong", null, agent.delivery || "SES + DynamoDB"))
          )
        ),
        e("div", {{className:"metrics"}},
          e(Metric, {{label:"Generated briefs", value:totals.briefs || 0}}),
          e(Metric, {{label:"Priorities found", value:totals.priorities || 0}}),
          e(Metric, {{label:"Nudges drafted", value:totals.followUps || 0}}),
          e(Metric, {{label:"Latest run", value:latest?.date || "Waiting"}})
        ),
        e("div", {{className:"showcase-grid"}}, fit.map((item, i) => e("div", {{className:"usecase", key:i}},
          e("div", {{className:"check"}}, "✓"),
          e("h3", null, item.label),
          e("p", null, item.detail)
        ))),
        e("div", {{className:"panel"}},
          e("h2", null, "Autonomous Flow"),
          e("div", {{className:"architecture"}},
            [
              ["1", "EventBridge", "Wakes DayBreak every morning at 6 AM."],
              ["2", "Lambda", "Loads config and runs the agent orchestration."],
              ["3", "Tools", "Reads tasks, stale threads, weather, and feeds."],
              ["4", "Bedrock Nova", "Chooses tools and composes structured JSON."],
              ["5", "SES + DynamoDB", "Emails the brief and stores history."]
            ].map((s) => e("div", {{className:"step", key:s[0]}}, e("div", {{className:"step-kicker"}}, "Step " + s[0]), e("strong", null, s[1]), e("p", {{className:"muted"}}, s[2])))
          )
        ),
        e("div", {{className:"panel"}},
          e("div", {{className:"toolbar"}}, e("h2", null, "AWS Free Tier Services"), e("button", {{onClick:goHistory}}, "View generated briefs")),
          e("div", {{className:"services"}}, services.map((svc, i) => e("span", {{className:"chip", key:i}}, svc)))
        )
      );
    }}
    function BriefDetail({{record}}) {{
      if (!record) return e("div", {{className:"empty"}}, "No briefs yet. The scheduled agent will populate this view after the first run.");
      const b = record.brief;
      return e("article", {{className:"brief"}},
        e("div", {{className:"brief-head"}},
          e("div", null, e("h2", null, fmtDate(record.date)), e("div", {{className:"muted"}}, b.greeting || "DayBreak brief")),
          e("span", {{className:"badge"}}, record.stats.priorities + " priorities")
        ),
        b.weather && e("section", {{className:"section"}}, e("h3", null, "Weather"), e("div", null, b.weather)),
        b.priorities?.length ? e("section", {{className:"section"}}, e("h3", null, "Top Priorities"),
          b.priorities.map((p, i) => e("div", {{className:"priority", key:i}},
            e("strong", null, p.title), p.due && e("span", {{className:"muted"}}, " - " + p.due),
            p.reason && e("div", {{className:"muted"}}, p.reason)
          ))
        ) : null,
        b.schedule?.length ? e("section", {{className:"section"}}, e("h3", null, "Calendar"), b.schedule.map((s, i) => e("div", {{key:i}}, s))) : null,
        b.follow_ups?.length ? e("section", {{className:"section"}}, e("h3", null, "Nudges"), b.follow_ups.map((f, i) => e("div", {{key:i, className:"priority"}}, e("strong", null, f.subject), e("div", {{className:"draft"}}, f.draft)))) : null,
        b.headlines?.length ? e("section", {{className:"section"}}, e("h3", null, "Headlines"), e("ul", null, b.headlines.map((h, i) => e("li", {{key:i}}, h)))) : null,
        b.closing && e("p", {{className:"muted"}}, b.closing)
      );
    }}
    function HistoryView({{briefs, selected, setSelected, query, setQuery, refresh}}) {{
      const current = briefs.find(x => x.date === selected) || briefs[0];
      const totals = briefs.reduce((a, r) => ({{p:a.p+r.stats.priorities, f:a.f+r.stats.followUps, h:a.h+r.stats.headlines}}), {{p:0,f:0,h:0}});
      return e(React.Fragment, null,
        e("div", {{className:"metrics"}},
          e(Metric, {{label:"Briefs", value:briefs.length}}),
          e(Metric, {{label:"Priorities", value:totals.p}}),
          e(Metric, {{label:"Follow-ups", value:totals.f}}),
          e(Metric, {{label:"Headlines", value:totals.h}})
        ),
        e("div", {{className:"toolbar"}},
          e("div", {{className:"search"}}, e("input", {{value:query, onChange:ev=>setQuery(ev.target.value), placeholder:"Search briefs"}}), e("button", {{onClick:refresh}}, "Refresh")),
          e("span", {{className:"muted"}}, "Latest stored DayBreak output")
        ),
        e("div", {{className:"grid"}},
          e("div", {{className:"list"}}, briefs.map(r => e("button", {{key:r.date, className:"brief-row " + (current?.date === r.date ? "active" : ""), onClick:()=>setSelected(r.date)}}, e("div", {{className:"row-date"}}, fmtDate(r.date)), e("div", {{className:"row-sub"}}, `${{r.stats.priorities}} priorities - ${{r.stats.followUps}} nudges`)))),
          e(BriefDetail, {{record:current}})
        )
      );
    }}
    function SettingsView() {{
      const [config, setConfig] = React.useState(null);
      const [status, setStatus] = React.useState("");
      const load = React.useCallback(async () => {{
        setStatus("");
        try {{ setConfig((await api.request("/api/config")).config); }}
        catch (err) {{ setStatus(err.message === "admin_token_required" ? "Admin token required." : "Settings are disabled until an admin token is configured."); }}
      }}, []);
      React.useEffect(() => {{ load(); }}, [load]);
      const update = (key, value) => setConfig(Object.assign({{}}, config, {{[key]: value}}));
      const save = async () => {{
        setStatus("Saving...");
        try {{ setConfig((await api.request("/api/config", {{method:"PUT", body:JSON.stringify(config)}})).config); setStatus("Saved."); }}
        catch (err) {{ setStatus("Save failed: " + err.message); }}
      }};
      if (!config) return e("div", {{className:"panel"}}, e("h2", null, "Settings"), e("div", {{className:"status"}}, status), e("button", {{onClick:load}}, "Load settings"));
      return e("div", {{className:"panel"}},
        e("h2", null, "Settings"),
        e("div", {{className:"form"}},
          e("label", null, "Name", e("input", {{value:config.name || "", onChange:ev=>update("name", ev.target.value)}})),
          e("label", null, "Timezone", e("input", {{value:config.timezone || "", onChange:ev=>update("timezone", ev.target.value)}})),
          e("label", null, "Recipient", e("input", {{value:config.recipient_email || "", onChange:ev=>update("recipient_email", ev.target.value)}})),
          e("label", null, "Sender", e("input", {{value:config.sender_email || "", onChange:ev=>update("sender_email", ev.target.value)}})),
          e("label", null, "Latitude", e("input", {{value:config.latitude ?? "", onChange:ev=>update("latitude", ev.target.value)}})),
          e("label", null, "Longitude", e("input", {{value:config.longitude ?? "", onChange:ev=>update("longitude", ev.target.value)}})),
          e("label", null, "Stale days", e("input", {{type:"number", min:"1", value:config.stale_after_days ?? 3, onChange:ev=>update("stale_after_days", ev.target.value)}})),
          e("label", null, "Max tasks", e("input", {{type:"number", min:"1", value:config.max_tasks_in_brief ?? 6, onChange:ev=>update("max_tasks_in_brief", ev.target.value)}})),
          e("label", {{className:"full"}}, "News feed URL", e("input", {{value:config.news_feed_url || "", onChange:ev=>update("news_feed_url", ev.target.value)}})),
          e("label", {{className:"full"}}, "Tone", e("textarea", {{value:config.tone || "", onChange:ev=>update("tone", ev.target.value)}}))
        ),
        e("div", {{className:"actions"}}, e("div", {{className:"status"}}, status), e("button", {{className:"primary", onClick:save}}, "Save settings"))
      );
    }}
    function RunView() {{
      const [date, setDate] = React.useState(new Date().toISOString().slice(0,10));
      const [status, setStatus] = React.useState("");
      const run = async () => {{
        setStatus("Queueing run...");
        try {{ const res = await api.request("/api/run", {{method:"POST", body:JSON.stringify({{date}})}}); setStatus("Queued for " + res.date + "."); }}
        catch (err) {{ setStatus("Run failed: " + err.message); }}
      }};
      return e("div", {{className:"panel"}}, e("h2", null, "Test Run"),
        e("div", {{className:"form"}}, e("label", null, "Brief date", e("input", {{type:"date", value:date, onChange:ev=>setDate(ev.target.value)}}))),
        e("div", {{className:"actions"}}, e("div", {{className:"status"}}, status), e("button", {{className:"primary", onClick:run}}, "Queue test run"))
      );
    }}
    function App() {{
      const [tab, setTab] = React.useState("overview");
      const [briefs, setBriefs] = React.useState([]);
      const [status, setStatus] = React.useState(null);
      const [selected, setSelected] = React.useState("");
      const [query, setQuery] = React.useState("");
      const [token, setToken] = React.useState(api.token());
      const refresh = React.useCallback(async () => {{
        const [data, statusData] = await Promise.all([
          api.request("/api/briefs?limit=30&q=" + encodeURIComponent(query)),
          api.request("/api/status")
        ]);
        setBriefs(data.items || []);
        setStatus(statusData);
        if (!selected && data.items?.[0]) setSelected(data.items[0].date);
      }}, [query, selected]);
      React.useEffect(() => {{ refresh(); }}, [refresh]);
      const saveToken = () => {{ sessionStorage.setItem("daybreakAdminToken", token); }};
      return e("div", {{className:"shell"}},
        e("aside", {{className:"sidebar"}},
          e("div", {{className:"brand"}}, e("div", {{className:"brandmark"}}, "D"), e("div", null, "DayBreak", e("div", {{className:"muted"}}, "Agent Console"))),
          e("nav", {{className:"nav"}}, ["overview","history","settings","run"].map(t => e("button", {{key:t, className:"ghost " + (tab === t ? "active" : ""), onClick:()=>setTab(t)}}, t === "overview" ? "Overview" : t === "history" ? "Brief history" : t === "settings" ? "Settings" : "Test run"))),
          e("div", {{className:"sidefoot"}}, "EventBridge Scheduler -> Lambda -> Bedrock -> SES")
        ),
        e("main", {{className:"main"}},
          e("header", {{className:"topbar"}},
            e("div", {{className:"title"}}, e("h1", null, tab === "overview" ? "Challenge showcase" : tab === "history" ? "Brief history" : tab === "settings" ? "Runtime settings" : "Manual test run"), e("p", null, "Autonomous morning brief for " + (window.DAYBREAK.userName || "you"))),
            e("div", {{className:"admin"}}, e("input", {{type:"password", value:token, onChange:ev=>setToken(ev.target.value), placeholder: window.DAYBREAK.adminEnabled ? "Admin token" : "Admin disabled"}}), e("button", {{onClick:saveToken}}, "Use token"))
          ),
          e("section", {{className:"content"}},
            tab === "overview" && e(OverviewView, {{status, briefs, goHistory:()=>setTab("history")}}),
            tab === "history" && e(HistoryView, {{briefs, selected, setSelected, query, setQuery, refresh}}),
            tab === "settings" && e(SettingsView),
            tab === "run" && e(RunView)
          )
        )
      );
    }}
    ReactDOM.createRoot(document.getElementById("root")).render(e(App));
  </script>
</body>
</html>"""


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    method = _method(event)
    path = _path(event)

    if method == "OPTIONS":
        return _response(204, "")
    try:
        if path == "/api/briefs":
            return _api_briefs(event)
        if path == "/api/status":
            return _api_status(event)
        if path == "/api/config":
            return _api_config(event)
        if path == "/api/run":
            return _api_run(event)
        return _response(200, _dashboard_html())
    except Exception as exc:  # noqa: BLE001 - API boundary
        logger.exception("Viewer request failed", extra={"path": path, "method": method})
        return _response(500, {"error": "viewer_error", "message": str(exc)})

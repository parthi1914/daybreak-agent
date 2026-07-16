"""Render a Brief to HTML and plain text for email delivery.

Design notes: email clients strip <style> and ignore most modern CSS, so
everything is inline and table-free where possible. The look is deliberately
quiet — a single ink-blue accent, a humanist serif for the date, system sans
for the body — so the content is the thing you notice, not the chrome. The one
signature element is the left accent rule on each section, which reads like a
margin note in a daybook.
"""
from __future__ import annotations

import datetime as dt
import html

from .models import Brief

_INK = "#1f3a5f"       # deep ink blue — the single accent
_RULE = "#e2e6ec"      # hairline
_MUTE = "#5b6673"      # secondary text
_BG = "#f6f7f9"

_SECTION = (
    'border-left:3px solid {accent};padding:2px 0 2px 16px;margin:0 0 22px 0;'
)


def _esc(s: str) -> str:
    return html.escape(s or "", quote=False)


def _pretty_date(iso: str) -> str:
    try:
        d = dt.date.fromisoformat(iso)
        return f"{d.strftime('%A, %B')} {d.day}"
    except ValueError:
        return iso


def _section(label: str, inner: str, accent: str = _INK) -> str:
    if not inner.strip():
        return ""
    return (
        f'<div style="{_SECTION.format(accent=accent)}">'
        f'<div style="font:600 11px/1.4 -apple-system,Segoe UI,Roboto,sans-serif;'
        f'letter-spacing:.10em;text-transform:uppercase;color:{_MUTE};margin-bottom:8px;">{_esc(label)}</div>'
        f"{inner}</div>"
    )


def render_html(brief: Brief, name: str) -> str:
    body_font = "font:15px/1.6 -apple-system,BlinkMacSystemFont,Segoe UI,Roboto,Helvetica,sans-serif;color:#22262b;"

    priorities = ""
    if brief.priorities:
        rows = []
        for i, p in enumerate(brief.priorities, 1):
            reason = f'<span style="color:{_MUTE};"> — {_esc(p.reason)}</span>' if p.reason else ""
            due = (
                f'<span style="display:inline-block;margin-left:8px;font-size:11px;color:{_INK};'
                f'border:1px solid {_RULE};border-radius:10px;padding:1px 8px;">{_esc(p.due)}</span>'
                if p.due else ""
            )
            rows.append(
                f'<div style="margin:0 0 10px 0;"><span style="color:{_INK};font-weight:600;">{i}.</span> '
                f'<span style="font-weight:600;">{_esc(p.title)}</span>{due}{reason}</div>'
            )
        priorities = "".join(rows)

    schedule = ""
    if brief.schedule:
        items = "".join(
            f'<div style="margin:0 0 6px 0;color:#22262b;">{_esc(s)}</div>' for s in brief.schedule
        )
        schedule = items

    follow_ups = ""
    if brief.follow_ups:
        cards = []
        for f in brief.follow_ups:
            cards.append(
                f'<div style="background:#fff;border:1px solid {_RULE};border-radius:8px;'
                f'padding:12px 14px;margin:0 0 10px 0;">'
                f'<div style="font-weight:600;margin-bottom:6px;">{_esc(f.subject)}</div>'
                f'<div style="color:{_MUTE};white-space:pre-wrap;">{_esc(f.draft)}</div></div>'
            )
        follow_ups = "".join(cards)

    headlines = ""
    if brief.headlines:
        lis = "".join(f'<li style="margin:0 0 5px 0;">{_esc(h)}</li>' for h in brief.headlines)
        headlines = f'<ul style="margin:0;padding-left:18px;color:#22262b;">{lis}</ul>'

    sections = "".join(
        [
            _section("The day", f'<div style="{body_font}">{_esc(brief.greeting)}</div>'),
            _section("Weather", f'<div style="{body_font}">{_esc(brief.weather)}</div>') if brief.weather else "",
            _section("Top priorities", priorities),
            _section("On the calendar", schedule),
            _section("Nudges ready to send", follow_ups),
            _section("Worth a glance", headlines),
        ]
    )

    closing = (
        f'<div style="{body_font}color:{_MUTE};font-style:italic;margin-top:6px;">{_esc(brief.closing)}</div>'
        if brief.closing else ""
    )

    return f"""\
<!doctype html><html><body style="margin:0;background:{_BG};padding:24px 0;">
<div style="max-width:600px;margin:0 auto;background:#fff;border:1px solid {_RULE};border-radius:12px;overflow:hidden;">
  <div style="background:{_INK};color:#fff;padding:22px 28px;">
    <div style="font:600 13px/1.2 -apple-system,Segoe UI,Roboto,sans-serif;letter-spacing:.14em;text-transform:uppercase;opacity:.75;">DayBreak</div>
    <div style="font:400 26px/1.25 Georgia,'Times New Roman',serif;margin-top:4px;">{_esc(_pretty_date(brief.date))}</div>
  </div>
  <div style="padding:26px 28px 22px 28px;">
    {sections}
    {closing}
  </div>
  <div style="border-top:1px solid {_RULE};padding:14px 28px;color:{_MUTE};font:12px/1.5 -apple-system,Segoe UI,Roboto,sans-serif;">
    Prepared automatically for {_esc(name)} before the day began. Reply to retune what DayBreak watches.
  </div>
</div></body></html>"""


def render_text(brief: Brief, name: str) -> str:
    """Plain-text fallback for clients that reject HTML."""
    lines = [f"DayBreak — {_pretty_date(brief.date)}", ""]
    if brief.greeting:
        lines += [brief.greeting, ""]
    if brief.weather:
        lines += [f"Weather: {brief.weather}", ""]
    if brief.priorities:
        lines.append("Top priorities:")
        for i, p in enumerate(brief.priorities, 1):
            tag = f" [{p.due}]" if p.due else ""
            reason = f" — {p.reason}" if p.reason else ""
            lines.append(f"  {i}. {p.title}{tag}{reason}")
        lines.append("")
    if brief.schedule:
        lines.append("On the calendar:")
        lines += [f"  - {s}" for s in brief.schedule] + [""]
    if brief.follow_ups:
        lines.append("Nudges ready to send:")
        for f in brief.follow_ups:
            lines += [f"  {f.subject}:", f"    {f.draft}"]
        lines.append("")
    if brief.headlines:
        lines.append("Worth a glance:")
        lines += [f"  - {h}" for h in brief.headlines] + [""]
    if brief.closing:
        lines.append(brief.closing)
    return "\n".join(lines)


def subject_line(brief: Brief) -> str:
    n = len(brief.priorities)
    stem = f"{n} priorit{'y' if n == 1 else 'ies'}" if n else "your brief"
    return f"DayBreak · {_pretty_date(brief.date)} — {stem}"

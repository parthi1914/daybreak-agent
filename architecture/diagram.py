#!/usr/bin/env python3
"""Render the DayBreak architecture diagram to PNG (for the article)."""
from __future__ import annotations

import matplotlib
matplotlib.use("Agg")
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch
import matplotlib.pyplot as plt

INK = "#1f3a5f"
ACCENT = "#c8622d"
MUTE = "#5b6673"
RULE = "#d7dce3"
FILL = "#ffffff"
BAND = "#f2f4f7"
GREEN = "#2e7d5b"

fig, ax = plt.subplots(figsize=(13, 7.6), dpi=170)
ax.set_xlim(0, 13)
ax.set_ylim(0, 7.6)
ax.axis("off")


def box(x, y, w, h, title, sub="", fc=FILL, ec=INK, tc=INK, lw=1.6):
    ax.add_patch(FancyBboxPatch(
        (x, y), w, h, boxstyle="round,pad=0.02,rounding_size=0.12",
        linewidth=lw, edgecolor=ec, facecolor=fc, mutation_aspect=1))
    ax.text(x + w / 2, y + h / 2 + (0.16 if sub else 0), title,
            ha="center", va="center", fontsize=10.5, fontweight="bold", color=tc)
    if sub:
        ax.text(x + w / 2, y + h / 2 - 0.20, sub, ha="center", va="center",
                fontsize=8, color=MUTE)


def arrow(x1, y1, x2, y2, color=INK, style="-|>", ls="-", lw=1.6):
    ax.add_patch(FancyArrowPatch(
        (x1, y1), (x2, y2), arrowstyle=style, mutation_scale=14,
        color=color, lw=lw, linestyle=ls, shrinkA=2, shrinkB=2))


# Title
ax.text(0.2, 7.25, "DayBreak — always-on morning-brief agent", fontsize=15,
        fontweight="bold", color=INK)
ax.text(0.2, 6.92, "EventBridge Scheduler wakes a Bedrock tool-use agent that "
        "prepares and delivers the brief before you're up.", fontsize=9.5, color=MUTE)

# Trigger
box(0.2, 4.7, 2.3, 1.1, "EventBridge", "Scheduler · cron 6 AM", fc=BAND)
ax.text(1.35, 4.5, "the trigger", ha="center", fontsize=7.5, color=ACCENT, style="italic")

# Agent Lambda (central)
box(3.2, 4.3, 3.5, 1.9, "AWS Lambda", "", fc="#eef3fb", ec=INK, lw=2.0)
ax.text(4.95, 5.78, "DayBreak agent", ha="center", fontsize=10.5, fontweight="bold", color=INK)
ax.text(4.95, 5.5, "Python 3.12 · Powertools", ha="center", fontsize=8, color=MUTE)
ax.text(4.95, 5.18, "idempotent · traced", ha="center", fontsize=8, color=MUTE)
ax.text(4.95, 4.75, "tool-use loop", ha="center", fontsize=8.5, color=ACCENT, style="italic")

# Bedrock
box(7.4, 4.55, 2.4, 1.4, "Amazon Bedrock", "Nova Lite · Converse", fc="#eef3fb")
ax.text(8.6, 4.38, "reasons & composes", ha="center", fontsize=7.5, color=MUTE, style="italic")

# Config
box(3.35, 2.75, 3.2, 0.95, "SSM Parameter Store", "profile & settings", fc=BAND)

# Data sources (tools)
box(0.2, 2.6, 2.5, 1.25, "DynamoDB", "Tasks & threads", fc=FILL)
box(0.2, 0.9, 2.5, 1.15, "Weather / RSS", "Open-Meteo · feeds", fc=FILL, ec=MUTE, tc=MUTE)

# Outputs
box(10.3, 4.9, 2.4, 1.05, "Amazon SES", "delivers the brief", fc="#eef7f1", ec=GREEN, tc=GREEN)
box(10.3, 3.4, 2.4, 1.0, "Inbox", "6 AM, ready to read", fc=BAND, ec=GREEN, tc=GREEN)
box(7.4, 2.75, 2.4, 0.95, "DynamoDB", "Briefs (audit + TTL)", fc=FILL)
box(10.3, 1.7, 2.4, 1.0, "Viewer URL", "latest brief (read-only)", fc=FILL, ec=MUTE, tc=MUTE)

# Reliability band
box(3.2, 0.7, 6.6, 1.15, "", "", fc="#fbf3ee", ec=ACCENT, lw=1.3)
ax.text(3.45, 1.55, "Reliability & observability", fontsize=9, fontweight="bold", color=ACCENT)
ax.text(3.45, 1.18, "SQS dead-letter queue · Scheduler retries · CloudWatch alarms → SNS email · dashboard · X-Ray",
        fontsize=8, color=MUTE)

# Arrows
arrow(2.5, 5.25, 3.2, 5.25)                       # scheduler -> lambda
arrow(6.7, 5.5, 7.4, 5.4)                          # lambda -> bedrock
arrow(7.4, 5.05, 6.7, 4.95, color=ACCENT, ls="--")  # bedrock -> lambda (tool calls back)
arrow(3.9, 4.3, 3.5, 3.7, color=MUTE)              # lambda -> ssm
arrow(1.45, 3.85, 3.4, 4.55, color=MUTE)           # dynamodb tasks -> lambda
arrow(1.45, 2.05, 3.35, 4.4, color=MUTE, ls=":")   # weather -> lambda
arrow(6.7, 5.6, 10.3, 5.45, color=GREEN)           # lambda -> ses
arrow(11.5, 4.9, 11.5, 4.4, color=GREEN)           # ses -> inbox
arrow(6.6, 4.6, 7.4, 3.35, color=MUTE)             # lambda -> briefs
arrow(9.8, 3.05, 10.3, 2.4, color=MUTE, ls=":")    # briefs -> viewer

# Legend
ax.text(0.2, 0.35, "solid = data/control flow      dashed = tool-call round-trip      dotted = optional / external",
        fontsize=8, color=MUTE)

plt.tight_layout()
out = __file__.rsplit("/", 1)[0] + "/architecture.png"
plt.savefig(out, bbox_inches="tight", facecolor="white")
print(f"wrote {out}")

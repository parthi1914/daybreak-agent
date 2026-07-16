"""Typed data structures for the brief the agent produces.

Keeping the brief as a validated dataclass (rather than a free-form string)
is what lets the same payload drive the HTML email, the stored record, and the
read-only viewer without re-parsing model prose.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class PriorityItem:
    title: str
    reason: str = ""
    due: str = ""

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "PriorityItem":
        return cls(
            title=str(d.get("title", "")).strip(),
            reason=str(d.get("reason", "")).strip(),
            due=str(d.get("due", "")).strip(),
        )


@dataclass
class FollowUp:
    subject: str
    draft: str

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "FollowUp":
        return cls(
            subject=str(d.get("subject", "")).strip(),
            draft=str(d.get("draft", "")).strip(),
        )


@dataclass
class Brief:
    """The finished morning brief, ready to render or persist."""

    date: str
    greeting: str
    weather: str = ""
    priorities: list[PriorityItem] = field(default_factory=list)
    schedule: list[str] = field(default_factory=list)
    follow_ups: list[FollowUp] = field(default_factory=list)
    headlines: list[str] = field(default_factory=list)
    closing: str = ""

    @classmethod
    def from_model_json(cls, date: str, d: dict[str, Any]) -> "Brief":
        """Build a Brief from the model's JSON, tolerating missing fields."""
        return cls(
            date=date,
            greeting=str(d.get("greeting", "")).strip(),
            weather=str(d.get("weather", "")).strip(),
            priorities=[PriorityItem.from_dict(p) for p in d.get("priorities", []) if isinstance(p, dict)],
            schedule=[str(s).strip() for s in d.get("schedule", []) if str(s).strip()],
            follow_ups=[FollowUp.from_dict(f) for f in d.get("follow_ups", []) if isinstance(f, dict)],
            headlines=[str(h).strip() for h in d.get("headlines", []) if str(h).strip()],
            closing=str(d.get("closing", "")).strip(),
        )

    def to_record(self) -> dict[str, Any]:
        """Flatten to a DynamoDB-friendly document."""
        return {
            "date": self.date,
            "greeting": self.greeting,
            "weather": self.weather,
            "priorities": [p.__dict__ for p in self.priorities],
            "schedule": self.schedule,
            "follow_ups": [f.__dict__ for f in self.follow_ups],
            "headlines": self.headlines,
            "closing": self.closing,
        }

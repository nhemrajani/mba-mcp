"""Pydantic records returned by the MCP tools."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

AtsKind = Literal["greenhouse", "lever", "ashby", "workday", "smartrecruiters"]

APPLICATION_STATUSES: tuple[str, ...] = (
    "interested",
    "applied",
    "interview",
    "offer",
    "rejected",
)

INTERACTION_KINDS: tuple[str, ...] = (
    "coffee_chat",
    "call",
    "email",
    "event",
    "referral",
    "intro",
    "note",
)


class Target(BaseModel):
    id: int
    name: str
    ats_kind: AtsKind | None = None
    ats_slug: str | None = None
    ats_url: str | None = None
    priority: int = 2
    created_at: str


class Job(BaseModel):
    company: str
    title: str
    location: str | None = None
    url: str
    posted_at: str | None = None
    source: str


class Application(BaseModel):
    id: int
    company: str
    role: str
    url: str | None = None
    status: str = "interested"
    deadline: str | None = None
    notes: str | None = None
    jd_text: str | None = None
    created_at: str
    updated_at: str
    days_until_deadline: int | None = None


class Profile(BaseModel):
    """Who the user is. Drives alumni matching and the default timeline."""

    full_name: str | None = None
    school: str | None = None
    school_linkedin: str | None = None
    graduation_year: int | None = None
    track: str | None = None
    target_locations: str | None = None
    email: str | None = None
    background: str | None = None
    goals: str | None = None
    hard_constraints: str | None = None
    updated_at: str | None = None


class ResumeNote(BaseModel):
    id: int
    note: str
    kind: str = "update"
    added_on: str


class Contact(BaseModel):
    id: int
    full_name: str
    company: str | None = None
    title: str | None = None
    email: str | None = None
    linkedin_url: str | None = None
    school: str | None = None
    grad_year: int | None = None
    connected_on: str | None = None
    source: str = "linkedin_csv"


class EmailSuggestion(BaseModel):
    email: str
    pattern: str
    confidence: Literal["high", "medium", "low"]
    basis: str
    verified: bool = False


class WarmPath(BaseModel):
    contact: Contact
    score: int
    reasons: list[str] = Field(default_factory=list)
    last_interaction: str | None = None
    interaction_count: int = 0


class Interaction(BaseModel):
    id: int
    contact_id: int
    kind: str
    notes: str | None = None
    occurred_at: str
    next_followup: str | None = None


class Followup(BaseModel):
    contact: Contact
    due_on: str
    days_overdue: int
    last_kind: str | None = None
    last_notes: str | None = None
    interaction_id: int


class OutreachDraft(BaseModel):
    id: int
    contact_id: int
    to_email: str | None = None
    subject: str
    body: str
    status: str = "draft"
    created_at: str
    sent_at: str | None = None
    gmail_message_id: str | None = None


class Milestone(BaseModel):
    id: str
    name: str
    description: str
    starts_on: str
    ends_on: str
    status: Literal["past", "active", "upcoming"]
    days_until: int
    actions: list[str] = Field(default_factory=list)


class Timeline(BaseModel):
    track: str
    label: str
    audience: str
    cycle: str
    today: str
    source: str
    disclaimer: str
    milestones: list[Milestone]

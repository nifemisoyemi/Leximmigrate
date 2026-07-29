"""
cases/monday.py — push LexImmigrate leads to the firm's Monday.com CRM board.

Design rules:
  - Monday is a MIRROR of our data, never the source of truth. The Lead row in
    Postgres is created first; if Monday is down, the lead is still safe.
  - Failures are logged and swallowed. A visitor must never see an error page
    because a CRM sync hiccuped.
  - Columns are resolved BY TITLE at runtime (and cached), so the board can be
    reordered or get new columns without breaking this code. Renaming the
    titles/labels this module writes to ("Email", "Phone", "Reason", "Details",
    "Not eligible", "Package question") WILL break the mapping — don't.

Requires in settings.py:
    MONDAY_API_TOKEN  (from .env — never commit)
    MONDAY_BOARD_ID   (e.g. "18424209220")

Uses `requests` (pip install requests if missing).
"""

import json
import logging

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

API_URL = "https://api.monday.com/v2"
TIMEOUT = 6  # seconds — a hung CRM must not hang the visitor's request

# Reasons this module writes to the Status column. Must match board labels exactly.
REASON_NOT_ELIGIBLE = "Not eligible"
REASON_PACKAGE_QUESTION = "Package question"

_columns_cache = None  # {title: {"id": ..., "type": ...}} — per-process cache


def _configured():
    return bool(getattr(settings, "MONDAY_API_TOKEN", "")) and bool(
        getattr(settings, "MONDAY_BOARD_ID", "")
    )


def _gql(query, variables=None):
    """Run one GraphQL request against Monday. Raises on transport/API errors."""
    resp = requests.post(
        API_URL,
        json={"query": query, "variables": variables or {}},
        headers={
            "Authorization": settings.MONDAY_API_TOKEN,
            "Content-Type": "application/json",
            "API-Version": "2024-10",
        },
        timeout=TIMEOUT,
    )
    resp.raise_for_status()
    data = resp.json()
    if "errors" in data:
        raise RuntimeError(f"Monday API error: {data['errors']}")
    return data["data"]


def _get_columns():
    """Fetch and cache the board's columns, keyed by title."""
    global _columns_cache
    if _columns_cache is not None:
        return _columns_cache
    data = _gql(
        "query ($board: [ID!]) { boards (ids: $board) { columns { id title type } } }",
        {"board": [str(settings.MONDAY_BOARD_ID)]},
    )
    boards = data.get("boards") or []
    if not boards:
        raise RuntimeError("Monday board not found — check MONDAY_BOARD_ID / token access.")
    _columns_cache = {c["title"]: {"id": c["id"], "type": c["type"]} for c in boards[0]["columns"]}
    return _columns_cache


def push_lead(lead, reason, details=""):
    """
    Create an item on the CRM board for this lead. Never raises.
    Returns the Monday item id (str) on success, or "" on failure/unconfigured.
    """
    if not _configured():
        logger.info("Monday sync skipped (not configured).")
        return ""
    try:
        cols = _get_columns()
        values = {}

        if "Email" in cols and lead.email:
            if cols["Email"]["type"] == "email":
                values[cols["Email"]["id"]] = {"email": lead.email, "text": lead.email}
            else:  # plain text column
                values[cols["Email"]["id"]] = lead.email
        if "Phone" in cols and lead.phone:
            digits = "".join(ch for ch in lead.phone if ch.isdigit())
            if digits:
                if cols["Phone"]["type"] == "phone":
                    values[cols["Phone"]["id"]] = {"phone": digits, "countryShortName": "US"}
                else:
                    values[cols["Phone"]["id"]] = lead.phone
        if "Reason" in cols and reason:
            values[cols["Reason"]["id"]] = {"label": reason}
        if "Details" in cols and details:
            if cols["Details"]["type"] == "long_text":
                values[cols["Details"]["id"]] = {"text": details[:2000]}
            else:
                values[cols["Details"]["id"]] = details[:2000]

        data = _gql(
            """
            mutation ($board: ID!, $name: String!, $values: JSON!) {
              create_item (board_id: $board, item_name: $name, column_values: $values) { id }
            }
            """,
            {
                "board": str(settings.MONDAY_BOARD_ID),
                "name": f"{lead.first_name} {lead.last_name}".strip() or lead.email,
                "values": json.dumps(values),
            },
        )
        item_id = data["create_item"]["id"]
        logger.info("Monday: created item %s for lead %s", item_id, lead.pk)
        return item_id
    except Exception:
        logger.exception("Monday sync failed for lead %s (lead is saved locally).", getattr(lead, "pk", "?"))
        return ""
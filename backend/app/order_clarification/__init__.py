"""Pure, trusted-input clarification decisions; no persistence or transport."""

from .engine import advance_issue
from .followup import plan_no_reply

__all__ = ["advance_issue", "plan_no_reply"]

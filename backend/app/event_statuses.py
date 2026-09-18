"""The statuses an event request may hold, and how each one reads to an organiser (CS-E07-S1).

This module is the single source of truth for the vocabulary. The database constraint, the
migration and the serialised response all derive from ``EVENT_REQUEST_STATUSES`` below, so a
value can never be storable without wording, or described without being storable.

The wording is the team's own, recorded so the test cases have a stated expected value rather
than a tester's judgement. It is amendable once confirmed with the customer; changing a line
here changes the interface and the tests that assert on it, and nothing else.
"""

from typing import Final

# Stored value -> (name shown to the organiser, one line explaining what it means for them).
EVENT_REQUEST_STATUSES: Final[dict[str, tuple[str, str]]] = {
    "draft": (
        "Draft",
        "You have not submitted this request yet. Only you can see it.",
    ),
    "submitted": (
        "Submitted",
        "Your request has been received and is waiting to be picked up for review.",
    ),
    "under_review": (
        "Under review",
        "Your request is being assessed. Nothing is needed from you yet.",
    ),
    "approved": (
        "Approved",
        "Your request has been accepted. Planning will begin shortly.",
    ),
    "planning": (
        "In planning",
        "Your event is being arranged — venue, equipment and staffing are being settled.",
    ),
    "confirmed": (
        "Confirmed",
        "Everything is arranged. Your event is going ahead on the agreed date.",
    ),
    "completed": (
        "Completed",
        "Your event has taken place and this request is now closed.",
    ),
    "cancelled": (
        "Cancelled",
        "Your event will not take place. Speak to your Event Coordinator if this is unexpected.",
    ),
    "rejected": (
        "Not approved",
        "Your request was not accepted. Your Event Coordinator can explain why.",
    ),
    "withdrawn": (
        "Withdrawn",
        "This request was taken back and will not be reviewed.",
    ),
    "postponed": (
        "Postponed",
        "Your event is on hold. A new date has not been set yet.",
    ),
}

# The value a request holds the moment it is submitted (CS-E03-S5).
INITIAL_STATUS: Final = "submitted"


def status_check_constraint() -> str:
    """Render the vocabulary as the SQL the check constraint uses.

    The migration and the model call this, so the two can never disagree about which values
    the database accepts.
    """
    values = ", ".join(f"'{status}'" for status in EVENT_REQUEST_STATUSES)
    return f"status in ({values})"


def status_label(status: str) -> str:
    """The plain-language name for a status, never the raw stored value."""
    return EVENT_REQUEST_STATUSES[status][0]


def status_explanation(status: str) -> str:
    """The one line telling the organiser what this status means for them."""
    return EVENT_REQUEST_STATUSES[status][1]

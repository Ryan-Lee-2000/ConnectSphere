"""Email copies of in-app notices (SPL-125, CS-E20).

Every new notice gains one ``email_deliveries`` row in the same transaction, so a refused or
rolled-back action leaves neither (AC5). Sending starts only after that transaction commits and
uses its own session, so a failed send can never undo the action (AC6). The row is the durable
retry queue: a background loop claims due rows, so a pending retry survives a restart, redeploy or
Render sleep (AC10), and a row that is sent or failed is never picked up again (AC9).

Every email goes to the one shared ConnectSphere address and names the person and role it was
meant for (AC3). Tests always use the ``log`` backend and never send (AC7).
"""

import base64
import html
import logging
import smtplib
import socket
import threading
import time
import weakref
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from email.message import EmailMessage

import httpx
from flask import Flask
from sqlalchemy import event, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.event_requests import SINGAPORE
from app.models import ROLE_DISPLAY_NAMES, Account, EmailDelivery, EventRequest, Notification, Role
from app.notifications import _event_link

logger = logging.getLogger(__name__)
# AC7: the log backend's emails are info records, so they must not be filtered out by default.
logger.setLevel(logging.INFO)

# AC8: the first attempt plus three retries, about a minute apart.
MAX_ATTEMPTS = 4
RETRY_DELAY = timedelta(minutes=1)
POLL_SECONDS = 15
SEND_TIMEOUT_SECONDS = 30
RUNTIME_BACKENDS = ("smtp", "gmail_api")
GMAIL_TOKEN_URL = "https://oauth2.googleapis.com/token"
GMAIL_SEND_URL = "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"

Sender = Callable[[EmailMessage], str | None]


@dataclass(frozen=True)
class EmailSettings:
    to_address: str
    base_url: str
    dispatch: Callable[[], None]


# One entry per app engine, so the session hooks know where that app's email goes.
_settings: "weakref.WeakKeyDictionary[Engine, EmailSettings]" = weakref.WeakKeyDictionary()


def _now() -> datetime:
    return datetime.now(SINGAPORE)


def register_email_delivery(app: Flask) -> None:
    """Choose the mail backend and start delivery, refusing to start when it is misconfigured."""

    config = app.config
    engine = app.extensions["engine"]
    if app.testing:
        # AC7: tests never send, whatever the developer's .env says. A test may inject a sender to
        # simulate failures, in the same way IDENTITY_VERIFIER replaces sign-in.
        sender = config.get("EMAIL_SENDER", log_sender)
        to_address = config.get("NOTIFICATION_EMAIL_TO") or "notices@example.test"
        base_url = config.get("APP_BASE_URL") or "http://127.0.0.1:5173"
    else:
        sender = _runtime_sender(config)
        to_address = config["NOTIFICATION_EMAIL_TO"]
        base_url = config["APP_BASE_URL"]

    def deliver() -> int:
        return process_due_emails(engine, sender)

    if app.testing:
        # The first attempt runs as soon as the action commits; retries are driven by the test.
        dispatch = deliver
    else:
        worker = _Worker(deliver)
        worker.start()
        dispatch = worker.wake
    _settings[engine] = EmailSettings(to_address, base_url.rstrip("/"), dispatch)
    app.extensions["process_due_emails"] = deliver


def _runtime_sender(config) -> Sender:
    backend = (config.get("EMAIL_BACKEND") or "").strip()
    missing = [key for key in ("NOTIFICATION_EMAIL_TO", "APP_BASE_URL") if not config.get(key)]
    if backend not in RUNTIME_BACKENDS:
        raise RuntimeError(
            "EMAIL_BACKEND must be smtp (local Mailpit) or gmail_api (Render). "
            "Run npm run setup; see .env.example."
        )
    if config.get("RENDER") and backend != "gmail_api":
        raise RuntimeError("EMAIL_BACKEND must be gmail_api on Render.")
    if backend == "gmail_api":
        missing += [
            key
            for key in ("GMAIL_CLIENT_ID", "GMAIL_CLIENT_SECRET", "GMAIL_REFRESH_TOKEN")
            if not config.get(key)
        ]
    if missing:
        raise RuntimeError(f"Email settings missing: {', '.join(missing)}. See .env.example.")
    if backend == "gmail_api":
        return GmailSender(
            config["GMAIL_CLIENT_ID"], config["GMAIL_CLIENT_SECRET"], config["GMAIL_REFRESH_TOKEN"]
        )
    host, port = config["SMTP_HOST"], int(config["SMTP_PORT"])
    try:
        socket.create_connection((host, port), timeout=3).close()
    except OSError as error:
        raise RuntimeError(
            f"Mailpit is not reachable at {host}:{port}. Start local Supabase (npm run setup)."
        ) from error
    return SmtpSender(host, port)


def log_sender(message: EmailMessage) -> None:
    logger.info("Email not sent (log backend):\n%s", message.as_string())


class SmtpSender:
    """Local development: deliver to Supabase's Mailpit, which never delivers externally."""

    def __init__(self, host: str, port: int):
        self.host, self.port = host, port

    def __call__(self, message: EmailMessage) -> None:
        with smtplib.SMTP(self.host, self.port, timeout=SEND_TIMEOUT_SECONDS) as smtp:
            smtp.send_message(message)


class GmailSender:
    """Render: the Gmail API over HTTPS, because the free tier blocks outbound SMTP ports."""

    def __init__(self, client_id: str, client_secret: str, refresh_token: str):
        self._grant = {
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        }
        self._token: str | None = None
        self._expires = 0.0
        self._lock = threading.Lock()

    def __call__(self, message: EmailMessage) -> str:
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
        response = httpx.post(
            GMAIL_SEND_URL,
            headers={"Authorization": f"Bearer {self._access_token()}"},
            json={"raw": raw},
            timeout=SEND_TIMEOUT_SECONDS,
        )
        if response.status_code == 401:
            self._token = None
        response.raise_for_status()
        return response.json()["id"]

    def _access_token(self) -> str:
        with self._lock:
            if self._token is None or time.monotonic() >= self._expires:
                response = httpx.post(GMAIL_TOKEN_URL, data=self._grant, timeout=10)
                response.raise_for_status()
                body = response.json()
                self._token = body["access_token"]
                self._expires = time.monotonic() + int(body.get("expires_in", 3600)) - 60
            return self._token


@event.listens_for(Session, "before_flush")
def _queue_emails(session: Session, _context, _instances) -> None:
    notices = [obj for obj in session.new if isinstance(obj, Notification)]
    for notice in notices:
        # AC3a: every notice names the role it was sent for; there is no default role.
        if not notice.recipient_role:
            raise ValueError("A notification must name the role it was sent for.")
    settings = _settings.get(session.get_bind()) if notices else None
    if settings is None:
        return
    with session.no_autoflush:
        for notice in notices:
            session.add(_render(session, notice, settings))
    # The dispatch itself is kept, not a flag: when the app is loaded as backend.app (npm start)
    # this module is imported twice, and whichever copy's hook runs first must start delivery.
    session.info["spl125_email_dispatch"] = settings.dispatch


@event.listens_for(Session, "after_commit")
def _send_after_commit(session: Session) -> None:
    # AC2: the first attempt follows the save. Sending never runs inside the action's own
    # transaction, so a failed send cannot undo it (AC6).
    dispatch = session.info.pop("spl125_email_dispatch", None)
    if dispatch is not None:
        try:
            dispatch()
        except Exception:
            logger.exception("Email dispatch failed; the retry loop will pick it up.")


@event.listens_for(Session, "after_rollback")
def _forget_queued(session: Session) -> None:
    session.info.pop("spl125_email_dispatch", None)


def _render(session: Session, notice: Notification, settings: EmailSettings) -> EmailDelivery:
    recipient = session.get(Account, notice.recipient_account_id)
    event_name = session.get(EventRequest, notice.event_request_id).name
    name = _one_line(recipient.display_name)
    role = ROLE_DISPLAY_NAMES[Role(notice.recipient_role)]
    created = notice.created_at
    when = (created if created.tzinfo else created.replace(tzinfo=SINGAPORE)).astimezone(SINGAPORE)
    when_text = f"{when:%a} {when.day} {when:%b %Y}, {when:%H:%M} SGT"
    link = settings.base_url + _event_link(notice)
    # AC3: the subject and the first line name the intended recipient and their role. AC4: the
    # event, the in-app wording, Singapore time and the same page as the in-app notice.
    lines = [
        ("Event", event_name),
        ("What changed", notice.message),
        ("When", when_text),
        ("Open", link),
    ]
    heading = f"For {name} ({role})"
    body_text = "\n".join(
        [heading, "", *(f"{label}: {value}" for label, value in lines), "", _footer(role)]
    )
    body_html = (
        f"<p><strong>{html.escape(heading)}</strong></p>"
        f"<p>Event: {html.escape(event_name)}<br>"
        f"What changed: {html.escape(notice.message)}<br>"
        f"When: {html.escape(when_text)}</p>"
        f'<p><a href="{html.escape(link)}">Open in ConnectSphere</a></p>'
        f"<p>{html.escape(_footer(role))}</p>"
    )
    return EmailDelivery(
        notification=notice,
        recipient_account_id=notice.recipient_account_id,
        recipient_name=name,
        recipient_role=notice.recipient_role,
        to_address=settings.to_address,
        subject=f"[ConnectSphere] {heading}: {_one_line(event_name)}",
        body_text=body_text,
        body_html=body_html,
        status="pending",
        attempts=0,
        next_attempt_at=notice.created_at,
        created_at=notice.created_at,
    )


def _footer(role: str) -> str:
    return f"You received this ConnectSphere notice as {role}."


def _one_line(value: str) -> str:
    # Header values cannot hold line breaks.
    return " ".join(value.split())


def process_due_emails(engine: Engine, sender: Sender, now: datetime | None = None) -> int:
    """Attempt every pending email that is due, one row and one transaction at a time.

    Each row stays locked while its attempt runs, so a second worker skips it rather than sending
    it again (AC9, AC10). Returns the number of attempts made.
    """

    attempts = 0
    while True:
        moment = now or _now()
        with Session(engine) as session:
            delivery = session.scalars(
                select(EmailDelivery)
                .where(EmailDelivery.status == "pending", EmailDelivery.next_attempt_at <= moment)
                .order_by(EmailDelivery.next_attempt_at, EmailDelivery.id)
                .limit(1)
                .with_for_update(skip_locked=True)
            ).first()
            if delivery is None:
                return attempts
            _attempt(delivery, sender, moment)
            session.commit()
            attempts += 1


def _attempt(delivery: EmailDelivery, sender: Sender, now: datetime) -> None:
    delivery.attempts += 1
    try:
        provider_id = sender(_message(delivery))
    except Exception as error:
        delivery.last_error = f"{type(error).__name__}: {error}"[:2000]
        if delivery.attempts >= MAX_ATTEMPTS:
            # AC8: one final outcome; nothing reached the inbox.
            delivery.status, delivery.failed_at, delivery.next_attempt_at = "failed", now, None
            logger.warning("Email %s failed after %s attempts.", delivery.id, delivery.attempts)
        else:
            delivery.next_attempt_at = now + RETRY_DELAY
        return
    delivery.status, delivery.sent_at, delivery.next_attempt_at = "sent", now, None
    delivery.provider_message_id = provider_id
    delivery.last_error = None


def _message(delivery: EmailDelivery) -> EmailMessage:
    message = EmailMessage()
    message["Subject"] = delivery.subject
    # One shared address is both the sender and the inbox (team decision, 24 Oct 2026).
    message["From"] = f"ConnectSphere <{delivery.to_address}>"
    message["To"] = delivery.to_address
    # A fixed id per email, so every attempt of one email is the same message.
    message["Message-ID"] = f"<connectsphere-email-{delivery.id}@connectsphere.local>"
    tags = [ROLE_DISPLAY_NAMES[Role(delivery.recipient_role)]]
    if delivery.attempts > 1:
        tags += ["retried", f"attempt {delivery.attempts}"]
    # Mailpit shows these as tags, so a retried email stands out locally.
    message["X-Tags"] = ", ".join(tags)
    message.set_content(delivery.body_text)
    message.add_alternative(delivery.body_html, subtype="html")
    return message


class _Worker:
    """Retries due emails in the background; ``wake`` runs it at once after a new notice."""

    def __init__(self, deliver: Callable[[], int]):
        self._deliver = deliver
        self._event = threading.Event()

    def start(self) -> None:
        # AC10: anything left pending by a restart, redeploy or sleep runs straight away.
        self._event.set()
        threading.Thread(target=self._run, name="email-delivery", daemon=True).start()

    def wake(self) -> None:
        self._event.set()

    def _run(self) -> None:
        while True:
            self._event.wait(POLL_SECONDS)
            self._event.clear()
            try:
                self._deliver()
            except Exception:
                logger.exception("Email delivery loop failed; it will try again.")

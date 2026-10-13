"""Delivery channels. Each raises NotifierError on failure, with no secrets in the message."""

from __future__ import annotations
import smtplib
import ssl
import sys
from email.message import EmailMessage
from typing import List, Optional, Protocol

import httpx

from src.core.config import Settings
from src.engine.alerts import Alert
from src.notify.format import format_telegram, format_text, subject_line


class NotifierError(Exception):
    pass


class Notifier(Protocol):
    name: str

    def send(self, alerts: List[Alert]) -> None: ...


class ConsoleNotifier:
    name = "console"

    def send(self, alerts: List[Alert]) -> None:
        print(f"\n=== {subject_line(alerts)} ===\n{format_text(alerts)}\n")
        sys.stdout.flush()


class TelegramNotifier:
    name = "telegram"

    def __init__(self, bot_token: str, chat_id: str, client: Optional[httpx.Client] = None):
        self._url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        self._chat_id = chat_id
        self._client = client or httpx.Client(timeout=httpx.Timeout(30.0, connect=10.0))

    def send(self, alerts: List[Alert]) -> None:
        for text in format_telegram(alerts):
            try:
                resp = self._client.post(self._url, json={
                    "chat_id": self._chat_id,
                    "text": text,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": True,
                })
            except httpx.HTTPError as exc:
                # str(exc) can contain the URL, which contains the bot token.
                raise NotifierError(f"Telegram request failed ({type(exc).__name__})") from None
            if resp.status_code != 200:
                try:
                    detail = str(resp.json().get("description", ""))[:200]
                except ValueError:
                    detail = ""
                raise NotifierError(f"Telegram returned HTTP {resp.status_code} {detail}".strip())


class EmailNotifier:
    name = "email"

    def __init__(self, host: str, port: int, user: Optional[str], password: Optional[str],
                 sender: str, recipients: List[str]):
        self.host, self.port = host, port
        self.user, self.password = user, password
        self.sender, self.recipients = sender, recipients

    def build_message(self, alerts: List[Alert]) -> EmailMessage:
        msg = EmailMessage()
        msg["Subject"] = subject_line(alerts)
        msg["From"] = self.sender
        msg["To"] = ", ".join(self.recipients)
        msg.set_content(format_text(alerts))
        return msg

    def send(self, alerts: List[Alert]) -> None:
        msg = self.build_message(alerts)
        # smtplib's default context skips certificate checks; verify so the password can't leak.
        context = ssl.create_default_context()
        try:
            if self.port == 465:
                smtp = smtplib.SMTP_SSL(self.host, self.port, timeout=30, context=context)
            else:
                smtp = smtplib.SMTP(self.host, self.port, timeout=30)
                smtp.starttls(context=context)
            with smtp:
                if self.user and self.password:
                    smtp.login(self.user, self.password)
                smtp.send_message(msg)
        except (smtplib.SMTPException, OSError) as exc:
            raise NotifierError(f"Email send failed ({type(exc).__name__})") from None


def notifiers_from_settings(settings: Settings) -> List[Notifier]:
    """Every channel whose settings are filled in. Empty list means no alerts can be delivered."""
    channels: List[Notifier] = []
    if settings.telegram_bot_token and settings.telegram_chat_id:
        channels.append(TelegramNotifier(settings.telegram_bot_token, settings.telegram_chat_id))
    recipients = [a.strip() for a in (settings.alert_email_to or "").split(",") if a.strip()]
    if settings.smtp_host and recipients:
        channels.append(EmailNotifier(
            host=settings.smtp_host,
            port=settings.smtp_port,
            user=settings.smtp_user,
            password=settings.smtp_password,
            sender=settings.alert_email_from or settings.smtp_user or recipients[0],
            recipients=recipients,
        ))
    return channels

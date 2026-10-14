import logging
import smtplib
import ssl
from email.message import EmailMessage

logger = logging.getLogger("nanocas")

# Without an explicit timeout `smtplib.SMTP()` falls back to
# `socket._GLOBAL_DEFAULT_TIMEOUT`, which is effectively infinite. Alerts
# are dispatched from a background thread (see alerts.Notifier), but a
# bounded timeout still matters so the thread pool can't fill up with
# stuck connections. See LOGBOOK section 4.2.
_SMTP_TIMEOUT_SECONDS = 30

# Port 465 is implicit TLS (SMTPS); everything else (25, 587, 2525) is
# plain-then-STARTTLS. The previous code always issued STARTTLS, which
# fails on 465 with "Connection unexpectedly closed".
_IMPLICIT_TLS_PORTS = {465}


def send_email(subject: str, body: str, config: dict) -> tuple[bool, str | None]:
    """Send one plain-text e-mail. Returns ``(ok, error_message)``.

    ``config`` keys: sender, recipient, smtpServer, smtpPort, password.
    ``smtpPort`` may arrive as a string from the web form.
    """
    try:
        sender = config["sender"]
        password = config["password"]
        recipient = config["recipient"]
        smtp_server = config["smtpServer"]
        smtp_port = int(config["smtpPort"])
    except (KeyError, TypeError, ValueError) as exc:
        logger.error(f"Email configuration invalid: {exc}")
        return False, f"invalid email configuration: {exc}"

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = recipient
    msg.set_content(body)

    context = ssl.create_default_context()
    try:
        if smtp_port in _IMPLICIT_TLS_PORTS:
            with smtplib.SMTP_SSL(smtp_server, smtp_port, timeout=_SMTP_TIMEOUT_SECONDS,
                                  context=context) as server:
                server.login(sender, password)
                server.send_message(msg)
        else:
            with smtplib.SMTP(smtp_server, smtp_port, timeout=_SMTP_TIMEOUT_SECONDS) as server:
                server.ehlo()
                if server.has_extn("starttls"):
                    server.starttls(context=context)
                    server.ehlo()
                server.login(sender, password)
                server.send_message(msg)
        logger.info(f"Email sent to {recipient}")
        return True, None
    except Exception as exc:  # noqa: BLE001
        logger.error(f"Failed to send email: {exc}")
        return False, str(exc)

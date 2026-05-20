import smtplib
from email.message import EmailMessage
import logging
import ssl

logger = logging.getLogger("nanocas")

# Without an explicit timeout `smtplib.SMTP()` falls back to
# `socket._GLOBAL_DEFAULT_TIMEOUT`, which is effectively infinite. The
# alert path is called synchronously from the watchdog dispatcher thread,
# so a slow / unreachable SMTP server would block every subsequent FASTQ
# from being processed. 30 s is generous for a TLS handshake + login but
# still short enough that the system fails gracefully. See LOGBOOK §4.2.
_SMTP_TIMEOUT_SECONDS = 30


def send_email(subject, body, config):
    try:
        sender = config["sender"]
        password = config["password"]
        recipient = config["recipient"]
        smtp_server = config["smtpServer"]
        smtp_port = config["smtpPort"]

        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = sender
        msg["To"] = recipient
        msg.set_content(body)

        context = ssl.create_default_context()

        with smtplib.SMTP(smtp_server, smtp_port, timeout=_SMTP_TIMEOUT_SECONDS) as server:
            server.starttls(context=context)
            server.login(sender, password)
            server.send_message(msg)
        logger.info(f"Email sent to {recipient}")

    except Exception as e:
        logger.error(f"Failed to send email: {e}")
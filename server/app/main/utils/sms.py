import logging
import os

from dotenv import load_dotenv
from twilio.base.exceptions import TwilioRestException
from twilio.http.http_client import TwilioHttpClient
from twilio.rest import Client

load_dotenv()

logger = logging.getLogger('nanocas')

# Twilio's default http_client uses a requests.Session with no timeout,
# so a stalled Twilio API would hang the calling thread indefinitely.
# Module-level singleton so we don't pay the requests.Session setup cost
# on every alert. See LOGBOOK section 4.2.
_TWILIO_TIMEOUT_SECONDS = 30
_TWILIO_HTTP_CLIENT = TwilioHttpClient(timeout=_TWILIO_TIMEOUT_SECONDS)

# Twilio hard-limits a single SMS segment; long alert texts are split
# into several segments and billed per segment. Cap the body so an
# alert never costs more than two segments.
_MAX_SMS_CHARS = 300


def twilio_configured() -> bool:
    return all(os.getenv(k) for k in ('TWILIO_ACCOUNT_SID', 'TWILIO_AUTH_TOKEN', 'TWILIO_PHONE_NUMBER'))


def send_sms(body: str, recipient_phone: str) -> tuple[bool, str | None]:
    """Send one SMS through Twilio. Returns ``(ok, error_message)``."""
    account_sid = os.getenv('TWILIO_ACCOUNT_SID')
    auth_token = os.getenv('TWILIO_AUTH_TOKEN')
    twilio_phone = os.getenv('TWILIO_PHONE_NUMBER')

    if not all([account_sid, auth_token, twilio_phone]):
        logger.error("Twilio credentials missing (TWILIO_ACCOUNT_SID / TWILIO_AUTH_TOKEN / "
                     "TWILIO_PHONE_NUMBER). SMS not sent.")
        return False, "Twilio credentials are not configured on the server"
    if not recipient_phone:
        logger.error("SMS recipient phone missing. SMS not sent.")
        return False, "no recipient phone number"

    if len(body) > _MAX_SMS_CHARS:
        body = body[:_MAX_SMS_CHARS - 1] + '…'

    try:
        client = Client(account_sid, auth_token, http_client=_TWILIO_HTTP_CLIENT)
        message = client.messages.create(body=body, from_=twilio_phone, to=recipient_phone)
        logger.info(f"SMS sent successfully: {message.sid}")
        return True, None
    except TwilioRestException as exc:
        logger.error(f"Failed to send SMS: {exc}")
        return False, str(exc)
    except Exception as exc:  # noqa: BLE001
        logger.error(f"Unexpected error sending SMS: {exc}")
        return False, str(exc)

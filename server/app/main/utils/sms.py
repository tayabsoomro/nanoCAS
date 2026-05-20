import os
from twilio.rest import Client
from twilio.base.exceptions import TwilioRestException
from twilio.http.http_client import TwilioHttpClient
import logging
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger('nanocas')

# Twilio's default http_client uses a requests.Session with no timeout,
# so a stalled Twilio API would hang the watchdog dispatcher indefinitely.
# Module-level singleton so we don't pay the requests.Session setup cost
# on every alert. See LOGBOOK §4.2.
_TWILIO_TIMEOUT_SECONDS = 30
_TWILIO_HTTP_CLIENT = TwilioHttpClient(timeout=_TWILIO_TIMEOUT_SECONDS)


def send_sms(body, recipient_phone):
    account_sid = os.getenv('TWILIO_ACCOUNT_SID')
    auth_token = os.getenv('TWILIO_AUTH_TOKEN')
    twilio_phone = os.getenv('TWILIO_PHONE_NUMBER')

    if not all([account_sid, auth_token, twilio_phone, recipient_phone]):
        logger.error("Twilio configuration or recipient phone missing. SMS not sent.")
        return

    try:
        client = Client(account_sid, auth_token, http_client=_TWILIO_HTTP_CLIENT)
        message = client.messages.create(
            body=body,
            from_=twilio_phone,
            to=recipient_phone
        )
        logger.info(f"SMS sent successfully: {message.sid}")
    except TwilioRestException as e:
        logger.error(f"Failed to send SMS: {e}")
    except Exception as e:
        logger.error(f"Unexpected error sending SMS: {e}")
"""
Twilio client — SMS, WhatsApp, status callbacks, inbound handling.
Credentials loaded from config (TWILIO_ACCOUNT_SID / TWILIO_AUTH_TOKEN / TWILIO_FROM_NUMBER).
"""
from __future__ import annotations
import logging
from typing import Optional

import config

logger = logging.getLogger(__name__)

# ── Lazy client ───────────────────────────────────────────────────────────────

_client = None


def _get_client():
    global _client
    if _client is None:
        from twilio.rest import Client
        if not config.TWILIO_ACCOUNT_SID or not config.TWILIO_AUTH_TOKEN:
            raise RuntimeError("TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN must be set.")
        _client = Client(config.TWILIO_ACCOUNT_SID, config.TWILIO_AUTH_TOKEN)
    return _client


def _is_configured() -> bool:
    return bool(config.TWILIO_ACCOUNT_SID and config.TWILIO_AUTH_TOKEN and config.TWILIO_FROM_NUMBER)


# ── SMS ───────────────────────────────────────────────────────────────────────

def send_sms(
    to: str,
    body: str,
    from_: str = None,
    status_callback: str = None,
) -> dict:
    """
    Send a single SMS. Returns {"sid": ..., "status": ..., "to": ...}.
    Raises on failure.
    """
    client = _get_client()
    from_number = from_ or config.TWILIO_FROM_NUMBER

    kwargs = {"body": body, "from_": from_number, "to": to}
    if status_callback:
        kwargs["status_callback"] = status_callback

    msg = client.messages.create(**kwargs)
    return {"sid": msg.sid, "status": msg.status, "to": msg.to}


def send_sms_bulk(
    contacts: list[dict],
    body_template: str,
    status_callback: str = None,
) -> tuple[int, int, list[str]]:
    """
    Send SMS to a list of contacts. Template supports {{name}} substitution.
    contacts: [{"phone": "+1...", "name": "..."}, ...]
    Returns (sent_count, failed_count, error_list).
    """
    if not _is_configured():
        raise RuntimeError("Twilio credentials not configured.")

    sent, failed, errors = 0, 0, []
    for contact in contacts:
        try:
            body = body_template.replace("{{name}}", contact.get("name") or "")
            send_sms(to=contact["phone"], body=body, status_callback=status_callback)
            sent += 1
        except Exception as e:
            failed += 1
            errors.append(f"{contact.get('phone', '?')}: {e}")
            logger.warning("SMS to %s failed: %s", contact.get("phone"), e)

    return sent, failed, errors


# ── WhatsApp ──────────────────────────────────────────────────────────────────

def send_whatsapp(
    to: str,
    body: str,
    media_url: str = None,
) -> dict:
    """
    Send a WhatsApp message via Twilio.
    to must be in format: +1234567890 (Twilio adds whatsapp: prefix).
    Returns {"sid": ..., "status": ..., "to": ...}.
    """
    client = _get_client()
    from_wa = f"whatsapp:{config.TWILIO_FROM_NUMBER}"
    to_wa = f"whatsapp:{to}" if not to.startswith("whatsapp:") else to

    kwargs = {"body": body, "from_": from_wa, "to": to_wa}
    if media_url:
        kwargs["media_url"] = [media_url]

    msg = client.messages.create(**kwargs)
    return {"sid": msg.sid, "status": msg.status, "to": msg.to}


def send_whatsapp_bulk(
    contacts: list[dict],
    body_template: str,
    media_url: str = None,
) -> tuple[int, int, list[str]]:
    """
    Send WhatsApp messages to a list of contacts.
    contacts: [{"phone": "+1...", "name": "..."}, ...]
    Returns (sent_count, failed_count, error_list).
    """
    if not _is_configured():
        raise RuntimeError("Twilio credentials not configured.")

    sent, failed, errors = 0, 0, []
    for contact in contacts:
        try:
            body = body_template.replace("{{name}}", contact.get("name") or "")
            send_whatsapp(to=contact["phone"], body=body, media_url=media_url)
            sent += 1
        except Exception as e:
            failed += 1
            errors.append(f"{contact.get('phone', '?')}: {e}")
            logger.warning("WhatsApp to %s failed: %s", contact.get("phone"), e)

    return sent, failed, errors


# ── Message status lookup ─────────────────────────────────────────────────────

def get_message_status(sid: str) -> dict:
    """Fetch current status of a message by SID."""
    client = _get_client()
    msg = client.messages(sid).fetch()
    return {
        "sid": msg.sid,
        "to": msg.to,
        "from_": msg.from_,
        "status": msg.status,
        "error_code": msg.error_code,
        "error_message": msg.error_message,
        "date_sent": str(msg.date_sent),
        "price": msg.price,
        "price_unit": msg.price_unit,
    }


# ── Account / balance ─────────────────────────────────────────────────────────

def get_account_balance() -> dict:
    """Return Twilio account balance."""
    client = _get_client()
    balance = client.api.v2010.accounts(config.TWILIO_ACCOUNT_SID).balance.fetch()
    return {"balance": balance.balance, "currency": balance.currency}


# ── Webhook validation ────────────────────────────────────────────────────────

def validate_signature(url: str, params: dict, signature: str) -> bool:
    """
    Validate that an inbound webhook is genuinely from Twilio.
    Use in Flask route: validate_signature(request.url, request.form, request.headers.get('X-Twilio-Signature'))
    """
    from twilio.request_validator import RequestValidator
    validator = RequestValidator(config.TWILIO_AUTH_TOKEN)
    return validator.validate(url, params, signature)


# ── Inbound SMS parser ────────────────────────────────────────────────────────

def parse_inbound_sms(form: dict) -> dict:
    """
    Parse Twilio's inbound SMS webhook POST body (request.form).
    Returns normalised dict with from_, body, num_media, media_urls.
    """
    return {
        "message_sid": form.get("MessageSid"),
        "from_": form.get("From"),
        "to": form.get("To"),
        "body": form.get("Body", "").strip(),
        "num_media": int(form.get("NumMedia", 0)),
        "media_urls": [
            form.get(f"MediaUrl{i}") for i in range(int(form.get("NumMedia", 0)))
        ],
        "city": form.get("FromCity"),
        "state": form.get("FromState"),
        "country": form.get("FromCountry"),
    }

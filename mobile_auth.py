"""Stateless bearer-token auth for the mobile app.

React Native's fetch/XHR implementation doesn't reliably expose the
Set-Cookie response header to JS (it's filtered out on most platforms for
security, same as in browsers), so the mobile app can't authenticate the
same way the browser does via Flask-Login's session cookie. Instead it
gets a signed token on login/register and sends it back as
`Authorization: Bearer <token>` on every request; app.py's Flask-Login
request_loader verifies it and loads the same user Flask-Login would.

Deliberately stateless (no server-side token table) -- logout just means
the client discards the token. That's a fine tradeoff for a first mobile
release; add a revocation list here later if forced remote logout is ever
needed.
"""
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
import config

_serializer = URLSafeTimedSerializer(config.SECRET_KEY, salt="mobile-api-token")
TOKEN_MAX_AGE = 60 * 60 * 24 * 30  # 30 days


def issue_token(user_id: int) -> str:
    return _serializer.dumps({"uid": user_id})


def verify_token(token: str):
    """Return the user_id encoded in a valid, unexpired token, or None."""
    try:
        data = _serializer.loads(token, max_age=TOKEN_MAX_AGE)
        return int(data["uid"])
    except (BadSignature, SignatureExpired, KeyError, ValueError, TypeError):
        return None

"""
Shared Flask extensions — importable by app.py, auth.py, and other modules
without circular imports.
"""
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

# Limiter is created here but must be initialized with init_app() in app.py.
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["200 per minute"],
    storage_uri="memory://",
    strategy="fixed-window",
)

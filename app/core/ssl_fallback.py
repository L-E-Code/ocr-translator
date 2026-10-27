"""
Model downloads on machines with outdated certificates.

EasyOCR downloads its models through urllib. Certificates are verified normally; only when the download fails
because of the certificate check is it retried once with verification off, and only for that retry. Everything else
(update check, Groq, translators) never runs unverified.
"""
import ssl
import threading
from contextlib import contextmanager

from core.logger_config import get_logger

logger = get_logger("SSL")

_lock = threading.Lock()


def is_certificate_error(error):
    """True if the error, or something in its chain, is a failed certificate verification."""
    seen = set()
    while error is not None and id(error) not in seen:
        seen.add(id(error))
        if isinstance(error, ssl.SSLCertVerificationError) or "CERTIFICATE_VERIFY_FAILED" in str(error):
            return True
        for arg in getattr(error, "args", ()):
            if isinstance(arg, BaseException) and is_certificate_error(arg):
                return True
        error = error.__cause__ or error.__context__
    return False


@contextmanager
def unverified_https():
    """urllib's default HTTPS context without certificate verification, restored on exit (one at a time)."""
    with _lock:
        original = ssl._create_default_https_context
        ssl._create_default_https_context = ssl._create_unverified_context
        try:
            yield
        finally:
            ssl._create_default_https_context = original


def with_certificate_fallback(func, *args, **kwargs):
    """Calls func; if it fails on the certificate check, calls it once more with verification off."""
    try:
        return func(*args, **kwargs)
    except Exception as error:
        if not is_certificate_error(error):
            raise
        logger.warning("Certificate check failed during a download; retrying once without verification "
                       "(this computer probably has outdated certificates).")
    with unverified_https():
        return func(*args, **kwargs)

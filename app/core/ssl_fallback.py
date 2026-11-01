"""
Model downloads on machines with outdated certificates.

EasyOCR downloads its models through urllib. Certificates are verified normally; only when the download fails
because of the certificate check is it retried once with verification off, and only for that retry. Everything else
(update check, Groq, translators) never runs unverified.

RapidOCR downloads its models through requests. A failed certificate check is retried once against the Windows
certificate store (`truststore`), which still verifies the server: it fixes a root certificate that Python does not
know but Windows does, and never turns verification off.
"""
import ssl
import threading
from contextlib import contextmanager

from core.logger_config import get_logger

logger = get_logger("SSL")

_lock = threading.Lock()
_rapidocr_lock = threading.Lock()


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


@contextmanager
def windows_certificates_for_rapidocr():
    """
    RapidOCR's model downloads verified against the Windows certificate store, restored on exit (one at a time).
    Only the downloader of RapidOCR is replaced: every other use of `requests` keeps its own certificates.
    """
    import requests
    import truststore
    from rapidocr.utils.download_file import DownloadFile, DownloadFileException

    class SystemStoreAdapter(requests.adapters.HTTPAdapter):
        def init_poolmanager(self, *args, **kwargs):
            kwargs["ssl_context"] = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            super().init_poolmanager(*args, **kwargs)

    def request(cls, url, logger):
        session = requests.Session()
        session.mount("https://", SystemStoreAdapter())
        try:
            response = session.get(url, stream=True, timeout=cls.REQUEST_TIMEOUT)
            response.raise_for_status()
            return response
        except requests.RequestException as error:
            raise DownloadFileException(f"Failed to download {url}") from error

    with _rapidocr_lock:
        original = DownloadFile.__dict__["_make_http_request"]
        DownloadFile._make_http_request = classmethod(request)
        try:
            yield
        finally:
            DownloadFile._make_http_request = original


def rapidocr_certificate_fallback(func, *args, **kwargs):
    """Calls func (which may download RapidOCR models); on a failed certificate check, once more with the Windows store."""
    try:
        return func(*args, **kwargs)
    except Exception as error:
        if not is_certificate_error(error):
            raise
        logger.warning("Certificate check failed during a download; retrying once with the Windows certificate store.")
    with windows_certificates_for_rapidocr():
        return func(*args, **kwargs)


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

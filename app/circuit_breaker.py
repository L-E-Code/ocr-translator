import threading
import time

from logger_config import get_logger

logger = get_logger("CircuitBreaker")


class CircuitBreaker:
    """
    Stops calling a service that keeps failing, so each line does not wait for requests that will not work.

    - Closed: requests go through. A rate limit (429) opens the circuit at once; other errors open it after
      `failure_threshold` failed calls in a row.
    - Open: `allow()` is False, so the caller goes straight to its fallback. The wait grows with each reopening
      (`base_cooldown`, double, double... up to `max_cooldown`), or follows the service's `Retry-After`.
    - Half-open: once the wait is over, a single request is let through as a test. Success closes the circuit;
      failure opens it again with a longer wait.

    Every `allow()` that returns True must be followed by `record_success()` or `record_failure()`.
    """
    def __init__(self, name="service", failure_threshold=3, base_cooldown=20.0, max_cooldown=120.0, clock=time.monotonic):
        self.name = name
        self.failure_threshold = failure_threshold
        self.base_cooldown = base_cooldown
        self.max_cooldown = max_cooldown
        self._clock = clock
        self._lock = threading.Lock()
        self._failures = 0
        self._opens = 0
        self._opened_at = None
        self._cooldown = 0.0
        self._trial = False
        self.rate_limited = False  # the last time the circuit opened it was because of a rate limit

    def allow(self):
        with self._lock:
            if self._opened_at is None:
                return True
            if self._clock() - self._opened_at >= self._cooldown and not self._trial:
                self._trial = True  # half-open: only one test request at a time
                return True
            return False

    def record_success(self):
        with self._lock:
            if self._opened_at is not None:
                logger.info(f"{self.name} answered again: circuit closed.")
            self._failures = 0
            self._opens = 0
            self._opened_at = None
            self._trial = False
            self.rate_limited = False

    def record_failure(self, rate_limited=False, retry_after=None):
        with self._lock:
            self._failures += 1
            if self._opened_at is None and not rate_limited and self._failures < self.failure_threshold:
                return
            self._opens += 1
            cooldown = min(self.max_cooldown, self.base_cooldown * 2 ** (self._opens - 1))
            if retry_after:
                cooldown = min(self.max_cooldown, max(cooldown, float(retry_after)))
            self._cooldown = cooldown
            self._opened_at = self._clock()
            self._trial = False
            self.rate_limited = rate_limited
            logger.warning(f"{self.name} {'rate limited' if rate_limited else 'failing'}: "
                           f"using the backup translators for {cooldown:.0f} s.")

    @property
    def is_open(self):
        with self._lock:
            return self._opened_at is not None

    def remaining(self):
        """Seconds until the next test request (0 if the circuit is closed or the wait is over)."""
        with self._lock:
            if self._opened_at is None:
                return 0.0
            return max(0.0, self._cooldown - (self._clock() - self._opened_at))

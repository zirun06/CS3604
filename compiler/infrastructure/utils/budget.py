"""Run-wide admission and reservations shared by model and process boundaries."""

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
import math
from threading import RLock
from time import monotonic


ENV = {
    "calls": "COMPILER_BUDGET_CALLS",
    "http_attempts": "COMPILER_BUDGET_HTTP_ATTEMPTS",
    "tokens": "COMPILER_BUDGET_TOKENS",
    "seconds": "COMPILER_BUDGET_SECONDS",
}
_current = ContextVar("compilation_budget", default=None)


class BudgetExhausted(BaseException):
    """Control flow, never a repairable model/tool error or an SDK retry."""

    def __init__(self, resource, scope):
        self.resource, self.scope = resource, scope
        super().__init__(f"Budget exhausted: {resource} ({scope})")

    @property
    def time_limit(self):
        return self.resource == "seconds"


@dataclass
class Attempt:
    input_tokens: int
    output_tokens: int
    sent: bool = False
    settled: bool = False

    @property
    def tokens(self):
        return self.input_tokens + self.output_tokens


class RunBudget:
    def __init__(self, limits=None, *, clock=monotonic, stages=1, image_tokens=4096):
        self.limits = dict(limits or {})
        self.clock = clock
        self.started = clock()
        self.stages = max(1, stages)
        self.image_tokens = image_tokens
        self.future = 0
        self.reserve_final_checks = False
        self.lock = RLock()
        self.used = dict.fromkeys(("calls", "http_attempts", "tokens"), 0)
        self.reserved_http = 0
        self.reserved_tokens = 0
        self.unreported_tokens = 0
        self.denials = []
        self.denial_count = 0

    @classmethod
    def from_settings(cls, settings, stages):
        limits = {}
        for resource, name in ENV.items():
            raw = settings.get(name)
            if raw in (None, ""):
                continue
            try:
                value = float(raw) if resource == "seconds" else int(raw)
                if not math.isfinite(value) or value < 0:
                    raise ValueError
            except (ValueError, OverflowError):
                raise ValueError(f"{name} must be a finite non-negative number" +
                    (" (integer)" if resource != "seconds" else "")) from None
            limits[resource] = value
        try:
            image_tokens = int(settings.get("COMPILER_IMAGE_TOKEN_RESERVE") or 4096)
            if image_tokens < 1:
                raise ValueError
        except (TypeError, ValueError):
            raise ValueError("COMPILER_IMAGE_TOKEN_RESERVE must be a positive integer") from None
        return cls(limits, stages=stages, image_tokens=image_tokens)

    def select_stage(self, future):
        with self.lock:
            self.future = future

    def cap(self, resource):
        limit = self.limits.get(resource)
        if limit is None:
            return math.inf
        # Retain a share for later passes; unused headroom rolls forward.
        reserve = limit * .25 * self.future / self.stages
        if resource == "seconds":
            # Leave up to five seconds (10% on tiny runs) for state publication.
            return limit - min(5, limit * .1) - reserve
        return limit - math.floor(reserve)

    def deny(self, resource, scope):
        with self.lock:
            self.denial_count += 1
            if len(self.denials) < 64:
                self.denials.append({"resource": resource, "scope": scope})
        raise BudgetExhausted(resource, scope)

    def remaining_time(self, *, run_only=False):
        cap = self.cap("seconds")
        if run_only and "seconds" in self.limits:
            limit = self.limits["seconds"]
            cap = limit - min(5, limit * .1)
        return cap - (self.clock() - self.started)

    def check_time(self, *, minimum=0, run_only=False):
        remaining = self.remaining_time(run_only=run_only)
        if remaining <= minimum:
            scope = "run" if self.remaining_time(run_only=True) <= minimum else "stage"
            self.deny("seconds", scope)
        return remaining

    def check_model_time(self, *, minimum=0):
        remaining = self.check_time(minimum=minimum)
        reserve = min(30, self.limits.get("seconds", 0) * .1) if self.reserve_final_checks else 0
        if remaining <= minimum + reserve:
            self.deny("model_seconds", "final_checks")
        return remaining - reserve

    def start_call(self):
        with self.lock:
            self.check_model_time()
            if self.used["calls"] >= self.cap("calls"):
                self.deny("calls", "run" if self.used["calls"] >= self.limits["calls"] else "stage")
            self.used["calls"] += 1

    def reserve_first_call(self, input_tokens, output_tokens):
        """Reserve all three resources before a vision worker is submitted."""
        with self.lock:
            attempt = self.reserve_attempt(input_tokens, output_tokens)
            try:
                self.start_call()
            except BudgetExhausted:
                self.settle(attempt, None)
                raise
            return attempt

    def reserve_attempt(self, input_tokens, output_tokens, *, shrink=False):
        with self.lock:
            self.check_model_time()
            occupied = self.used["http_attempts"] + self.reserved_http
            if occupied >= self.cap("http_attempts"):
                self.deny("http_attempts", "run" if self.used["http_attempts"] >= self.limits["http_attempts"] else "stage")
            occupied = self.used["tokens"] + self.reserved_tokens
            free = self.cap("tokens") - occupied - input_tokens
            if free < output_tokens:
                if not shrink or free < 1:
                    hard = self.used["tokens"] + input_tokens + (1 if shrink else output_tokens)
                    self.deny("tokens", "run" if hard > self.limits["tokens"] else "stage")
                output_tokens = int(free)
            attempt = Attempt(input_tokens, output_tokens)
            self.reserved_http += 1
            self.reserved_tokens += attempt.tokens
            return attempt

    def dispatch(self, attempt):
        with self.lock:
            self.check_model_time()
            if attempt.sent or attempt.settled:
                raise RuntimeError("Attempt reservation was already consumed")
            if self.used["tokens"] + attempt.tokens > self.cap("tokens"):
                self.deny("tokens", "run" if self.used["tokens"] + attempt.tokens > self.limits["tokens"] else "stage")
            self.reserved_http -= 1
            self.used["http_attempts"] += 1
            attempt.sent = True

    def settle(self, attempt, actual):
        if attempt is None:
            return
        with self.lock:
            if attempt.settled:
                return
            attempt.settled = True
            self.reserved_tokens -= attempt.tokens
            if not attempt.sent:
                self.reserved_http -= 1
            else:
                charge = attempt.tokens if actual is None else actual
                self.used["tokens"] += charge
                if actual is None:
                    self.unreported_tokens += charge

    def snapshot(self):
        with self.lock:
            return {"limits": self.limits.copy(), "used": self.used.copy(),
                "reserved_http_attempts": self.reserved_http, "reserved_tokens": self.reserved_tokens,
                "unreported_tokens_charged": self.unreported_tokens, "denials": list(self.denials),
                "denial_count": self.denial_count, "image_token_reserve": self.image_tokens,
                "seconds_remaining": max(0, self.remaining_time(run_only=True)) if "seconds" in self.limits else None}


def active_budget():
    return _current.get()


@contextmanager
def budget_scope(budget):
    token = _current.set(budget)
    try:
        yield
    finally:
        _current.reset(token)


def budget_timeout(timeout):
    budget = active_budget()
    return min(timeout, budget.check_time()) if budget else timeout

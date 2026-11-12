"""Run-wide admission and reservations shared by model and process boundaries."""

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
import json
import math
from threading import Condition, RLock
from time import monotonic


ENV = {
    "calls": "COMPILER_BUDGET_CALLS",
    "http_attempts": "COMPILER_BUDGET_HTTP_ATTEMPTS",
    "tokens": "COMPILER_BUDGET_TOKENS",
    "seconds": "COMPILER_BUDGET_SECONDS",
}
MODEL_FAILURE_LIMIT = "COMPILER_MODEL_FAILURE_THRESHOLD"
STAGE_WEIGHTS = dict(zip((f"{i:02}" for i in range(11)), (1, 13, 14, 12, 10, 9, 12, 7, 7, 5, 10)))
OUTPUT_CAPS = {"02": 8192, "03": 6144, "04": 8192, **{f"{i:02}": 12288 for i in range(5, 11)}}


def stage_values(raw, defaults, setting):
    overrides = json.loads(raw) if raw else {}
    if (not isinstance(overrides, dict) or not set(overrides) <= set(defaults)
            or any(type(value) is not int or value < 1 for value in overrides.values())):
        raise ValueError(f"{setting} must map valid stage numbers to positive integers")
    return {**defaults, **overrides}


_current = ContextVar("compilation_budget", default=None)
_wait_for_reservations = ContextVar("wait_for_reservations", default=False)


class BudgetExhausted(BaseException):
    """Control flow, never a repairable model/tool error or an SDK retry."""

    def __init__(self, resource, scope):
        self.resource, self.scope = resource, scope
        super().__init__(f"Budget exhausted: {resource} ({scope})")

    @property
    def time_limit(self):
        return self.resource == "seconds"


class ModelCircuitOpen(BaseException):
    """Run control flow: the model connection has repeatedly failed."""

    def __init__(self, details):
        self.details = details
        super().__init__(f"Model circuit opened after {details['consecutive_failures']} consecutive failures: "
            f"{details['category']} ({details['reason']})")


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
    def __init__(self, limits=None, *, clock=monotonic, stages=1, image_tokens=4096, model_failure_threshold=3):
        self.limits = dict(limits or {})
        self.clock = clock
        self.started = clock()
        self.stages = max(1, stages)
        self.image_tokens = image_tokens
        self.future = 0
        self.stage = None
        self.stage_weights = STAGE_WEIGHTS.copy()
        self.output_caps = OUTPUT_CAPS.copy()
        self.stage_deadlines = {}
        self.design_workers = 3
        self.reserve_final_checks = False
        self.lock = RLock()
        self.changed = Condition(self.lock)
        self.used = dict.fromkeys(("calls", "http_attempts", "tokens"), 0)
        self.reserved_http = 0
        self.reserved_tokens = 0
        self.unreported_tokens = 0
        self.denials = []
        self.denial_count = 0
        self.model_failure_threshold = model_failure_threshold
        self.last_model_failure = None
        self.consecutive_model_failures = 0
        self.model_circuit = None

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
        try:
            threshold = int(settings.get(MODEL_FAILURE_LIMIT) or 3)
            if threshold < 1:
                raise ValueError
        except (TypeError, ValueError):
            raise ValueError(f"{MODEL_FAILURE_LIMIT} must be a positive integer") from None
        budget = cls(limits, stages=stages, image_tokens=image_tokens, model_failure_threshold=threshold)
        budget.stage_weights = stage_values(settings.get("COMPILER_STAGE_WEIGHTS"), STAGE_WEIGHTS, "COMPILER_STAGE_WEIGHTS")
        budget.output_caps = stage_values(settings.get("COMPILER_STAGE_OUTPUT_CAPS"), OUTPUT_CAPS, "COMPILER_STAGE_OUTPUT_CAPS")
        budget.design_workers = int(settings.get("COMPILER_OBLIGATION_WORKERS") or 3)
        if not 1 <= budget.design_workers <= 16:
            raise ValueError("COMPILER_OBLIGATION_WORKERS must be between 1 and 16")
        return budget

    def allocate_stages(self, stages):
        stages = [name[:2] for name in stages]
        limit = self.limits.get("seconds")
        if limit is not None:
            usable = limit - min(5, limit * .1)
            total = sum(self.stage_weights.get(stage, 1) for stage in stages)
            cumulative = 0
            for stage in stages:
                cumulative += self.stage_weights.get(stage, 1)
                self.stage_deadlines[stage] = usable * cumulative / total

    def output_limit(self, cap):
        return min(cap, self.output_caps.get(self.stage, cap))

    def select_stage(self, future, stage=None):
        with self.lock:
            self.future, self.stage = future, stage[:2] if stage else None

    def cap(self, resource):
        limit = self.limits.get(resource)
        if limit is None:
            return math.inf
        # Retain a share for later passes; unused headroom rolls forward.
        reserve = limit * .25 * self.future / self.stages
        if resource == "seconds":
            # Leave up to five seconds (10% on tiny runs) for state publication.
            return self.stage_deadlines.get(self.stage, limit - min(5, limit * .1) - reserve)
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

    def check_model_circuit(self):
        with self.lock:
            if self.model_circuit is not None:
                raise ModelCircuitOpen(self.model_circuit)

    def note_model_outcome(self, failure):
        """Count consecutive matching logical outcomes, across clients and stages."""
        with self.lock:
            if self.model_circuit is not None:
                return
            if failure is None:
                self.last_model_failure = None
                self.consecutive_model_failures = 0
                return
            category, reason = failure
            same = (failure == self.last_model_failure or
                (category in {"authentication", "connection"} and self.last_model_failure is not None
                    and category == self.last_model_failure[0]))
            self.consecutive_model_failures = self.consecutive_model_failures + 1 if same else 1
            self.last_model_failure = failure
            if self.consecutive_model_failures >= self.model_failure_threshold:
                self.model_circuit = {"category": category, "reason": reason, "stage": self.stage,
                    "threshold": self.model_failure_threshold, "consecutive_failures": self.consecutive_model_failures}
                self.changed.notify_all()
                raise ModelCircuitOpen(self.model_circuit)

    def check_model_time(self, *, minimum=0):
        remaining = self.check_time(minimum=minimum)
        reserve = min(30, self.limits.get("seconds", 0) * .1) if self.reserve_final_checks else 0
        if self.stage is not None and self.stage not in {"04", "06", "08", "10"}:
            reserve = 0
        if remaining <= minimum + reserve:
            self.deny("model_seconds", "final_checks")
        return remaining - reserve

    def start_call(self):
        with self.lock:
            self.check_model_circuit()
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
            except (BudgetExhausted, ModelCircuitOpen):
                self.settle(attempt, None)
                raise
            return attempt

    def reserve_attempt(self, input_tokens, output_tokens, *, shrink=False):
        with self.lock:
            while True:
                self.check_model_circuit()
                remaining = self.check_model_time()
                cap = self.cap("tokens")
                minimum = 1 if shrink else output_tokens
                need_tokens = input_tokens + minimum
                http_cap = self.cap("http_attempts")
                temporary = (self.used["http_attempts"] < http_cap <= self.used["http_attempts"] + self.reserved_http
                    or self.used["tokens"] + input_tokens + output_tokens <= cap
                    < self.used["tokens"] + self.reserved_tokens + input_tokens + output_tokens)
                if not (temporary and _wait_for_reservations.get()):
                    break
                self.changed.wait(timeout=min(remaining, 1.0))
            occupied = self.used["http_attempts"] + self.reserved_http
            if occupied >= http_cap:
                self.deny("http_attempts", "run" if self.used["http_attempts"] >= self.limits["http_attempts"] else "stage")
            free = cap - self.used["tokens"] - self.reserved_tokens - input_tokens
            if free < output_tokens:
                if not shrink or free < 1:
                    hard = self.used["tokens"] + need_tokens
                    self.deny("tokens", "run" if hard > self.limits["tokens"] else "stage")
                output_tokens = int(free)
            attempt = Attempt(input_tokens, output_tokens)
            self.reserved_http += 1
            self.reserved_tokens += attempt.tokens
            return attempt

    def dispatch(self, attempt):
        with self.lock:
            self.check_model_circuit()
            self.check_model_time()
            if attempt.sent or attempt.settled:
                raise RuntimeError("Attempt reservation was already consumed")
            if self.used["tokens"] + attempt.tokens > self.cap("tokens"):
                self.deny("tokens", "run" if self.used["tokens"] + attempt.tokens > self.limits["tokens"] else "stage")
            self.reserved_http -= 1
            self.used["http_attempts"] += 1
            attempt.sent = True
            self.changed.notify_all()

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
            self.changed.notify_all()

    def snapshot(self):
        with self.lock:
            return {"limits": self.limits.copy(), "used": self.used.copy(),
                "reserved_http_attempts": self.reserved_http, "reserved_tokens": self.reserved_tokens,
                "unreported_tokens_charged": self.unreported_tokens, "denials": list(self.denials),
                "denial_count": self.denial_count, "image_token_reserve": self.image_tokens,
                "stage_deadlines_seconds": self.stage_deadlines, "stage_output_caps": self.output_caps,
                "obligation_workers": self.design_workers,
                "model_failure_threshold": self.model_failure_threshold, "model_circuit": self.model_circuit,
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


@contextmanager
def wait_for_reservations():
    token = _wait_for_reservations.set(True)
    try:
        yield
    finally:
        _wait_for_reservations.reset(token)

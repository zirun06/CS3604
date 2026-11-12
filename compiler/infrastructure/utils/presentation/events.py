"""Append-only compiler telemetry, independent of full prompt/response logging."""

from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re

import yaml
from dotenv import dotenv_values
from threading import RLock
from time import monotonic
from uuid import uuid4

from infrastructure.shared.models.pricing import (
    load_prices,
    estimate_cost,
    normalize_usage,
)

_run = ContextVar("compiler_telemetry", default=None)
from infrastructure.utils.budget import active_budget, BudgetExhausted
from infrastructure.utils.files import save_json

_tasks = ContextVar("compiler_telemetry_task_stack", default=())
_action = ContextVar("compiler_telemetry_action", default=None)
_authoring = ContextVar("compiler_test_authoring", default=None)
_batch = ContextVar("compiler_batch", default=None)
_task = ContextVar("compiler_telemetry_task", default=None)


def timestamp():
    return datetime.now(timezone.utc).isoformat()


def totals():
    return {
        "calls": 0,
        "usage_calls": 0,
        "logical_calls": 0,
        "http_attempts": 0,
        "failed_calls": 0,
        "failed_sdk_calls": 0,
        "missing_usage_calls": 0,
        "http_missing_usage": 0,
        "reasoning_tokens": 0,
        "local_check_seconds": 0,
        "priced_calls": 0,
        "input_tokens": 0,
        "cached_input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
        "model_seconds": 0,
        "cost_cny": 0,
        "currency": "CNY",
    }


def usage_snapshot(stats):
    result = dict(stats)
    result["cost_complete"] = stats["calls"] == stats["priced_calls"]
    if stats["calls"] and not stats["priced_calls"]:
        result["cost_cny"] = None
    return result


def emit(event, **fields):
    run = _run.get()
    if run is None:
        return
    task = _task.get()
    record = {
        "event": event,
        "timestamp": timestamp(),
        "run_id": run["id"],
        "stage": run.get("stage"),
        "task_id": task["task_id"] if task else None,
        "task_span_id": task["id"] if task else None,
        "requirement_ids": task["requirement_ids"] if task else [],
        "batch_id": _batch.get(),
        **fields,
    }
    # Telemetry must not replace the compilation's original exception on I/O failure.
    try:
        with run["lock"]:
            with (run["output"] / "compilation_events.jsonl").open(
                "a", encoding="utf-8"
            ) as stream:
                stream.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError as error:
        run["logging_error"] = str(error)


def begin_run(output, input_dir, stage, settings=None):
    requirements = []
    try:
        pending = [
            yaml.safe_load(
                (input_dir / "requirements.yaml").read_text(encoding="utf-8-sig")
            )
        ]
        while pending:
            node = pending.pop()
            if not isinstance(node, dict):
                continue
            if isinstance(node.get("id"), str):
                requirements.append(node["id"])
            children = node.get("children")
            if isinstance(children, list):
                pending.extend(children)
    except (OSError, ValueError, yaml.YAMLError):
        pass
    output.mkdir(parents=True, exist_ok=True)
    defaults = dotenv_values(
        Path(__file__).resolve().parents[3] / ".env", encoding="utf-8-sig"
    ) if settings is None else {}
    settings = {**defaults, **os.environ} if settings is None else settings
    prices, source = load_prices(settings.get("COMPILER_PRICE_TABLE"))
    effort_path = output / ".arc/test_model_effort.json"
    restored_effort = json.loads(effort_path.read_text(encoding="utf-8")) if (
        stage is not None and not stage.startswith("00_") and effort_path.is_file()) else {}
    state = {
        "id": os.getenv("COMPILER_RUN_ID") or uuid4().hex,
        "output": output,
        "started_at": timestamp(),
        "started": monotonic(),
        "stage": None,
        "lock": RLock(),
        "requirements": requirements,
        "prices": prices["models"],
        "price_table": prices,
        "price_source": source,
        "test_costs": restored_effort.get("costs", {}),
        "validation_owners": {path: set(owners) for path, owners in restored_effort.get("owners", {}).items()},
        "validations": {},
        "first_feedback_seconds": None,
        "totals": totals(),
        "stage_totals": totals(),
    }
    token = _run.set(state)
    model = settings.get("MODEL") or "deepseek-flash"
    emit(
        "run_started",
        input=str(input_dir),
        output=str(output),
        selected_stage=stage,
        pid=os.getpid(),
        settings={
            "model": model,
            "stage": stage,
            "currency": "CNY",
        },
        pricing=prices, price_source=source,
    )
    return token, state["id"]


def finish_run(token, status):
    run = _run.get()
    finish_action()
    result = {
        "run_id": run["id"],
        "started_at": run["started_at"],
        "finished_at": timestamp(),
        "seconds": monotonic() - run["started"],
        "usage": usage_snapshot(run["totals"]),
        "pricing": {"source": run["price_source"], "table": run["price_table"]},
        "budget": active_budget().snapshot() if active_budget() is not None else None,
    }
    emit("run_finished", status=status, **result)
    _run.reset(token)
    return result


def begin_stage(stage):
    run = _run.get()
    if run is None:
        return None
    finish_action()
    run.update(
        stage=stage,
        stage_started=monotonic(),
        stage_started_at=timestamp(),
        stage_totals=totals(),
        validations={},
        first_feedback_seconds=None,
    )
    emit("stage_started")
    return stage


def finish_stage(stage, status):
    run = _run.get()
    if run is None or stage is None:
        return {}
    finish_action()
    result = {
        "started_at": run["stage_started_at"],
        "finished_at": timestamp(),
        "seconds": monotonic() - run["stage_started"],
        "usage": usage_snapshot(run["stage_totals"]),
        "validations": {
            key: {**counts, "pass_rate": counts["passed"] / (counts["passed"] + counts["failed"])
                if counts["passed"] + counts["failed"] else None}
            for key, counts in run["validations"].items()
        },
        "first_validation_seconds": run["first_feedback_seconds"],
    }
    if run["test_costs"]:
        save_json(run["output"] / ".arc/test_model_effort.json", {
            "costs": run["test_costs"],
            "owners": {path: sorted(owners) for path, owners in run["validation_owners"].items()},
        })
    emit("stage_finished", status=status, **result)
    run["stage"] = None
    return result


def task_metadata(label, requirement_ids=None):
    """Resolve only known IDs; shared tasks keep all owners without splitting their cost."""
    run = _run.get()
    metadata = {
        "task_id": label,
        "task_kind": "task",
        "requirement_ids": list(requirement_ids or []),
    }
    if run is None:
        return metadata
    if requirement_ids is None:
        for identity in run["requirements"]:
            if re.search(r"(?<![\w.-])" + re.escape(identity) + r"(?![\w.-])", label):
                metadata["requirement_ids"].append(identity)
    if label in run["requirements"]:
        metadata.update(task_id=label, task_kind="requirement")
        return metadata
    for filename, registry, kind in (
        ("backend_apis.json", "apis", "api"),
        ("ui_design.json", "pages", "page"),
    ):
        try:
            design = json.loads(
                (run["output"] / ".arc" / filename).read_text(encoding="utf-8-sig")
            )
        except (OSError, ValueError):
            continue
        for identity in design.get(registry, {}):
            if re.search(r"(?<![\w.-])" + re.escape(identity) + r"(?![\w.-])", label):
                metadata.update(task_id=identity, task_kind=kind)
                return metadata
    return metadata


@contextmanager
def task_scope(label, requirement_ids=None, result=None, *, batch_id=None):
    run = _run.get()
    if run is None:
        yield
        return
    if batch_id is None:
        finish_action()
    else:
        _action.set(None)
    parent = _task.get()
    task = {
        "id": uuid4().hex,
        "parent_id": parent["id"] if parent else None,
        "started": monotonic(),
        "started_at": timestamp(),
        "totals": totals(),
        **task_metadata(str(label), requirement_ids),
    }
    token = _task.set(task)
    stack = _tasks.set((*_tasks.get(), task))
    batch = _batch.set(batch_id or _batch.get())
    emit(
        "task_started",
        task_kind=task["task_kind"],
        parent_task_span_id=task["parent_id"],
    )
    status = "GREEN"
    try:
        yield
    except BaseException as error:
        status = "INTERRUPTED" if isinstance(error, KeyboardInterrupt) else "FAILED"
        raise
    finally:
        finish_action()
        if status == "GREEN" and result is not None:
            status = result.get("status", status)
        emit(
            "task_finished",
            task_kind=task["task_kind"],
            parent_task_span_id=task["parent_id"],
            status=status,
            started_at=task["started_at"],
            seconds=monotonic() - task["started"],
            usage=usage_snapshot(task["totals"]),
        )
        _batch.reset(batch)
        _tasks.reset(stack)
        _task.reset(token)


def begin_action(label):
    run = _run.get()
    if run is None:
        return
    finish_action()
    action = {
        "id": uuid4().hex,
        "label": label,
        "started": monotonic(),
        "started_at": timestamp(),
        "totals": totals(),
    }
    _action.set(action)
    emit("action_started", action_id=action["id"], action=label)


def finish_action():
    run = _run.get()
    action = _action.get()
    if run is None or action is None:
        return
    emit(
        "action_finished",
        action_id=action["id"],
        action=action["label"],
        started_at=action["started_at"],
        seconds=monotonic() - action["started"],
        usage=usage_snapshot(action["totals"]),
    )
    _action.set(None)


def model_started(call_id, model, logical_call_id):
    run = _run.get()
    if run is None:
        return
    action = _action.get()
    emit(
        "model_started",
        call_id=call_id,
        logical_call_id=logical_call_id,
        model=model,
        action_id=action["id"] if action else None,
        action=action["label"] if action else None,
    )


def _targets(run):
    action = _action.get()
    return [run["totals"], run["stage_totals"], *(task["totals"] for task in _tasks.get()),
        *([action["totals"]] if action else [])]


def model_metric(name, amount=1):
    run = _run.get()
    if run is None:
        return
    with run["lock"]:
        for target in _targets(run):
            target[name] += amount
        authoring = _authoring.get()
        if authoring is not None and name in {"logical_calls", "http_attempts", "missing_usage_calls"}:
            authoring[name] += amount


def account_usage(model, usage):
    run = _run.get()
    if run is None:
        return None, None
    normalized = normalize_usage(usage)
    amount = estimate_cost(model, normalized, run["prices"], run["price_table"]["unit_tokens"])
    names = ("input_tokens", "cached_input_tokens", "output_tokens", "reasoning_tokens", "total_tokens")
    with run["lock"]:
        for target in _targets(run):
            for name in names:
                target[name] += normalized[name] or 0
            if amount is not None:
                target["cost_cny"] += amount
        authoring = _authoring.get()
        if authoring is not None:
            for name in names:
                authoring[name] += normalized[name] or 0
    return normalized, amount


def model_finished(call_id, model, usage, seconds, status="GREEN", error=None):
    run = _run.get()
    if run is None:
        return
    normalized, amount = account_usage(model, usage)
    complete = normalized["input_tokens"] is not None and normalized["output_tokens"] is not None
    model_metric("calls")
    model_metric("model_seconds", seconds)
    model_metric("usage_calls", int(complete))
    model_metric("missing_usage_calls", int(not complete))
    model_metric("priced_calls", int(amount is not None))
    model_metric("failed_sdk_calls", int(status != "GREEN"))
    secret = os.getenv("OPENAI_API_KEY")
    if error and secret:
        error = error.replace(secret, "[REDACTED]")
    action = _action.get()
    emit("model_finished", call_id=call_id, model=model, status=status, seconds=seconds,
        usage=normalized, cost_cny=amount, currency="CNY", price=run["prices"].get(model),
        cached_usage_reported=normalized["cached_input_tokens"] is not None, error=error,
        action_id=action["id"] if action else None)


@contextmanager
def test_authoring(path, phase):
    """Charge only the test author's model calls, not validation or app repair."""
    run = _run.get()
    if run is None:
        yield
        return
    with run["lock"]:
        counts = run["test_costs"].setdefault(path, {}).setdefault(phase, totals())
        task = _task.get()
        if task:
            run["validation_owners"].setdefault(path, set()).update(task["requirement_ids"])
    token = _authoring.set(counts)
    try:
        yield
    finally:
        _authoring.reset(token)


def validation_event(kind, seconds, status, *, source="deterministic", files=(), feedback=True, only_if_absent=False, **fields):
    run = _run.get()
    if run is None:
        return
    with run["lock"]:
        if only_if_absent and kind in run["validations"]:
            return
        counts = run["validations"].setdefault(kind,
            {"count": 0, "seconds": 0, "passed": 0, "failed": 0, "not_run": 0})
        counts["count"] += 1
        counts["seconds"] += seconds
        counts[status] += 1
        if feedback and status != "not_run" and run["first_feedback_seconds"] is None and run["stage"] is not None:
            run["first_feedback_seconds"] = monotonic() - run["stage_started"]
        task = _task.get()
        owners = set(task["requirement_ids"] if task else ())
        for file in files:
            owners.update(run["validation_owners"].get(file, ()))
            if task:
                run["validation_owners"].setdefault(file, set()).update(task["requirement_ids"])
        if not owners and not files and kind in {"build", "typecheck", "startup_check", "database_check"}:
            owners.update(run["requirements"])
        effort = {}
        for phase in ("generation", "review"):
            for file in set(files):
                for name, value in run["test_costs"].get(file, {}).get(phase, {}).items():
                    if name in {"logical_calls", "http_attempts", "input_tokens", "output_tokens", "total_tokens", "missing_usage_calls"}:
                        selected = effort.setdefault(phase, {})
                        selected[name] = selected.get(name, 0) + value
    emit("validation", validation_type=kind, seconds=seconds, result=status,
        test_source=source, files=list(files), test_model_effort=effort,
        requirement_ids=sorted(owners), **fields)


def validation(kind, *, source="deterministic", selected_files=False):
    """Observe an existing check's normalized result without changing acceptance."""
    def decorate(function):
        @wraps(function)
        def observed(self, *args, **kwargs):
            started = monotonic()
            files = (args[0] if args else kwargs.get("files")) if selected_files else ()
            if selected_files and files is None:
                files = ()
            status = "failed"
            try:
                result = function(self, *args, **kwargs)
                status = "passed"
                if isinstance(result, dict):
                    if selected_files and not files and kind != "typecheck":
                        status = "not_run"
                    elif result.get("returncode") or result.get("fail") or result.get("failed") or result.get("errors") or result.get("skipped") or result.get("flaky") or result.get("todo"):
                        status = "failed"
                    elif kind in {"http_test", "ui_presence", "browser_e2e"} and not (result.get("passed") or result.get("pass")):
                        status = "not_run"
                return result
            except BudgetExhausted as error:
                status = "failed" if getattr(error, "process_started", False) else "not_run"
                raise
            finally:
                actual_source = source
                if kind == "typecheck" and files:
                    sources = {"deterministic" if str(file).startswith("frontend/tests/ui/") else "model"
                        for file in files}
                    actual_source = sources.pop() if len(sources) == 1 else "mixed"
                validation_event(kind, monotonic() - started, status, source=actual_source, files=files or (),
                    feedback=kind != "browser_install")
        return observed
    return decorate

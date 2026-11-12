"""Execute and report design batches, publishing only validated proposals."""

from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from contextlib import nullcontext

from infrastructure.shared.agent.conventions import load_conventions
from infrastructure.shared.agent.proposals import ProposalExhausted, propose_json
from infrastructure.shared.agent.tasks import TaskFailures
from infrastructure.shared.models.text import ModelOutputTruncated
from infrastructure.stages.requirements.batching import DesignPlan, packed
from infrastructure.utils.files import read_artifact, save_json
from infrastructure.utils.budget import wait_for_reservations
from infrastructure.utils.presentation.events import task_scope


MAX_REQUEST_CHARS = 96000


class DesignInputTooLarge(ValueError):
    """Split before dispatch when assembled evidence exceeds the request target."""


def check_request_size(request, count):
    if count > 1 and len(packed(request)) > MAX_REQUEST_CHARS:
        raise DesignInputTooLarge(f"Batch exceeds the {MAX_REQUEST_CHARS}-character design input target")


POLICIES = {
    "identity": "Reuse the canonical persisted identity and exact field names for the same entity across modules.",
    "session": "Keep one session identity and credential transport per authentication flow; never expose secrets in business data.",
    "naming": "Reuse accepted DB, API, page and UI symbols; coordinate shared changes instead of creating aliases or duplicates.",
    "errors": "Reuse existing status and error shapes for the same operation; preserve required no-write rejection paths.",
    "data": "Separate persistence from transient UI state and preserve the established types and relationships.",
}
OUTPUT = """\n\nBatch output: return an object containing "requirements", an object keyed by
EXACTLY the active leaf IDs. Each leaf's entry is its own complete result; preserve
its exact step IDs and do not assign effects to unrelated leaves. Shared records
may be created once and referenced from several leaves. Earlier entries in the
provided batch order can declare symbols later entries reference. If correcting
a rejection, resubmit the whole batch; no rejected changes were applied."""


def exact_keys(value, expected, label):
    if not isinstance(value, dict) or set(value) != set(expected):
        actual = set(value) if isinstance(value, dict) else set()
        raise ValueError(f"{label}: missing {sorted(set(expected) - actual)}, unexpected {sorted(actual - set(expected))}")


def check_shared_records(proposals, kinds):
    """Reject contradictory definitions of the same symbol within one proposal."""
    for kind in kinds:
        seen = {}
        for proposal in proposals.values():
            for identity, record in proposal[kind].items():
                if identity in seen and record != seen[identity]:
                    raise ValueError(f"Conflicting definitions for shared {kind}.{identity}")
                seen[identity] = record


class DesignBatches:
    def __init__(self, arc_dir, stage, console, root=None):
        self.arc_dir, self.console = arc_dir, console
        self.plan = DesignPlan(root if root is not None else read_artifact(arc_dir, "requirements.json"))
        self.stage = stage
        self.failures = TaskFailures(arc_dir, stage, console)
        self.records = []
        self.effective = []
        self._records_by_id = {}
        self.blocked_requirements = {}
        self.catalog = {}
        self.refresh_catalog()
        save_json(arc_dir / "design_batch_plan.json", self.plan.evidence())

    def refresh_catalog(self):
        """Publish the source index and accepted canonical symbols, never model guesses."""
        specs = {"db_schema": ("entities",), "backend_apis": ("apis", "modules"),
            "ui_design": ("pages", "elements"), "frontend_triggers": ("triggers",)}
        catalog = defaultdict(dict)
        for artifact, kinds in specs.items():
            path = self.arc_dir / f"{artifact}.json"
            if not path.is_file():
                continue
            value = read_artifact(self.arc_dir, path.name)
            for kind in kinds:
                for identity, record in value[kind].items():
                    catalog[kind][identity] = str(record.get("description") or record.get("name") or record.get("type") or "")[:160]
                    if kind == "entities":
                        for field in record["fields"]:
                            catalog["fields"][f"{identity}.{field}"] = identity
        self.catalog = {"policies": POLICIES,
            "source_symbols": {key: owners for key, owners in self.plan.symbols.items() if len(owners) > 1},
            "accepted_symbols": dict(catalog), "shared_conventions": load_conventions(self.arc_dir)}
        save_json(self.arc_dir / "design_catalog.json", self.catalog)

    def propose(self, batch, model, instructions, requests, accept, max_attempts, *, context_index=None,
            shared=None, output_rules=OUTPUT, log_checkpoints=True):
        active = tuple(requests)
        if not active:
            return None
        relevant = set(active).union(*(self.plan.dependencies[rid] for rid in active))
        request = {"batch": self.plan.describe(batch), "order": list(active),
            "requirements": {rid: {"evidence": self.plan.leaf_context[rid], **req} for rid, req in requests.items()},
            "shared_catalog": {**self.catalog, "source_symbols": {term: owners for term, owners
                in self.catalog["source_symbols"].items() if relevant.intersection(owners)}},
            **(shared or {})}

        def verify(proposal):
            exact_keys(proposal["requirements"], active, "Batch requirements")
            return accept(proposal)

        self._records_by_id[batch.id]["request_chars"] = len(packed(request))
        check_request_size(request, len(batch.leaves))
        result, _ = propose_json(model, instructions + output_rules, request, verify,
            self.console, batch.id, max_attempts, context_index=context_index, split_on_truncation=True,
            log_checkpoints=log_checkpoints, compact_feedback=True)
        return result

    def block(self, rid, reason):
        self.blocked_requirements[rid] = reason
        self.failures.report["tasks"][f"upstream:{rid}"] = {"status": "BLOCKED_UPSTREAM", "error": reason}

    def run(self, process, *, publish=None, workers=1, split_rejected=False):
        """Workers may compute independent results; only the caller publishes them."""
        if workers > 1 and publish is None:
            raise ValueError("Parallel design requires an explicit serial publish function")

        def register(batch):
            record = {**self.plan.describe(batch), "status": "RUNNING"}
            self.records.append(record)
            self._records_by_id[batch.id] = record
            return record

        def evaluate(batch):
            with task_scope(batch.id, batch.leaves, batch_id=batch.id), wait_for_reservations():
                return process(batch)

        pool = ThreadPoolExecutor(max_workers=workers) if workers > 1 else None

        def submit(batch):
            register(batch)
            return pool.submit(copy_context().run, evaluate, batch)

        def attempt(batch, future=None):
            record = self._records_by_id[batch.id] if future is not None else register(batch)
            with self.failures.task(batch.id):
                try:
                    result = future.result() if future is not None else evaluate(batch)
                    if publish is not None and result is not None:
                        with task_scope(batch.id, batch.leaves, batch_id=batch.id):
                            publish(batch, result)
                    if result:
                        self.refresh_catalog()
                    record["status"] = "GREEN" if result else "NOT_APPLICABLE"
                except (DesignInputTooLarge, ModelOutputTruncated, ProposalExhausted) as error:
                    rejected = isinstance(error, ProposalExhausted)
                    if rejected and (not split_rejected or len(batch.leaves) == 1):
                        raise
                    record["split_reason"] = ("invalid_proposal" if rejected else "input_size"
                        if isinstance(error, DesignInputTooLarge) else "output_truncated")
                    if len(batch.leaves) == 1:
                        record["status"] = "TRUNCATED_SINGLE_LEAF"
                        raise
                    record["status"] = "SPLIT"
                    children = self.plan.split(batch)
                    record["children"] = [child.id for child in children]
                else:
                    self.effective.append(batch)
            task = self.failures.report["tasks"][batch.id]
            if task["status"] != "GREEN":
                if record["status"] == "RUNNING":
                    record["status"] = task["status"]
                record["error"] = task["error"]
                self.effective.append(batch)
            elif record["status"] == "SPLIT":
                for child in children:
                    attempt(child, submit(child) if pool else None)

        try:
            if pool:
                jobs = [(batch, submit(batch)) for batch in self.plan.batches]
                for batch, future in jobs:
                    attempt(batch, future)
            else:
                for batch in self.plan.batches:
                    attempt(batch)
            self.failures.finish()
        finally:
            if pool:
                pool.shutdown(cancel_futures=True)
            coverage = self.plan.audit(self.effective) if self.failures.report["status"] != "RUNNING" else None
            save_json(self.arc_dir / f"design_batches_{self.stage[:2]}.json", {
                "stage": self.stage, "status": self.failures.report["status"], "workers": workers,
                "blocked_requirements": self.blocked_requirements, "attempts": self.records, "coverage": coverage})

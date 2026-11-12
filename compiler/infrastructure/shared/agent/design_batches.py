"""Execute and report design batches, publishing only validated proposals."""

from collections import defaultdict
from contextlib import nullcontext

from infrastructure.shared.agent.conventions import load_conventions
from infrastructure.shared.agent.proposals import propose_json
from infrastructure.shared.agent.tasks import TaskFailures
from infrastructure.shared.models.text import ModelOutputTruncated
from infrastructure.stages.requirements.batching import DesignPlan, packed
from infrastructure.utils.files import read_artifact, save_json
from infrastructure.utils.presentation.events import task_scope


MAX_REQUEST_CHARS = 96000


class DesignInputTooLarge(ValueError):
    """Split before dispatch when assembled evidence exceeds the request target."""


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

    def propose(self, batch, model, instructions, requests, accept, max_attempts, *, context_index=None, shared=None):
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

        self.records[-1]["request_chars"] = len(packed(request))
        if len(batch.leaves) > 1 and self.records[-1]["request_chars"] > MAX_REQUEST_CHARS:
            raise DesignInputTooLarge(f"{batch.id} exceeds the {MAX_REQUEST_CHARS}-character design input target")
        result, _ = propose_json(model, instructions + OUTPUT, request, verify,
            self.console, batch.id, max_attempts, context_index=context_index, split_on_truncation=True)
        return result

    def run(self, process):
        def visit(batch):
            record = {**self.plan.describe(batch), "status": "RUNNING"}
            self.records.append(record)
            try:
                with task_scope(batch.id, batch.leaves, batch_id=batch.id):
                    ran = process(batch)
                    if ran:
                        self.refresh_catalog()
                record["status"] = "GREEN" if ran else "NOT_APPLICABLE"
            except (DesignInputTooLarge, ModelOutputTruncated) as error:
                record["split_reason"] = "input_size" if isinstance(error, DesignInputTooLarge) else "output_truncated"
                if len(batch.leaves) == 1:
                    record["status"] = "TRUNCATED_SINGLE_LEAF"
                    raise
                record["status"] = "SPLIT"
                children = self.plan.split(batch)
                record["children"] = [child.id for child in children]
            else:
                self.effective.append(batch)
                return
            for child in children:
                attempt(child)

        def attempt(batch):
            i = len(self.records)
            with self.failures.task(batch.id):
                visit(batch)
            task = self.failures.report["tasks"][batch.id]
            if task["status"] != "GREEN":
                record = self.records[i]
                if record["status"] == "RUNNING":
                    record["status"] = task["status"]
                record["error"] = task["error"]
                self.effective.append(batch)

        try:
            for batch in self.plan.batches:
                attempt(batch)
            self.failures.finish()
        finally:
            coverage = self.plan.audit(self.effective) if self.failures.report["status"] != "RUNNING" else None
            save_json(self.arc_dir / f"design_batches_{self.stage[:2]}.json", {
                "stage": self.stage, "status": self.failures.report["status"],
                "attempts": self.records, "coverage": coverage})

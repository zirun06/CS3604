"""Group artifact work, isolate failures and preserve verified partial acceptance."""

from dataclasses import dataclass

from infrastructure.shared.agent.conventions import load_conventions
from infrastructure.shared.agent.recovery import implementation_task
from infrastructure.stages.requirements.batching import DesignPlan, packed, pack_related, split_by_size
from infrastructure.utils.files import read_artifact, save_json


@dataclass(frozen=True)
class ImplementationBatch:
    id: str
    units: tuple[str, ...]
    retained: tuple[str, ...] = ()


class ImplementationBatches:
    """Use the design plan's source index with stage-specific artifact dependencies."""

    def __init__(self, arc_dir, stage, console, *, phase="main"):
        self.arc_dir, self.stage, self.console = arc_dir, stage, console
        self.plan = DesignPlan(read_artifact(arc_dir, "requirements.json"))
        self.source = self.plan.audit(self.plan.batches)
        catalog = arc_dir / "design_catalog.json"
        self.catalog = read_artifact(arc_dir, catalog.name) if catalog.is_file() else {}
        self.owners = {}
        self.signals = {}
        self.records = []
        self.results = {}
        self.accepted = {}
        self.phase = phase

    def register(self, values, owners, signals, *, ordered=False):
        self.owners = {key: tuple(dict.fromkeys(owners.get(key, ()))) for key in values}
        self.signals = {key: set(signals.get(key, ())) for key in values}
        sizes = {key: len(packed(values[key])) for key in values}
        # Cluster connected artifacts first. For DDL, preserve the original
        # dependency-first order within each connected component.
        pending = set(values)
        identities = []
        while pending:
            current = next(key for key in values if key in pending)
            pending.remove(current)
            component = [current]
            keys = set(self.signals[current])
            while True:
                neighbors = [key for key in values if key in pending and keys & self.signals[key]]
                if not neighbors:
                    break
                for key in neighbors:
                    pending.remove(key)
                    keys.update(self.signals[key])
                    component.append(key)
            if ordered:
                members = set(component)
                identities.extend(key for key in values if key in members)
            else:
                identities.extend(component)
        self.sizes = sizes
        self.groups = [ImplementationBatch(f"{self.stage}-{self.phase}-{index:03}", items)
            for index, items in enumerate(pack_related(identities, self.signals, sizes), 1)]
        return self

    def requirement_ids(self, units):
        return list(dict.fromkeys(rid for unit in units for rid in self.owners[unit]))

    def context(self, batch, task):
        owners = self.requirement_ids(batch.units)
        return {**task, "batch_id": batch.id, "units": list(batch.units),
            "requirement_evidence": {rid: self.plan.leaf_context[rid] for rid in owners},
            "shared_catalog": {"policies": self.catalog.get("policies", {}),
                "accepted_symbols": self.catalog.get("accepted_symbols", {}),
                "shared_conventions": load_conventions(self.arc_dir)}}

    def regression(self, batch, limit=3):
        keys = set().union(*(self.signals[unit] for unit in batch.units))
        related = [unit for unit in reversed(self.accepted) if keys & self.signals[unit] and unit not in batch.retained]
        return list(dict.fromkeys([*batch.retained, *related[:limit]]))

    def run(self, process):
        def visit(batch):
            entry = {"batch_id": batch.id, "units": list(batch.units), "retained": list(batch.retained),
                "input_chars": sum(self.sizes[unit] for unit in batch.units),
                "requirements": self.requirement_ids(batch.units), "status": "RUNNING"}
            self.records.append(entry)
            passed = {}
            with implementation_task(self.arc_dir.parent, entry, self.console, batch.id, batch_id=batch.id):
                passed = process(batch, entry)
                if not passed or set(passed) - set(batch.units):
                    raise ValueError("No valid unit was accepted")
                entry.update(accepted=list(passed), pending=[unit for unit in batch.units if unit not in passed],
                    status="GREEN" if len(passed) == len(batch.units) else "PARTIAL")
            if entry["status"] in {"GREEN", "PARTIAL"}:
                self.accepted.update(passed)
                for unit, result in passed.items():
                    self.results[unit] = {**result, "status": "GREEN", "batch_id": batch.id}
            pending = tuple(unit for unit in batch.units if unit not in self.accepted)
            if not pending:
                return
            if entry["status"] != "BUDGET_EXHAUSTED" and len(batch.units) > 1:
                if len(pending) == len(batch.units):
                    parts = split_by_size(pending, self.sizes)
                    entry["split_reason"] = entry.get("error_type", "failed_acceptance")
                else:
                    parts = (pending,)
                    entry["split_reason"] = "partial_acceptance"
                retained = tuple(dict.fromkeys([*batch.retained, *passed]))
                children = [ImplementationBatch(f"{batch.id}.{i}", part, retained)
                    for i, part in enumerate(parts, 1)]
                entry["children"] = [child.id for child in children]
                for child in children:
                    siblings = tuple(unit for unit in batch.units if unit in self.accepted)
                    visit(ImplementationBatch(child.id, child.units, tuple(dict.fromkeys([*child.retained, *siblings]))))
            else:
                for unit in pending:
                    self.results[unit] = {**entry, "status": entry["status"] if entry["status"] != "PARTIAL" else "FAILED"}

        try:
            for batch in self.groups:
                visit(batch)
        finally:
            self.publish()
        return self.results

    def publish(self):
        assigned = {rid: [] for rid in self.plan.leaf_context}
        for batch in self.groups:
            for unit in batch.units:
                identity = self.results.get(unit, {}).get("batch_id", batch.id)
                for rid in self.owners[unit]:
                    if rid in assigned and identity not in assigned[rid]:
                        assigned[rid].append(identity)
        coverage = {kind: [{**{k: v for k, v in row.items() if k != "batch"},
                "batches": assigned.get(row["id"] if kind == "leaves" else row["requirement"], [])}
            for row in rows] for kind, rows in self.source.items()}
        suffix = self.stage if self.phase == "main" else f"{self.stage}_{self.phase}"
        save_json(self.arc_dir / f"implementation_batches_{suffix}.json", {"stage": self.stage,
            "phase": self.phase, "attempts": self.records, "results": self.results, "coverage": coverage})


def passing_checks(units, check, require):
    """Check suites independently so one failing suite cannot hide passing siblings."""
    passed, rejected = {}, {}
    for unit in units:
        result = None
        try:
            result = check(unit)
            require(result)
        except (ValueError, RuntimeError) as error:
            rejected[unit] = {"error": str(error), "check": result or getattr(error, "feedback", None)}
        else:
            passed[unit] = result
    return passed, rejected


def require_any(passed, rejected):
    if not passed:
        from infrastructure.shared.agent.feedback import CheckFailure
        raise CheckFailure("No unit passed the acceptance checks", rejected)

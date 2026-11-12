"""Plan bounded design batches and keep traceability back to the source tree."""

from collections import Counter, defaultdict
from dataclasses import dataclass
import json
import re


MAX_LEAVES = 6
MAX_INPUT_CHARS = 24000
DESIGN_STAGES = ("02", "03", "05", "07", "09")
REFERENCE = re.compile(r"\\ref\[(requirement|scenario|step|image)\]\(([^)]+)\)")
WORD = re.compile(r"[a-z][a-z0-9]{3,}", re.I)
COMMON = set("after before check create from into only open page should show steps that then there this update user when where will with".split())


def packed(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


@dataclass(frozen=True)
class DesignBatch:
    id: str
    module: str
    leaves: tuple[str, ...]


class DesignPlan:
    """Start at top-level modules, prefer related leaves, and cap source size."""

    def __init__(self, root, *, max_leaves=MAX_LEAVES, max_chars=MAX_INPUT_CHARS):
        if min(max_leaves, max_chars) < 1:
            raise ValueError("Batch limits must be positive")
        self.max_chars = max_chars
        self.max_leaves = max_leaves
        self.nodes = {}
        self.leaf_context = {}
        self.paths = {}
        self.scenarios = {}
        self.steps = {}
        self.size = {}
        groups = defaultdict(list)
        self.symbols = defaultdict(list)
        references = {}
        terms = {}
        modules = {}
        order = {}

        def visit(node, module, path, parents):
            rid = node["id"]
            if rid in self.nodes:
                raise ValueError(f"Duplicate requirement: {rid}")
            self.nodes[rid] = node
            self.paths[rid] = path
            modules[rid] = module
            description = node.get("description", "")
            for index, scenario in enumerate(node.get("scenarios", [])):
                sid = scenario["id"]
                key = (rid, sid)
                if key in self.scenarios:
                    raise ValueError(f"Duplicate scenario {sid} in {rid}")
                self.scenarios[key] = (index, module)
                for j, step in enumerate(scenario.get("steps", [])):
                    step_id = step["id"]
                    if step_id in self.steps:
                        raise ValueError(f"Duplicate step: {step_id}")
                    self.steps[step_id] = (rid, sid, j, index, module)
            children = node.get("children", [])
            if children:
                parent = {k: v for k, v in node.items() if k not in ("children", "scenarios")}
                for index, child in enumerate(children):
                    visit(child, child["id"] if not path else module, (*path, index), (*parents, parent))
                return

            order[rid] = len(order)
            groups[module].append(rid)
            self.leaf_context[rid] = {"source": {k: v for k, v in node.items() if k != "children"},
                "ancestors": parents}
            source = packed(self.leaf_context[rid]["source"])
            self.size[rid] = len(packed(self.leaf_context[rid]))
            references[rid] = REFERENCE.findall(source)
            terms[rid] = {word.casefold() for word in WORD.findall(node.get("name", ""))} - COMMON
            terms[rid].update(f"{kind}:{identity}" for kind, identity in references[rid] if kind == "image")
            if isinstance(description, dict):
                for image in description.get("image", []):
                    if image.get("page"):
                        terms[rid].add("page:" + image["page"])

        visit(root, root["id"], (), ())
        for rid, names in terms.items():
            for name in sorted(names):
                self.symbols[name].append(rid)
        scenario_owners = defaultdict(set)
        for rid, sid in self.scenarios:
            scenario_owners[sid].add(rid)

        def leaf_owners(identity):
            path = self.paths.get(identity)
            if path is None:
                return set()
            return {rid for rid in self.leaf_context if self.paths[rid][:len(path)] == path}

        self.dependencies = {}
        for rid, refs in references.items():
            owners = set()
            for kind, identity in refs:
                if kind == "requirement":
                    owners.update(leaf_owners(identity))
                elif kind == "scenario":
                    for owner in scenario_owners[identity]:
                        owners.update(leaf_owners(owner))
                elif kind == "step" and identity in self.steps:
                    owners.update(leaf_owners(self.steps[identity][0]))
            self.dependencies[rid] = sorted(owners - {rid}, key=order.get)

        self.batches = []
        pending = set(order)
        while pending:
            ready = [rid for rid in order if rid in pending and pending.isdisjoint(self.dependencies[rid])]
            # A cycle is a relationship, not a reason to drop the remaining requirements.
            first = ready[0] if ready else min(pending, key=order.get)
            module = modules[first]
            batch = [first]
            pending.remove(first)
            size = self.size[first]
            while len(batch) < max_leaves:
                fits = [rid for rid in groups[module] if rid in pending and
                    size + self.size[rid] <= max_chars and pending.isdisjoint(
                        d for d in self.dependencies[rid] if modules[d] != module)]
                if not fits:
                    break
                batch_terms = set().union(*(terms[rid] for rid in batch))
                def affinity(rid):
                    links = sum(rid in self.dependencies[other] or other in self.dependencies[rid] for other in batch)
                    unresolved = sum(dep in pending for dep in self.dependencies[rid])
                    return (links, -unresolved, len(terms[rid] & batch_terms), -order[rid])
                rid = max(fits, key=affinity)
                batch.append(rid)
                pending.remove(rid)
                size += self.size[rid]
            self.batches.append(DesignBatch(f"B{len(self.batches) + 1:03}", module, tuple(batch)))

        self.audit(self.batches)

    def split(self, batch):
        """Split near half the source size, retaining order and the full leaf records."""
        leaves = batch.leaves
        return tuple(DesignBatch(batch.id + suffix, batch.module, part)
            for suffix, part in zip((".a", ".b"), split_by_size(leaves, self.size)))

    def describe(self, batch):
        size = sum(self.size[rid] for rid in batch.leaves)
        return {"id": batch.id, "module": batch.module, "leaves": list(batch.leaves),
            "input_chars": size, "oversize_single_leaf": size > self.max_chars}

    def audit(self, batches):
        actual = Counter(rid for batch in batches for rid in batch.leaves)
        if actual != Counter(self.leaf_context.keys()):
            raise ValueError("Batch coverage differs from original leaves")
        leaf_batch = {rid: b.id for b in batches for rid in b.leaves}

        def owner_batch(rid):
            if rid in leaf_batch:
                return leaf_batch[rid]
            # Parent-owned scenarios are organizational metadata, never reassigned as leaf behavior.
            path = self.paths[rid]
            return next(leaf_batch[leaf] for leaf in self.leaf_context if self.paths[leaf][:len(path)] == path)

        scenarios = [{"requirement": rid, "id": sid, "batch": owner_batch(rid),
            "source": [*self.paths[rid], "scenarios", index], "organizational": rid not in leaf_batch}
            for (rid, sid), (index, _) in self.scenarios.items()]
        steps = [{"requirement": rid, "scenario": sid, "id": step, "batch": owner_batch(rid),
            "source": [*self.paths[rid], "scenarios", index, "steps", j], "organizational": rid not in leaf_batch}
            for step, (rid, sid, j, index, _) in self.steps.items()]
        if Counter((s["requirement"], s["id"]) for s in scenarios) != Counter(self.scenarios.keys()):
            raise ValueError("Batch coverage differs from original scenarios")
        if Counter(s["id"] for s in steps) != Counter(self.steps.keys()):
            raise ValueError("Batch coverage differs from original steps")
        return {"leaves": [{"id": rid, "batch": leaf_batch[rid], "source": list(self.paths[rid]),
            "input_chars": self.size[rid]} for rid in self.leaf_context], "scenarios": scenarios, "steps": steps}

    def evidence(self):
        return {"max_leaves": self.max_leaves, "max_input_chars": self.max_chars,
            "batches": [self.describe(b) for b in self.batches], "coverage": self.audit(self.batches),
            "explicit_dependencies": {rid: deps for rid, deps in self.dependencies.items() if deps},
            "shared_symbol_candidates": {name: owners for name, owners in self.symbols.items() if len(owners) > 1}}


def split_by_size(units, sizes):
    """Keep unit order and split near half the source size."""
    if len(units) < 2:
        raise ValueError("Cannot split a single unit without changing its validation boundary")
    total = sum(sizes[unit] for unit in units)
    cut = min(range(1, len(units)), key=lambda i: abs(total - 2 * sum(sizes[key] for key in units[:i])))
    return units[:cut], units[cut:]


def pack_related(identities, signals, sizes, *, max_items=MAX_LEAVES, max_chars=MAX_INPUT_CHARS):
    """Pack adjacent related artifacts without disturbing a dependency-first order."""
    group, keys, size = [], set(), 0
    for item in identities:
        item_keys, weight = set(signals[item]), sizes[item]
        if group and (len(group) >= max_items or size + weight > max_chars or keys.isdisjoint(item_keys)):
            yield tuple(group)
            group, keys, size = [], set(), 0
        group.append(item)
        keys.update(item_keys)
        size += weight
    if group:
        yield tuple(group)

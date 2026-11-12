"""Generate offline coverage and call estimates from source YAML without loading a model."""

import argparse
from hashlib import sha256
from pathlib import Path
import sys

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from infrastructure.stages.requirements.batching import DESIGN_STAGES, DesignPlan
from infrastructure.utils.files import save_json


def counts(root):
    """Read raw ownership independently of the planner's traversal."""
    stack = [root]
    leaves, scenarios, steps, images = [], [], [], set()
    while stack:
        node = stack.pop()
        rid = node["id"]
        children = node.get("children", [])
        stack.extend(children)
        if not children:
            leaves.append(rid)
        for scenario in node.get("scenarios", []):
            sid = scenario["id"]
            scenarios.append((rid, sid))
            steps.extend((rid, sid, step["id"]) for step in scenario.get("steps", []))
        description = node.get("description", "")
        if isinstance(description, dict):
            images.update(item["reference"] for item in description.get("image", [])
                if not item["reference"].startswith(r"\ref["))
    return leaves, scenarios, steps, images


def estimates(leaves, images, batches):
    def single(n):
        return [n, n]

    new = {"00": single(0), "01": single(images), "04": [1.25 * leaves, 1.5 * leaves],
        "06": [2 * leaves, 4 * leaves], "08": [leaves, 2 * leaves], "10": single(3 * leaves)}
    new.update({stage: single(batches) for stage in DESIGN_STAGES})
    old = {**new, **{stage: single(leaves) for stage in DESIGN_STAGES}}

    def total(records):
        return [sum(bounds) for bounds in zip(*records.values())]

    return {"old_by_stage": dict(sorted(old.items())), "new_by_stage": dict(sorted(new.items())),
        "old_total": total(old), "new_total": total(new), "design_calls_saved": 5 * (leaves - batches)}


def build_evidence(source):
    raw = source.read_bytes()
    source_text = raw.decode("utf-8-sig").replace("\r\n", "\n")
    root = yaml.safe_load(source_text)
    plan = DesignPlan(root)
    evidence = plan.evidence()
    leaves, scenarios, steps, images = counts(root)
    coverage = evidence["coverage"]
    observed = ([row["id"] for row in coverage["leaves"]],
        [(row["requirement"], row["id"]) for row in coverage["scenarios"]],
        [(row["requirement"], row["scenario"], row["id"]) for row in coverage["steps"]])
    for expected, actual in zip((leaves, scenarios, steps), observed):
        if len(actual) != len(set(actual)) or sorted(expected) != sorted(actual):
            raise ValueError(f"Coverage does not match {source}")
    return {"source": f"{source.parent.name}/{source.name}", "sha256": sha256(raw).hexdigest(),
        "yaml_chars": len(source_text), "batch_count": len(plan.batches),
        "coverage_counts": {key: len(value) for key, value in coverage.items()},
        "coverage_verified": True, "reference_images": len(images), **evidence,
        "calls": estimates(len(leaves), len(images), len(plan.batches))}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("requirements_dir", type=Path)
    parser.add_argument("output_dir", type=Path)
    args = parser.parse_args()
    sources = sorted(args.requirements_dir.glob("*/requirements.yaml"))
    if not sources:
        parser.error("no */requirements.yaml inputs found")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for source in sources:
        evidence = build_evidence(source)
        target = args.output_dir / f"{source.parent.name}.json"
        save_json(target, evidence)
        assert yaml.safe_load(target.read_text(encoding="utf-8")) == evidence
        print(source.parent.name, evidence["batch_count"], evidence["coverage_counts"],
            evidence["reference_images"], evidence["calls"]["old_total"], evidence["calls"]["new_total"])


if __name__ == "__main__":
    main()

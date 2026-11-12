"""Trace original scenarios to frozen executable suites and compare repair candidates."""

from difflib import unified_diff
from hashlib import sha256
import json

from infrastructure.shared.agent.feedback import CheckFailure
from infrastructure.stages.frontend.triggers.testing import test_path
from infrastructure.utils.files import save_json


def coverage_matrix(plan, tree, ui, design, effects, obligations=None):
    """Retain all original scenario evidence, including scenarios with no executable UI."""
    entries = {}
    for rid, context in plan.leaf_context.items():
        scenarios = {}
        for scenario in context["source"].get("scenarios", []):
            sid = scenario["id"]
            steps = {}
            for raw in scenario.get("steps", []):
                step_id = raw["id"]
                step = tree.steps[step_id]
                elements = []
                for uid in ui["steps"].get(step_id, []):
                    node = ui["elements"][uid]
                    props = node.get("prop", {})
                    names = {k: props[k] for k in ("text", "label", "placeholder", "alt") if k in props}
                    elements.append({"id": uid, "role": node["type"], "names": names})
                triggers = design["steps"].get(step_id, [])
                wired = sorted({field for tid in triggers for field in effects[tid]["write"]})
                declared = (obligations or {}).get("steps", {}).get(step_id, {})
                steps[step_id] = {**{key: step[key] for key in ("Given", "When", "Then")},
                    "ui_evidence": elements, "triggers": triggers,
                    "db_writes": declared.get("write", wired), "wired_db_writes": wired,
                    "acceptance_item": f"{rid}/{sid}/{step_id}"}
            scenarios[sid] = {"name": scenario.get("name", ""), "steps": steps,
                "acceptance_item": f"{rid}/{sid}"}
        entries[rid] = {"suite": test_path(rid), "scenarios": scenarios,
            "requirement_evidence": context["source"].get("description", "")}
    return entries


def snapshot_tests(output, paths):
    return {path: (output / path).read_bytes() for path in paths}


def write_revision(output, batch, before, after, coverage, diagnostics):
    changes = []
    for rid, evidence in coverage.items():
        path = evidence["suite"]
        if path not in before or before[path] == after[path]:
            continue
        old, new = before[path], after[path]
        diff = "".join(unified_diff(old.decode("utf-8").splitlines(keepends=True),
            new.decode("utf-8").splitlines(keepends=True), "generated", "reviewed"))
        changes.append({"requirement": rid, "path": path, "before_sha256": sha256(old).hexdigest(),
            "after_sha256": sha256(new).hexdigest(), "diff": diff, "source": evidence,
            "reason": "Scheduled review of a suite that was not GREEN before implementation",
            "triggering_check": diagnostics[rid]})
    if changes:
        target = output / ".arc/acceptance/test_revisions.jsonl"
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({"batch": batch, "changes": changes}, ensure_ascii=False) + "\n")


class FrozenAcceptance:
    def __init__(self, output, batch, paths, baseline, *, zero_limit=2):
        self.output, self.batch = output, batch
        self.frozen = snapshot_tests(output, paths)
        self.best = self.state(baseline)
        self.zero_limit, self.zero_count = zero_limit, 0
        self.report = output / ".arc/acceptance" / f"{batch}.json"
        self.records = []
        self.publish()

    def publish(self):
        save_json(self.report, {"batch": self.batch,
            "files": {path: sha256(content).hexdigest() for path, content in self.frozen.items()},
            "attempts": self.records})

    def verify_files(self):
        for path, content in self.frozen.items():
            target = self.output / path
            if not target.is_file() or target.read_bytes() != content:
                raise CheckFailure("Frozen acceptance suite changed", {"file": path})

    @staticmethod
    def state(results):
        return {rid: {"cases": result.get("cases", {}), "errors": bool(result.get("errors")),
            "unstable": bool(result.get("skipped") or result.get("flaky")),
            "started": bool(result.get("cases")) and not result.get("errors") and not any(
                marker in case.get("failure", "") for case in result.get("cases", {}).values()
                for marker in ("E2E_RUNTIME_ERROR", "E2E_NETWORK_ERROR", "browserType.launch"))}
            for rid, result in results.items()}

    def evaluate(self, results, build, *, existing=False):
        """Compare test identity, passing set and real executable failure evidence."""
        self.verify_files()
        current = self.state(results)
        reason, decision = "", "REJECTED"
        previous_pass, passing = set(), set()
        for rid, previous in self.best.items():
            now = current.get(rid, {})
            if not now.get("started") or now["unstable"] or any(
                    case["status"] in {"skipped", "flaky", "invalid"} for case in now.get("cases", {}).values()):
                reason = f"{rid}: missing execution, skipped, or unstable acceptance"
                break
            if previous["cases"] and set(previous["cases"]) != set(now["cases"]):
                reason = f"{rid}: frozen test inventory changed"
                break
            previous_pass.update((rid, key) for key, case in previous["cases"].items() if case["status"] == "passed")
            passing.update((rid, key) for key, case in now["cases"].items() if case["status"] == "passed")
        if not reason and not previous_pass <= passing:
            reason = "A previously passing acceptance case regressed"
        if not reason:
            if passing - previous_pass or (existing and passing):
                decision, reason = "ACCEPTED", "New fixed cases pass" if not existing else "Existing cases remain GREEN"
            else:
                changed = any(
                    now["cases"] and {key: case.get("failure") for key, case in now["cases"].items()}
                    != {key: case.get("failure") for key, case in self.best[rid]["cases"].items()}
                    for rid, now in current.items())
                if not passing and not previous_pass and changed and self.zero_count < self.zero_limit:
                    decision, reason = "INTERMEDIATE", "Executable failure changed while no cases pass"
                else:
                    reason = "No additional fixed cases pass"
        if decision != "REJECTED":
            try:
                built = build()
                if built["returncode"]:
                    raise ValueError(built["output"])
            except (ValueError, RuntimeError) as error:
                decision, reason = "REJECTED", f"Application build failed: {error}"
        record = {"decision": decision, "reason": reason, "cases": current,
            "passing": [list(key) for key in sorted(passing)]}
        self.records.append(record)
        self.publish()
        if decision == "REJECTED":
            raise CheckFailure(reason, {"decision": record, "observed": results})
        self.best = current
        if decision == "INTERMEDIATE":
            self.zero_count += 1
        return record

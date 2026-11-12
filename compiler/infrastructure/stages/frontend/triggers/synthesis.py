"""Design requirement-scoped triggers after checking upstream API capabilities."""

from infrastructure.stages.frontend.triggers.prompts import INSTRUCTIONS
from infrastructure.stages.frontend.triggers.design import apply_decomposition, empty_triggers, relevant_pages, api_ids, validate_coverage
from infrastructure.stages.frontend.ui.design import data_symbols
from infrastructure.utils.files import save_json, read_artifact
from infrastructure.stages.database.obligation_utils import normalize_obligations
from infrastructure.shared.agent.design_batches import DesignBatches, exact_keys, check_shared_records
from infrastructure.shared.agent.discovery import ContextIndex
from infrastructure.shared.agent.conventions import load_conventions, select_conventions
from infrastructure.stages.backend.primitives import validate_design, ObligationCoverageError


def synthesize_triggers(arc_dir, ui, tree, backend, contexts, model, console, max_attempts=10):
    result = empty_triggers(tree)
    obligations = normalize_obligations(read_artifact(arc_dir, "db_obligations.json"), tree)
    conventions = load_conventions(arc_dir)
    accepted = []
    path = arc_dir / "frontend_triggers.json"
    save_json(path, result)
    batches = DesignBatches(arc_dir, "09_design_frontend_triggers", console)

    def process(batch):
        nonlocal result
        requests, apis = {}, {}
        for rid in batch.leaves:
            pages = relevant_pages(ui, rid)
            if not pages:
                continue
            try:
                validate_design({"apis": backend["apis"],
                    "requirements": {rid: backend["requirements"].get(rid, [])}},
                    obligations, complete=False, tree=tree)
            except ObligationCoverageError as error:
                raise ValueError(f"Upstream backend contract cannot cover {rid}: {error}. "
                    "Review stage 03 obligations and stage 05 API design before generating triggers.") from error
            elements = {uid for page in pages.values() for uid in page["elements"]}
            existing = {tid: trigger for tid, trigger in result["triggers"].items() if trigger["source"] in elements}
            aids = set(backend["requirements"].get(rid, [])) | {aid for trigger in existing.values() for aid in api_ids(trigger)}
            apis.update({aid: backend["apis"][aid] for aid in sorted(aids)})
            requests[rid] = {"ui": {"pages": {pid: ui["pages"][pid] for pid in pages},
                    "elements": {uid: ui["elements"][uid] for uid in sorted(elements)},
                    "requirements": {rid: ui["requirements"].get(rid, [])},
                    "steps": {sid: ui["steps"].get(sid, []) for sid in tree.own_steps[rid]}},
                "required_obligations": obligations["requirements"][rid],
                "step_obligations": {sid: obligations["steps"][sid] for sid in tree.own_steps[rid]},
                "shared_conventions": select_conventions(conventions, requirements=[rid]),
                "existing_triggers": existing, "api_ids": sorted(aids)}
        if not requests:
            return False

        def accept(proposal):
            entries = proposal["requirements"]
            candidate = result
            check_shared_records(entries, ("triggers",))
            for rid in requests:
                entry = entries[rid]
                exact_keys(entry["step_triggers"], tree.own_steps[rid], f"{rid} steps")
                candidate = apply_decomposition(candidate, entry, rid)
            validate_coverage(candidate, backend, obligations, tree, [*accepted, *requests])
            return candidate

        result = batches.propose(batch, model, INSTRUCTIONS, requests, accept, max_attempts,
            shared={"backend_apis": apis},
            context_index=ContextIndex(lambda: {"convention": conventions, "api": backend["apis"],
                "page": ui["pages"], "ui_element": ui["elements"], "ui_data": data_symbols(ui["elements"]),
                "trigger": result["triggers"]}))
        accepted.extend(requests)
        save_json(path, result)
        console.artifact("frontend_triggers", result, batch.id + " | Accepted triggers")
        return True

    batches.run(process)
    return result

"""Design reusable HTTP APIs and internal modules for batches of leaf requirements."""

from copy import deepcopy
from pathlib import Path

from infrastructure.shared.agent.conventions import load_conventions, merge_conventions
from infrastructure.shared.agent.design_batches import DesignBatches, exact_keys
from infrastructure.shared.models.text import TextModel
from infrastructure.shared.rag.backend import BackendRetriever
from infrastructure.stages.backend.context import load_context, related_schema
from infrastructure.stages.backend.design import validate_backend_design
from infrastructure.stages.backend.design_agent import API, MODULE, BACKEND_DESIGN_RULES
from infrastructure.stages.database.obligation_utils import union
from infrastructure.utils.files import save_json
from infrastructure.utils.presentation.console import DemoConsole


INSTRUCTIONS = BACKEND_DESIGN_RULES.replace("for ONE\nrequirement", "for a batch of\nrequirements").replace(
    "when associate_requirement finalizes the design", "at the end of the batch") + """
Return three keys: "apis" and "modules" mapping stable IDs to COMPLETE new or
changed contract definitions, and "requirements" mapping leaf IDs to associations.
Use the supplied contract schemas. Omit unchanged contracts. Existing contracts
may only be changed if retrieved; preserve their earlier requirement coverage.
Each association has api_ids and module_ids arrays of entry-point IDs (possibly
empty). Use optional "conventions" mapping stable IDs to new shared decisions;
reuse existing decisions exactly and omit them if unchanged. Check each leaf
against its own requirement and step obligations, rather than the batch union."""


def design_backend_apis(arc_dir: Path, pause: bool = False, top_k: int = 6, max_attempts: int = 5) -> dict:
    tree, schema, obligations = load_context(arc_dir)
    if min(top_k, max_attempts) < 1:
        raise ValueError("top_k and max_attempts must be positive")
    console, retriever = DemoConsole(pause), BackendRetriever()
    conventions = load_conventions(arc_dir)
    design = {"apis": {}, "modules": {}, "requirements": {}, "requirement_modules": {}}
    for rid in tree.requirements:
        if tree.children[rid]:
            design["requirements"][rid] = []
            design["requirement_modules"][rid] = []
    path = arc_dir / "backend_apis.json"
    save_json(path, design)
    batches = DesignBatches(arc_dir, "05_design_backend_apis", console)
    model = TextModel(json_mode=False)

    def process(batch):
        nonlocal design, conventions
        requests = {}
        retrieved = {"apis": {}, "modules": {}}
        for rid in batch.leaves:
            requirement = tree.requirements[rid]
            required = obligations["requirements"][rid]
            query = "\n".join((requirement["name"], requirement["description"], tree.concatenated_steps(rid)))
            matches = retriever.retrieve(query, required, design, top_k)
            for kind in retrieved:
                retrieved[kind].update(matches[kind])
            requests[rid] = {"required_obligations": required,
                "step_obligations": {sid: obligations["steps"][sid] for sid in tree.own_steps[rid]},
                "candidate_apis": list(matches["apis"]), "candidate_modules": list(matches["modules"])}
        records = [r["required_obligations"] for r in requests.values()] + [
            *retrieved["apis"].values(), *retrieved["modules"].values()]
        fields = union(records)
        schemas = {"apis": API, "modules": MODULE}

        def accept(proposal):
            candidate, decisions = deepcopy(design), conventions
            for kind, shape in schemas.items():
                for identity, contract in proposal[kind].items():
                    if not identity.strip():
                        raise ValueError("Contract ID must be a nonempty string")
                    if identity in design[kind] and identity not in retrieved[kind]:
                        raise ValueError(f"Cannot replace an unseen shared contract: {identity}")
                    exact_keys(contract, shape["required"], f"{kind}.{identity}")
                    candidate[kind][identity] = deepcopy(contract)
            for rid in batch.leaves:
                association = proposal["requirements"][rid]
                for key, dest in (("api_ids", "requirements"), ("module_ids", "requirement_modules")):
                    ids = association[key]
                    if not isinstance(ids, list) or any(not isinstance(item, str) for item in ids):
                        raise ValueError(f"{rid}.{key} must be an array of IDs")
                    candidate[dest][rid] = ids
                effects = requests[rid]["required_obligations"]
                changes = association.get("conventions", {})
                if isinstance(changes, dict):
                    for key, decision in changes.items():
                        if key in decisions and decision != decisions[key]["description"]:
                            raise ValueError(f"{rid} contradicts shared convention {key}; reuse the canonical decision")
                decisions = merge_conventions(decisions, association, rid, effects["read"] + effects["write"])
            validate_backend_design(candidate, schema, obligations, tree)
            return candidate, decisions

        design, conventions = batches.propose(batch, model, INSTRUCTIONS, requests, accept, min(max_attempts, 5),
            shared={"contracts": retrieved, "contract_schemas": schemas, "related_schema": related_schema(schema, [fields])})
        save_json(path, design)
        save_json(arc_dir / "shared_conventions.json", conventions)
        console.artifact("backend_apis", design, batch.id + " | Accepted APIs and modules")
        return True

    try:
        batches.run(process)
    finally:
        model.client.close()
    validate_backend_design(design, schema, obligations, tree, complete=True)
    save_json(path, design)
    return design

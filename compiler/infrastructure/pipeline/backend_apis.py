"""Design reusable HTTP APIs and internal modules for batches of leaf requirements."""

from copy import deepcopy
from pathlib import Path

from infrastructure.shared.agent.conventions import load_conventions, merge_conventions
from infrastructure.shared.agent.design_batches import DesignBatches, DesignOutputTooLarge, PartialDesign, exact_keys
from infrastructure.shared.agent.proposals import RESPONSE_ERRORS
from infrastructure.shared.models.text import ModelOutputTruncated, TextModel
from infrastructure.shared.rag.backend import BackendRetriever
from infrastructure.stages.backend.context import load_context, related_schema
from infrastructure.stages.backend.contract_records import OUTPUT, combine_records, expand_contract, read_records
from infrastructure.stages.backend.design import validate_backend_design
from infrastructure.stages.backend.design_agent import API, MODULE, BACKEND_DESIGN_RULES
from infrastructure.stages.database.obligation_utils import union
from infrastructure.utils.budget import active_budget
from infrastructure.utils.files import save_json
from infrastructure.utils.presentation.console import DemoConsole


# Give API design smaller batches than schema or obligation design.
MAX_LEAVES = 3
MAX_SOURCE_CHARS = 12000
INSTRUCTIONS = BACKEND_DESIGN_RULES.replace("for ONE\nrequirement", "for a batch of\nrequirements").replace(
    "when associate_requirement finalizes the design", "within each leaf record").replace(
    "Complete callee dependencies are\nincluded, along with connected callers needed to coordinate shared updates.",
    "Retrieved contracts include their callee dependencies.").replace(
    "read/write contain TOTAL possible persistent effects across specified branches.\n"
    "Modules additionally declare direct_read/direct_write for fields directly accessed\n"
    "by their own logic. A module's total read/write MUST equal the union of direct effects\n"
    "and all callees' total effects. APIs access the database through modules; their total\n"
    "effects MUST equal the union of their callees.",
    "Declare direct_read/direct_write for each module. The compiler derives total effects\n"
    "from these and the callee graph. APIs access the database through modules.") + """
Check each leaf against its own requirement and step obligations. Reuse existing
shared decisions exactly. Change a shared contract only if retrieved, and preserve
coverage of earlier leaves. Keep only requirement-supported HTTP and module branches.
"""

REPAIR = """
The previous attempt failed. Use correction.error and correction.details to fix
the affected records. Return all the active leaves in the same JSON Lines format.
"""


def estimate_output(requests):
    steps = sum(len(req["step_obligations"]) for req in requests.values())
    entities = {field.split(".", 1)[0] for req in requests.values()
        for effect in req["required_obligations"].values() for field in effect}
    return 400 + 850 * len(requests) + 300 * steps + 350 * len(entities)


def design_backend_apis(arc_dir: Path, pause: bool = False, top_k: int = 2, max_attempts: int = 3) -> dict:
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
    batches = DesignBatches(arc_dir, "05_design_backend_apis", console,
        plan_options={"max_leaves": MAX_LEAVES, "max_chars": MAX_SOURCE_CHARS})
    for rid, failure in obligations["unavailable"].items():
        batches.block(rid, failure["reason"])
    model = TextModel(json_mode=False)

    def process(batch):
        nonlocal design, conventions
        requests = {}
        retrieved = {"apis": {}, "modules": {}}
        schemas = {"apis": API, "modules": MODULE}
        for rid in batch.leaves:
            if rid in batches.blocked_requirements:
                continue
            requirement = tree.requirements[rid]
            required = obligations["requirements"][rid]
            query = "\n".join((requirement["name"], requirement["description"], tree.concatenated_steps(rid)))
            matches = retriever.retrieve(query, required, design, top_k)
            for kind in retrieved:
                retrieved[kind].update({identity: {key: value for key, value in contract.items() if key != "callers"}
                    for identity, contract in matches[kind].items()})
            requests[rid] = {"required_obligations": required,
                "step_obligations": {sid: obligations["steps"][sid] for sid in tree.own_steps[rid]},
                "candidate_apis": list(matches["apis"]), "candidate_modules": list(matches["modules"])}
        if not requests:
            return False
        records = [r["required_obligations"] for r in requests.values()] + [
            *retrieved["apis"].values(), *retrieved["modules"].values()]
        fields = union(records)
        estimate = estimate_output(requests)
        budget = active_budget()
        cap = budget.output_limit(model.max_output_tokens) if budget else model.max_output_tokens
        batches.record_output_estimate(batch, estimate)
        if len(requests) > 1 and estimate > cap * .75:
            raise DesignOutputTooLarge(f"Estimated {estimate} output tokens for a {cap}-token limit")

        def apply(proposal, owners):
            candidate, decisions = deepcopy(design), conventions
            for kind, shape in schemas.items():
                for identity, contract in proposal[kind].items():
                    if not identity.strip():
                        raise ValueError("Contract ID must be a nonempty string")
                    if identity in design[kind] and identity not in retrieved[kind]:
                        raise ValueError(f"Cannot replace an unseen shared contract: {identity}")
                    record = expand_contract(kind, contract)
                    record.pop("callers", None)
                    keys = set(shape["required"])
                    if "read" not in record and "write" not in record:
                        keys -= {"read", "write"}
                    exact_keys(record, keys, f"{kind}.{identity}")
                    candidate[kind][identity] = record
            for rid in owners:
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
            validate_backend_design(candidate, schema, obligations, tree, derive_effects=True)
            return candidate, decisions

        def publish(result):
            nonlocal design, conventions
            design, conventions = result
            save_json(path, design)
            save_json(arc_dir / "shared_conventions.json", conventions)
            console.artifact("backend_apis", design, batch.id + " | Accepted APIs and modules")

        def accept(response):
            if isinstance(response, dict):
                return apply(response, requests)
            proposal = combine_records(read_records(response), requests)
            return apply(proposal, requests)

        def generate(instructions, request):
            try:
                return model.generate_records(instructions, request)
            except ModelOutputTruncated as error:
                retained = []
                for record in read_records(error.content, truncated=True):
                    rid = record.get("requirement_id")
                    if not isinstance(rid, str) or rid not in requests or rid in retained:
                        continue
                    try:
                        result = apply(combine_records([record], [rid]), [rid])
                    except RESPONSE_ERRORS:
                        continue
                    publish(result)
                    retained.append(rid)
                if retained:
                    raise PartialDesign(retained) from error
                raise

        related = related_schema(schema, [fields])
        visible = {**{kind: {identity: batches.catalog["accepted_symbols"].get(kind, {}).get(identity, "")
                            for identity in contracts} for kind, contracts in retrieved.items()},
                   "entities": {name: value.get("description", "") for name, value in related.items()}}
        publish(batches.propose(batch, model, INSTRUCTIONS, requests, accept, max_attempts,
            shared={"contracts": retrieved, "related_schema": related, "estimated_output_tokens": estimate},
            output_rules=OUTPUT, accepted_symbols=visible, generate_response=generate,
            repair_instructions=REPAIR))
        return True

    try:
        batches.run(process)
    finally:
        model.client.close()
    validate_backend_design(design, schema, obligations, tree, complete=True)
    save_json(path, design)
    return design

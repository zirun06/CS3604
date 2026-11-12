"""Derive requirement and step read/write obligations against the completed schema."""

from pathlib import Path

from infrastructure.shared.agent.design_batches import DesignBatches, exact_keys
from infrastructure.shared.agent.discovery import ContextIndex
from infrastructure.shared.models.text import TextModel
from infrastructure.shared.rag.schema import SchemaRetriever
from infrastructure.stages.database.obligation_agent import OBLIGATION_INTRO, OBLIGATION_RULES
from infrastructure.stages.database.obligation_utils import check_symbols, normalize_inference, normalize_obligations
from infrastructure.stages.requirements.tree import RequirementTree
from infrastructure.utils.files import read_artifact, save_json
from infrastructure.utils.budget import active_budget
from infrastructure.utils.presentation.console import DemoConsole


def infer_db_obligations(arc_dir: Path, pause: bool = False, top_k: int = 6, max_attempts: int = 5) -> dict:
    if min(top_k, max_attempts) < 1:
        raise ValueError("top_k and max_attempts must be positive")
    root = read_artifact(arc_dir, "requirements.json")
    tree = RequirementTree(root)
    schema = read_artifact(arc_dir, "db_schema.json")
    console, retriever = DemoConsole(pause), SchemaRetriever()
    obligations = {"requirements": {}, "steps": {}}
    for rid in tree.requirements:
        if tree.children[rid]:
            obligations["requirements"][rid] = {"read": [], "write": []}
            for sid in tree.own_steps[rid]:
                obligations["steps"][sid] = {"read": [], "write": []}
    path = arc_dir / "db_obligations.json"
    save_json(path, obligations)
    batches = DesignBatches(arc_dir, "03_infer_db_obligations", console, root)
    model = TextModel(json_mode=False)
    business_rules = OBLIGATION_INTRO.replace("ONE requirement", "each leaf requirement") + OBLIGATION_RULES
    output_rules = """

Return exactly one JSON object with TWO top-level maps. Use
{"requirements":{"LEAF-ID":{"read":[],"write":[]}},"steps":{"STEP-ID":{"read":[],"write":[]}}}.
Requirements and steps are siblings. Do not nest steps inside a requirement.
Use every leaf ID in order and every ID in its expected_step_ids. Use empty read/write
arrays where appropriate and an empty steps map only when the batch has no steps.
Use only actual schema symbols and do not modify them. Query entity context if needed.
When correcting a rejection, resubmit both maps for the whole batch."""

    def process(batch):
        requests, provided = {}, {}
        for rid in batch.leaves:
            requirement = tree.requirements[rid]
            candidates = schema["requirements"].get(rid, [])
            if not isinstance(candidates, list) or any(not isinstance(field, str) for field in candidates):
                raise ValueError(f"Malformed related_fields for {rid}")
            query = "\n".join((requirement["name"], requirement["description"], tree.concatenated_steps(rid)))
            entities = set(retriever.retrieve(query, schema, top_k)["entities"])
            entities.update(field.split(".", 1)[0] for field in candidates)
            provided.update({name: schema["entities"][name] for name in sorted(entities) if name in schema["entities"]})
            requests[rid] = {"related_fields": candidates, "entity_candidates": sorted(entities),
                "expected_step_ids": tree.own_steps[rid]}

        def accept(proposal):
            reviewed = {}
            expected = [sid for rid in batch.leaves for sid in tree.own_steps[rid]]
            exact_keys(proposal.get("steps"), expected, "Top-level steps (sibling of requirements)")
            for rid in batch.leaves:
                record = normalize_inference({"requirement": proposal["requirements"][rid],
                    "steps": proposal["steps"]}, tree.own_steps[rid])
                check_symbols([record["requirement"], *record["steps"].values()], schema)
                reviewed[rid] = record
            return reviewed

        return batches.propose(batch, model, business_rules, requests, accept, min(max_attempts, 5),
            shared={"provided_entities": provided}, context_index=ContextIndex(lambda: {"entity": schema["entities"]}),
            output_rules=output_rules, log_checkpoints=False)

    def publish(batch, reviewed):
        for rid, entry in reviewed.items():
            obligations["requirements"][rid] = entry["requirement"]
            obligations["steps"].update(entry["steps"])
        save_json(path, obligations)
        console.artifact("db_obligations", obligations, batch.id + " | Accepted obligations")

    budget = active_budget()
    try:
        batches.run(process, publish=publish, workers=budget.design_workers if budget and not pause else 1,
            split_rejected=True)
    finally:
        model.client.close()
        obligations = normalize_obligations(obligations, tree, partial=True)
        save_json(path, obligations)
    return obligations

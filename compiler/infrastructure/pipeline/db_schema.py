"""Step 02: discover entities and fields in bounded requirement batches."""

from copy import deepcopy
from pathlib import Path

from infrastructure.shared.agent.design_batches import DesignBatches
from infrastructure.shared.agent.discovery import ContextIndex
from infrastructure.shared.models.text import TextModel
from infrastructure.shared.rag.schema import SchemaRetriever
from infrastructure.stages.database.schema import check_related_fields
from infrastructure.stages.database.schema_agent import create_entity, update_entity
from infrastructure.stages.requirements.tree import RequirementTree
from infrastructure.utils.files import read_artifact, save_json
from infrastructure.utils.presentation.console import DemoConsole


INSTRUCTIONS = """Extend one application's persistent SQLite schema from the supplied
requirement evidence. Reuse canonical entities and fields, including fields read
here whose creation belongs to another requirement. Only persist required data:
store password hashes and omit transient confirmation inputs. Use SQL-compatible
names and constraints supported by the requirements.

Return "entities" mapping each new or updated entity name to its definition,
plus "requirements" mapping each leaf ID to {"related_fields":["Entity.field"]}.
New entities need description and fields. New fields need description, type,
nullable, primary_key, unique, references (null or Entity.field), and constraints
(an array of strings). For an existing entity supply only changed properties and
fields. Preserve accepted names and unrelated behavior; references=null clears a
reference. Omit unchanged entities. Each related_fields list must include all
persistent fields needed by that leaf, including unchanged fields, or [] for none.
Use the entity context query if an existing symbol needs closer inspection."""


def build_db_schema(arc_dir: Path, pause: bool = False, top_k: int = 10, max_attempts: int = 5) -> dict:
    if min(top_k, max_attempts) < 1:
        raise ValueError("top_k and max_attempts must be positive")
    root = read_artifact(arc_dir, "requirements.json")
    tree, retriever = RequirementTree(root), SchemaRetriever()
    console = DemoConsole(pause)
    schema = {"entities": {}, "requirements": {}}
    path = arc_dir / "db_schema.json"
    batches = DesignBatches(arc_dir, "02_build_db_schema", console, root)
    model = TextModel(json_mode=False)

    def process(batch):
        nonlocal schema
        requests = {}
        for rid in batch.leaves:
            requirement = tree.requirements[rid]
            query = "\n".join((requirement["name"], requirement["description"], tree.concatenated_steps(rid)))
            requests[rid] = {"retrieved_entities": list(retriever.retrieve(query, schema, top_k)["entities"])}
        provided = {name: schema["entities"][name] for entry in requests.values() for name in entry["retrieved_entities"]}

        def accept(proposal):
            candidate = deepcopy(schema)
            for name, entity in proposal["entities"].items():
                apply = update_entity if name in candidate["entities"] else create_entity
                apply(candidate, name, entity)
            for rid in batch.leaves:
                fields = proposal["requirements"][rid]["related_fields"]
                check_related_fields(candidate, fields)
                candidate["requirements"][rid] = sorted(set(fields))
            return candidate

        schema = batches.propose(batch, model, INSTRUCTIONS, requests, accept, min(max_attempts, 5),
            shared={"retrieved_entities": provided}, context_index=ContextIndex(lambda: {"entity": schema["entities"]}))
        save_json(path, schema)
        console.artifact("db_schema", schema, batch.id + " | Accepted schema")
        return True

    try:
        batches.run(process)
    finally:
        model.client.close()
    return schema

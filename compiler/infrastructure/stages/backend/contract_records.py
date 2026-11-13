"""Decode complete leaf records and expand their compact contract schemas."""

from copy import deepcopy
import json


OUTPUT = """
Return JSON Lines, exactly one single-line JSON object per active leaf in order.
Finish each record before starting the next. No outer array, Markdown or commentary.
Each line has requirement_id, api_ids, module_ids, apis, modules, and optional
conventions (map stable IDs to new shared decisions). Use {} for no new contracts,
[] for no entry points. Omit unchanged definitions. A line can refer to contracts
already accepted or emitted in earlier lines; never defer its dependencies to later lines.
Example record shape:
{"requirement_id":"R1","api_ids":["A1"],"module_ids":[],"apis":{"A1":{"description":"Read a record","signature":{"name":"getRecord","method":"GET","path":"/api/records/:id"},"request":{"params":{"fields":{"id":"integer"}}},"response":{"success":[200,{"fields":{"id":"integer","title?":"string"}}]},"callees":["M1"],"precondition":[],"postcondition":[{"id":"Q1","description":"Return the requested record","status":200}]}},"modules":{"M1":{"name":"findRecord","description":"Find by persisted ID","input":{"fields":{"id":"integer"}},"output":{"fields":{"id":"integer","title?":"string"}},"direct_read":["Record.id","Record.title"],"direct_write":[],"callees":[],"precondition":[],"postcondition":[]}}}
Value schemas use a type string (string, number, integer, boolean, null, object,
array), [itemSchema] for an array, or {"fields":{"name":schema,"optional?":schema}}
for an object (all keys without ? are required). Use an inline full JSON Schema
object for constraints, unions or other details. Omitted request components
params/query/body/headers are empty object schemas. Response success and errors
use [status, bodySchema, headersSchema?]; omit errors if there are none. Header
names are lower-case. Use "null" for an empty body.
For APIs and modules omit total read/write and callers; the compiler derives them.
API preconditions include error_status and API postconditions include status.
Module pre/postconditions include id and description. Preserve required business
behavior, matching route placeholders, credential transport, and no-write rejections.
"""


_TYPES = {"string", "number", "integer", "boolean", "null", "object", "array"}


def expand_schema(value):
    if isinstance(value, str) and value in _TYPES:
        return {"type": value}
    if isinstance(value, list) and len(value) == 1:
        return {"type": "array", "items": expand_schema(value[0])}
    if isinstance(value, dict):
        if set(value) != {"fields"}:
            return deepcopy(value)
        properties, required = {}, []
        for key, field in value["fields"].items():
            name = key.removesuffix("?")
            if not name or name in properties:
                raise ValueError(f"Invalid or duplicate schema field {key!r}")
            properties[name] = expand_schema(field)
            if name == key:
                required.append(name)
        return {"type": "object", "properties": properties, "required": required}
    raise ValueError(f"Expected a compact or inline JSON schema, got {value!r}")


def expand_contract(kind, contract):
    record = deepcopy(contract)
    if kind == "modules":
        for key in ("input", "output"):
            record[key] = expand_schema(record[key])
        return record
    request = record.get("request", {})
    unexpected = set(request) - {"params", "query", "body", "headers"}
    if unexpected:
        raise ValueError(f"Unexpected API request components: {sorted(unexpected)}")
    record["request"] = {key: expand_schema(request.get(key, {"fields": {}}))
        for key in ("params", "query", "body", "headers")}

    def expand_result(result):
        if isinstance(result, list):
            if len(result) not in {2, 3}:
                raise ValueError("HTTP response must be [status, body, optional headers]")
            status, body, *headers = result
            return {"status": status, "body": expand_schema(body),
                "headers": expand_schema(headers[0] if headers else {"fields": {}})}
        return {**result, "body": expand_schema(result["body"]), "headers": expand_schema(result["headers"])}

    response = record["response"]
    unexpected = set(response) - {"success", "errors"}
    if unexpected:
        raise ValueError(f"Unexpected API response components: {sorted(unexpected)}")
    record["response"] = {"success": expand_result(response["success"]),
        "errors": [expand_result(result) for result in response.get("errors", [])]}
    return record


def read_records(content, *, truncated=False):
    """Recover only independently parseable records, never repair incomplete JSON."""
    for number, line in enumerate(content.splitlines(), 1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as error:
            if truncated:
                continue
            raise ValueError(f"Invalid JSON on backend record line {number}: {error.msg}. "
                "Emit one complete JSON object on each line.") from error
        if not isinstance(record, dict):
            if truncated:
                continue
            raise ValueError("Each contract record must be an object")
        yield record


def combine_records(records, active):
    proposal = {"apis": {}, "modules": {}, "requirements": {}}
    for record in records:
        rid = record["requirement_id"]
        if rid not in active or rid in proposal["requirements"]:
            raise ValueError(f"Unexpected or duplicate backend requirement ID: {rid}")
        proposal["requirements"][rid] = {key: record[key] for key in ("api_ids", "module_ids")}
        if "conventions" in record:
            proposal["requirements"][rid]["conventions"] = record["conventions"]
        for kind in ("apis", "modules"):
            for identity, contract in record[kind].items():
                if identity in proposal[kind] and proposal[kind][identity] != contract:
                    raise ValueError(f"Conflicting definitions for {kind}.{identity}")
                proposal[kind][identity] = contract
    if set(proposal["requirements"]) != set(active):
        missing = sorted(set(active) - proposal["requirements"].keys())
        raise ValueError(f"Missing complete backend records for {missing}")
    return proposal

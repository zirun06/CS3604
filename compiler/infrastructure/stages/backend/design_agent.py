"""Backend design prompts and complete API/module contract definitions."""


STRING = {"type": "string"}
STRINGS = {"type": "array", "items": STRING}
FUNCTION_NAME = {"type": "string", "pattern": "^[A-Za-z_][A-Za-z0-9_]*$",
    "description": "Unique implementation function name, e.g. resolveCurrentUser; separate from the stable contract id."}
JSON_SCHEMA = {"type": "object", "additionalProperties": True,
    "description": "Inline JSON Schema describing the value, not example data. Declare object properties/required and array items where applicable."}
CONDITIONS = {"type": "array", "items": {"type": "object", "properties": {
    "id": {"type": "string", "description": "Stable condition identifier"},
    "description": {"type": "string", "description": "Business assumption or guaranteed outcome, including applicable branches"}},
    "required": ["id", "description"], "additionalProperties": False}}
COMMON = {
    "description": {"type": "string", "description": "Business responsibility, call sequence, input mapping, result composition and failure handling"},
    "read": {**STRINGS, "description": "Total qualified Entity.field reads, including all callee effects; [] when none"},
    "write": {**STRINGS, "description": "Total qualified Entity.field writes across supported branches, including callee effects; [] when none"},
    "precondition": {**CONDITIONS, "description": "Input/state assumptions and supported rejection conditions; [] if unconditional"},
    "postcondition": {**CONDITIONS, "description": "Output and persistent-state guarantees for supported branches"},
    "callees": {**STRINGS, "uniqueItems": True,
        "description": "IDs of directly called modules only. Callers are derived by the compiler and must not be supplied."},
}
MODULE = {"type": "object", "description": "Complete internal module contract, also required for updates",
    "properties": {**COMMON, "name": FUNCTION_NAME,
        "input": {**JSON_SCHEMA, "description": "Inline JSON Schema of the module's input arguments"},
        "output": {**JSON_SCHEMA, "description": "Inline JSON Schema of the module's result, including specified business failure branches"},
        "direct_read": {**STRINGS, "description": "Qualified DB fields read by this module itself, excluding callee accesses"},
        "direct_write": {**STRINGS, "description": "Qualified DB fields written by this module itself, excluding callee accesses"}},
    "required": [*COMMON, "name", "input", "output", "direct_read", "direct_write"], "additionalProperties": False}
HTTP_RESULT = {"type": "object", "properties": {
    "status": {"type": "integer", "minimum": 100, "maximum": 599, "not": {"const": 501},
        "description": "HTTP status for this specified business outcome; 501 is reserved for implementation stubs"},
    "body": {**JSON_SCHEMA, "description": "Inline JSON Schema of the response body; use type=null for an empty body"},
    "headers": {**JSON_SCHEMA, "description": "Inline JSON Schema of response headers with lower-case names"}},
    "required": ["status", "body", "headers"], "additionalProperties": False}
API = {"type": "object", "description": "Complete HTTP data endpoint contract, also required for updates",
    "properties": {**COMMON,
        "signature": {"type": "object", "properties": {
            "name": FUNCTION_NAME,
            "method": {"type": "string", "enum": ["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"],
                "description": "Uppercase HTTP method"},
            "path": {"type": "string", "pattern": "^/api/[^?#\\s]+$",
                "description": "Backend data endpoint, e.g. /api/session/current; never a frontend page URL, query string or fragment"}},
            "required": ["name", "method", "path"], "additionalProperties": False},
        "request": {"type": "object", "properties": {
            "params": {**JSON_SCHEMA, "description": "Schema of named route parameters, matching placeholders in signature.path"},
            "query": {**JSON_SCHEMA, "description": "Schema of query parameters"},
            "body": {**JSON_SCHEMA, "description": "Schema of the request body"},
            "headers": {**JSON_SCHEMA, "description": "Schema of request headers with lower-case names and explicit credential transport"}},
            "required": ["params", "query", "body", "headers"], "additionalProperties": False},
        "response": {"type": "object", "properties": {
            "success": {**HTTP_RESULT, "description": "Successful business response"},
            "errors": {"type": "array", "items": HTTP_RESULT, "description": "Requirement-supported rejection responses; [] when none"}},
            "required": ["success", "errors"], "additionalProperties": False},
        "precondition": {"type": "array", "description": "API assumptions with rejection status declared in response.errors", "items": {
            "type": "object", "properties": {"id": STRING, "description": STRING,
                "error_status": {"type": "integer", "description": "Status of the declared rejection response when this condition fails"}},
            "required": ["id", "description", "error_status"], "additionalProperties": False}},
        "postcondition": {"type": "array", "description": "Observable guarantees associated with declared response statuses", "items": {
            "type": "object", "properties": {"id": STRING, "description": STRING,
                "status": {"type": "integer", "description": "Declared response status to which this guarantee applies"}},
            "required": ["id", "description", "status"], "additionalProperties": False}}},
    "required": [*COMMON, "signature", "request", "response"], "additionalProperties": False}


BACKEND_DESIGN_RULES = """You are an architecture designer incrementally designing the backend for ONE
requirement, preserving earlier accepted contracts. Design both HTTP APIs and reusable
internal modules between API and database. Produce contracts, not implementation code.

APPLICATION BOUNDARY
The generated frontend renders pages. Page URLs such as /, /register and /login are
frontend routes, NOT backend HTTP API paths. Design data endpoints under /api/.
For example, opening / to restore the username needs GET /api/session/current returning
JSON; do not design GET / serving rendered HTML. APIs return business data and action
outcomes, while UI labels, link visibility, page layout and rendering belong to frontend.
Do not create an HTML-rendering API or incidental UI formatting modules to implement a
page requirement. A requirement about a page is not permission to move rendering server-side.

Design API interfaces around data and actions needed by frontend scenarios.
Declare the exact wire path, route-parameter names, and JSON success/error fields consumed
by callers. When required by the source, define one session bootstrap/refresh contract,
stable credential transport and owner-scoped access; preserve explicitly public reads.
Never expose stored password hashes or session secrets in business responses. Describe only requirement-supported success and
rejection branches. Preconditions and postconditions must connect interface behavior
to observable outcomes, including unchanged data on rejection where required.

Modules perform computation, persistence, composition or shared business operations.
Describe each module's input assumptions, failure outcomes,
computed results and DB guarantees. Pure calculations have empty DB effects. Create
modules only for meaningful responsibilities; avoid splitting every statement or
introducing wrappers with no independent purpose. Module postconditions should explain
which output/failure branches its callers must handle; APIs map these to HTTP responses.
An internal requirement can associate modules without any HTTP API.

OBLIGATION AND CALL GRAPH
read/write contain TOTAL possible persistent effects across specified branches.
Modules additionally declare direct_read/direct_write for fields directly accessed
by their own logic. A module's total read/write MUST equal the union of direct effects
and all callees' total effects. APIs access the database through modules; their total
effects MUST equal the union of their callees. Module callees can only name modules;
cycles and calls back into APIs are forbidden. List each direct callee once; descriptions
and P/Q explain call order, parameter mapping, result composition and failure handling.
The compiler DERIVES callers as the inverse of callees for both API and module records;
do not supply callers in tool arguments. Forward references are allowed while staging;
all references must resolve when associate_requirement finalizes the design.

The current requirement's associated API/module totals must cover its read obligation
and have EXACTLY its write obligation. Supporting reads are allowed. This also covers
each step, and shared updates must preserve all earlier requirement coverage. Given
setup is not the current action. Keep rejection paths write-free when required; totals
still include successful-branch writes. Reload/reopening needs persisted read operations;
a create response cannot replace them. Do not inherit unrelated parent/reference effects.

REUSE AND RETRIEVAL
Supplied candidates combine BM25 and same-mode read/write overlap retrieval. They can
be reused, extended, or used as examples for distinct operations. Overlap is evidence
of data relevance, NOT proof of compatible behavior, inputs, security rules or outputs.
Never reuse a broad mutating operation that introduces unrelated writes. Pure modules
can be retrieved lexically even with empty effects. Complete callee dependencies are
included, along with connected callers needed to coordinate shared updates. No retrieve
tool is available. Stable canonical IDs preserve shared behavior.
Selected shared conventions must remain consistent across new and reused operations.

"""

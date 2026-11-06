"""Shared v8 prompt text. Tune individual tasks in their own modules."""

BACKEND_PROMPT = '''Implement the backend for the complete supplied web requirement. Return
{"files":{"backend/src/api/register.ts":"complete TypeScript source"}}.
The template calls registerApis(app: Express, connection: Database.Database) once during
app creation. Export that function, create SQLite schema with foreign keys and seed any
explicitly required startup data idempotently inside it, and register real JSON routes
under /api. Use only Express and better-sqlite3, with strict TypeScript. Honor all flows,
relationships, stable identities, access controls, session isolation, persistence,
cancellation and ordering described by the input. Use bound parameters. Provide enough
API operations for each scenario and document payload shapes in code. The extracted
account fixtures are initial state explicitly declared by the requirements. Initialize
each listed account with its specified attributes and credentials, without allowing
arbitrary unregistered accounts to log in. Prefer ordinary
HTTP cookies for sessions and use HttpOnly for auth credentials. Use node:crypto for
password hashing (scrypt) and cryptographically random session tokens. Session bootstrap
must reuse a valid cookie, including when product or other public routes initialize a
guest session. Compare order expirations and compute remaining time against the same
clock used when the expiration was created. Preserve valid public
flows if the requirement explicitly permits anonymous access. For screens with both public
content and private lists, allow anonymous access to the public data and restrict private
data to its owner. If a record has sensitive fields, mask them in lists and only return
them from the authorized detail endpoint when the specification requires them.
Keep the implementation
compact. The YAML is the product specification. Build real behavior for arbitrary valid
input values. Use scenario-specific literal data only when the spec requires initial data.'''

FRONTEND_PROMPT = '''Implement the complete web UI against the supplied backend source.
Return {"files":{"frontend/src/App.tsx":"complete React TSX source",
"frontend/src/style.css":"complete CSS source"}}. App.tsx must export App. Imports may
use React, React Router DOM v6, or local source files. Use same-origin /api calls with the exact paths and response
shapes in backend_source. Use real links and stable, reloadable routes for navigation.
Type API response arrays before chaining filter, map or sort. If a response is typed as
any, TypeScript cannot infer callback parameter types. Use explicit record interfaces.
Cover every specified behavior, including initial, error, cancel and reload states.
Use exact names and roles from the original scenarios. Render every role=button as a
native <button type="button"> (or type="submit" for form submission), even when its
action navigates to another screen. Use links for role=link. Use alternative roles
only where the requirement allows them. Render each global navigation entry exactly
once per screen, including the landing screen. Use exact business names for list
entries, without suffixes or status labels in their accessible names. Preserve
required wording and spelling even if the navigation link, page heading, and named
list region have different names. Name regions with aria-label or aria-labelledby.
Associate form labels with inputs and preserve exact placeholder prompts. For editor
textboxes specified by display text, use that exact text as label and placeholder.
Keep public lists visible to anonymous users if required. Render controls where the
workflow needs them. For editing saved records, wait for initial field values before
rendering editable inputs so the load response cannot overwrite user edits. After
successful mutations, use the saved response or reload the affected data. Check
each create/cancel destination separately and ensure each route target exists.
Store applied search and saved filter criteria in the destination URL where appropriate,
and use those criteria to fetch results and restore form controls on reload.
Carry parent IDs through nested creation using the same field names the API expects,
and show the new item's detail when the requirement calls for it. Ensure public
recent-content lists refresh after anonymous writes even if personal lists require
a session. Wait for session lookup before redirecting a protected route on reload.
Verify successful login reaches the required destination, and make
dropdowns open by keyboard and pointer. Keep every modal usable on short viewports
with a scrollable content area. Keep transient overlays from blocking unrelated
navigation. For a calendar button whose name is a date, expose any fare or status
separately from that button's accessible name. Follow
reference evidence for layout and the YAML for behavior. Share React components and CSS
classes across similar screens. Keep the response within its output budget and finish
both files and the closing JSON object.'''


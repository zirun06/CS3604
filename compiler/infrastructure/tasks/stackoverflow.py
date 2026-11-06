"""Stack Overflow contracts and budgets, isolated from the other five tasks."""

from infrastructure.tasks.profile import TaskProfile
from infrastructure.tasks import prompts

API_CONTRACT = """
Mandatory Stack Overflow core API contract shared by backend and frontend:
- GET /api/questions -> {questions: array}; GET /api/tags -> {tags: array};
  GET /api/users -> {users: array}. These public reads work anonymously without
  a foreign-key-invalid guest account. An anonymous session uses NULL account ID,
  never a fictitious zero ID, and bootstrap reuses an existing valid cookie.
- GET /api/search?q=<complete title> returns {questions: array, suggestions: array}
  and includes the actual matching historical or newly published record.
- GET /api/questions/:id opens a publicly readable question and its answers.
  Search results must link to a working detail for that actual record ID.
- POST /api/auth/signup and POST /api/auth/login take {email,password}; each
  returns {user:{id,email,display_name,reputation,...}} and sets the session cookie.
- GET /api/auth/me returns {user: the same public object or null} and restores
  the current session; POST /api/auth/logout clears authentication.
- Public user/author objects use display_name, not displayName. Newly registered
  accounts use their email as display_name until edited. Every API consumer uses
  the backend's documented field names; do not invent an incompatible second
  response envelope. Other endpoints are documented in the supplied backend.
These routes and response keys are required by this implementation strategy.
"""

BACKEND_GUIDANCE = API_CONTRACT + """
Stack Overflow integration contracts:
- declared_initial_world is a deduplicated index of startup data explicitly given
  by the specification. Seed ALL historical_questions, including their supplied
  answers, comments and timestamps, not only the first retry question. Preserve
  shared parent identities across public discovery and activity. Public history
  must exist before a profile or module is visited; do not create it lazily from
  activity endpoints. Ordinary runtime examples remain UI-created, not seeded.
- Every INSERT must have exactly as many value expressions as listed columns;
  its bound arguments match its placeholders. Question/answer creation must be
  executable against the initialized schema, not just TypeScript-correct.
- Read the supplied scenarios' initial accounts, historical posts, tags, badges,
  activity and timestamps. Seed those public fixtures once, using stable identity
  relations, without reseeding on each request. Runtime questions, answers and
  comments are created by users, have arbitrary titles/text, and must remain
  discoverable in other authenticated browser contexts. Never infer an owner
  from a title, display name, or case suffix. Many accounts share Stack User.
- Use one persistent per-browser session and one current-user response shape.
  Restore it on reload, pass credentials on all writes, and authorize by user ID
  in every endpoint. Do not let an anonymous bootstrap race overwrite a newly
  authenticated identity. State belongs to its account, not a global active user.
  Preserve the declared account passwords and profile fields; signup must create
  usable credentials and an automatic session without email verification.
- Return all simultaneous form errors. Empty login must return both Email cannot
  be empty and Password cannot be empty. Keep the exact specified malformed,
  absent-account and wrong-password messages distinct.
- Define explicit request/response shapes for question creation and detail before
  implementing them. Return the created question ID and full detail, not an
  ambiguous mixture of id, question_id and nested objects. Parse tags consistently
  whether the editor supplies comma-separated text or an array. Enforce only the
  required title/body minima 15/220 and at least one tag. Search full titles and
  expose newly created records immediately. Answers/comments refer to real
  parent IDs, with parent-specific queries and no shared draft or thread state.
- Persist votes by (voter, post kind, post ID). Derive the displayed current vote
  for that viewer. Clicking the same vote undoes it, and changing direction first
  reverses the old reputation effect. Apply question/answer upvote +10 and
  question downvote -2 to the author's reputation transactionally, as specified.
  Return updated score, current vote and author reputation after each mutation.
  Deleting an unaccepted answer reverses its vote reputation. Enforce ownership,
  prevent deletion of accepted answers, and allow only the question owner to
  accept exactly one answer. Transfer acceptance atomically.
- Persist edits and revision summaries even when an unchanged answer is saved;
  validate empty answer bodies with Body cannot be empty. Comments have their
  own edited flag, created timestamp, post parent and optional parent comment.
  Use the specified clock for the five-minute comment edit window; do not use
  historical July fixtures against the machine's current date. Preserve the
  separate expired-clock scenario without adding undocumented browser controls.
- Owner activity must query actual posts and answers including runtime-created
  ones, with complete answer text and links to real parent questions. Public
  profiles, reputation history and private votes use the viewed user's ID and
  the viewer's authorization. Watched tags and custom filters are per user and
  survive reload. Tag counts start at the catalog baseline and adjust on actual
  publication, deletion and tag edits. Never replace unrelated historical posts.
"""

FRONTEND_GUIDANCE = API_CONTRACT + """
Stack Overflow implementation priorities and UI contracts:
- First complete login -> Ask Question -> publish -> search in another browser ->
  answer -> owner activity. Build one typed API helper and match the supplied
  backend's actual paths, field names and response envelopes exactly. Check HTTP
  errors and show their messages. Await mutations, then refresh their real parent
  detail. Do not swallow an error or navigate using an undefined created ID.
- Keep a banner, navigation Main navigation, and page content. The header profile
  action's name is the current display name (Stack User for verified fixtures),
  or registered email when no display name exists. Catalog profile buttons are
  '<display name> <email>' to distinguish identities. Clicking one's header action
  must actually navigate to that user's profile, on first load and after reload.
- Reuse a Profile component for own and catalog profiles. Include Public profile,
  numeric status Reputation, Badges and Recent activity regions. Include a
  navigation named Profile navigation with Activity and Reputation; inside its
  Activity view use a separate Activity navigation with all specified categories
  and an Activity content region. Expose aria-current='page' on selected items.
  Keep these scopes distinct so Reputation/Questions/Answers are unambiguous.
  Answer activity shows the complete answer excerpt, parent title and accepted
  status. Profile editing preserves all eight fields and displays a success
  role=status after saving, including after returning to the Public profile.
- Question feed contains its own Ask Question, Newest, Active and Next page
  controls even when anonymous. An anonymous Ask Question may open login. Each
  summary is a region named 'Question <title>'. Metric statuses named Score,
  Answer count and View count contain only numeric text, with labels outside.
- Question detail has one exact title heading, Question post region, and separate
  Answers region. A shared Post component should implement question and answer
  score, votes, author, revisions and comments. Answers contains regions named
  'Answer by <display name>'. Scope Author and its Reputation to the right post.
  Votes have aria-pressed from the server viewer vote, not a transient CSS class.
  Question post includes the required Edit action for the reference detail;
  protected mutations still check ownership. Owner edit/delete actions belong to
  the post rather than its Author or nested Comments. Use Sorted by with exactly
  Highest score, Trending, Date modified, initially Date modified as specified.
- Question editor labels Title, Body, Tags, Edit Summary and status Title character
  count are exact. Suggestions is a named region: entering node.js suggests
  node.js, http and retry, rather than filtering them away by substring. Accept
  comma-separated tags. Preview renders Markdown live; Bold, Italic and Code
  operate on the editor selection. Existing editors prefill Title/Body/Tags,
  include How to Edit and Rev, retain validation errors and discard on Cancel.
  Save edits persists summary and shows edited metadata. Timeline displays the
  actual Revision history region. Keep post creation and answer submission
  labels distinct: Post Your Question and Post Your Answer / Your Answer.
- Shared Comments component takes post kind and ID; each comment is a region
  named 'Comment <body>' with status Comment votes, owner Edit/Delete and Reply.
  Enter commits Comment. Reply opens a parent-scoped Reply textbox and Add Reply;
  render Replies nested INSIDE that comment with @parent-author attribution.
  Show edited after successful edits. Comment deletion is immediate. Question
  and answer deletion instead use a dialog AND button named Confirm deletion.
  Show five comments then Show 2 more comments for the seven-comment fixture.
- Tags has regions 'Tag <name>' with numeric Question count. Clicking python
  opens Python tag containing Watch tag/Unwatch tag and Related tags, as well as
  the filtered feed. Watched tags and Saved filters use their own named regions.
  The watch action belongs inside Python tag, not only a sibling toolbar. Filter
  panel has Unanswered checkbox, native Sort select and Tags textbox; Save custom
  filter opens the named dialog with Filter title and Save filter. Restore saved
  criteria and selected options after navigation/reload, for this viewer only.
- Login uses a Log in region and matching submit button, and signup likewise.
  Render both empty-field messages in the login region at once. Use noValidate
  when browser-native validation would hide the required visible errors.
- Use reusable Post, Comments, Feed, Profile and editor rendering, with ordinary
  React data flow. Avoid giant repeated inline branches, local shadow copies of
  identity, and components defined inside the parent render that remount inputs
  on each keystroke. Only CSS goes in the later styling stage.
- Read saved revision history from the actual server detail/endpoint and pass it
  to both question and answer Timeline views. location.state and local arrays
  are not persisted history and disappear for a second browser or after reload.
  Do not replace source timestamps with new Date() when rendering saved events.

Scope and uniqueness checklist before returning the source:
- Put each summary's title, tags AND numeric Score/Answer count/View count inside
  the same 'Question <title>' region. Visible labels include votes, answers and
  views; do not leave the metrics in a sibling outside the summary region.
- Put question tags INSIDE Question post, by passing tags to Post and rendering
  them there. Rendering TagLinks immediately after </Post> is the wrong scope.
- On a question detail page expose exactly one status named Answer count. Other
  visual copies of the count are ordinary text without that role/name. Make the
  question's visible Modified label unique; answer metadata uses edited/updated
  wording so it does not create a second matching Modified label.
- Show an explicit edited indicator inside the edited question/answer even when
  only the edit reason changed. Ensure its backend response carries the saved
  revision/edited flag and refresh it after Save edits.
- Keep a Filter action available on the normal Questions listing, with its panel
  and saved criteria. Do not implement Filter only on search results or tag pages.
- A weak-password message visibly says 'at least 8 characters'. Keep the saved
  profile success status on the destination profile after editor navigation.
- Keep Comments mounted inside its owning post even when empty or anonymous;
  only the write/maintenance controls depend on authentication and ownership.
- Use the literal visible identity Stack Overflow in the banner, and provide
  Next page inside both the Question feed and Tags catalog scopes.
- Adjacent visible labels do not name a role=status element automatically. Use
  aria-label="Score", aria-label="Reputation", etc. on the status itself. Give
  header identity actions an explicit aria-label from the display name/email;
  decorative icons and CSS pseudo-element content must not alter that name.
"""

REPAIR_GUIDANCE = """
Stack Overflow: prioritize shared session recovery, header profile navigation,
question creation/detail and cross-account discovery before isolated labels.
Many answer/comment cases fail during question creation: inspect the actual
submission response, request fields and navigation ID rather than patching each
case's title. Never special-case a generated title or account suffix.
Trace profile navigation from the header action to the rendered Profile navigation
and Activity navigation landmarks. Preserve distinct per-user ownership, viewer
votes, comment parents and private preferences. Fix the shared component when
multiple scopes lack statuses, aria-pressed or actions. Profile update needs a
visible saved status; answer activity must retain the complete answer text.
Use exact short anchors copied from current files. Finish one shared blocker
end to end per attempt, preserving every already passing scenario.
For strict mode violations, count the actual rendered matching roles and names
and keep just the required semantic output in its owning region. A CSS class
does not change an accessible name, role, or containment. Do not try to fix
duplicate Answer count statuses with a class change. Keep the single named
status in the detail's Answers section and use plain text for redundant copies.
If Question post lacks its tags, move their real rendering into the Post region
instead of adding another global tag bar. Use the same scope rule for summary
metrics. When a profile save navigates away, preserve its success status on the
destination. For edits trace both the persisted edited flag and its rendering.
For missing search targets, compare the declared initial world with seeded public
records first. A correctly working search cannot find a record never initialized.
For revision history, trace the saved summary in the backend response through the
detail type and the Post prop; do not append it only to navigation state.
"""

PROFILE = TaskProfile(
    key="stackoverflow", suite="75912b85c96a15ebd749a0b344556d5e972b39c866cdcfbcd043576ab73f9c0c",
    backend_prompt=prompts.BACKEND_PROMPT + BACKEND_GUIDANCE,
    frontend_prompt=prompts.FRONTEND_PROMPT + FRONTEND_GUIDANCE,
    report_profile="stackoverflow", frontend_mode="split",
    style_output_tokens=10000, style_attempts=2, build_repair_attempts=2,
    transient_retries=2, rollback_failed_candidates=True, associate_status_labels=True,
    validate_sql_inserts=True, probe_backend_contract=True,
    index_initial_world=True, adaptive_repairs=True,
    repair_dependencies=(('composeQuestion', 'REQ-3.3'), ('publishAnswer', 'REQ-4.1'),
                         ('openQuestion', 'REQ-6.3'), ('ownProfile', 'REQ-2.3'),
                         ('login', 'REQ-2.1'), ('activity', 'REQ-7.4')),
    acceptance_attempts=4, repair_failure_limit=1, repair_edit_retries=1,
    retry_invalid_edits=True,
    style_guidance="Keep CSS under 24000 characters with shared navigation, post, "
                   "editor, profile, comment and dialog selectors. No application "
                   "code or embedded images. Do not hide named regions or controls.",
    repair_guidance=REPAIR_GUIDANCE,
)

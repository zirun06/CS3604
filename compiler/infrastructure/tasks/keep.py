"""Independent v8 configuration for keep."""

from infrastructure.tasks.profile import TaskProfile
from infrastructure.tasks import prompts


BACKEND_GUIDANCE = """
Implement the personal workspace without login or a reminder scheduler.
Use persistent note IDs and label IDs. Notes store content, pinned state, background
color, archive state and deletion time. Keep Notes, Archived and Trash mutually
consistent. Undo restores the exact deleted note. Empty Trash removes only trashed
notes; implement the specified seven-day retention using timestamps. Reminders is
a default label. Save settings and layout changes, honoring Save versus Cancel.
Keep API payloads consistent across create, autosave, edit, restore and filtering.
"""
FRONTEND_GUIDANCE = """
Use the exact scenario names for Sidebar, Take a note, Note editor, Title,
Content, Close, Pinned notes and Other notes.
Use native buttons for Notes, Reminders, Archived, Trash and Edit Labels even
when they navigate. Set aria-label="Take a note" on the creation button if its
visual text has dots. Set aria-expanded on Toggle sidebar. Mark decorative icon
spans aria-hidden so they cannot change the accessible names of buttons.
Preserve each arbitrary note title as its region name, including any suffix
entered by the user. Note actions are
scoped to that region and usable by hover and keyboard. Autosave on Close must
finish before refreshing the list; reopening an editor loads the saved values.
Keep archived and trashed notes out of active lists. Undo targets the last action's
record, and rename/delete labels updates note membership consistently.
Use plain Unicode characters or JavaScript string expressions for icons.
Never place a raw Unicode code-point escape directly in JSX text.
Generate complete compilable TSX with reusable components and CSS class names.
Return every requested file as a nonempty JSON string, including on retry.
"""
REPAIR_GUIDANCE = """
Prioritize shared entry controls and exact accessible names before individual
actions. Trace note IDs through autosave, archive, Trash and Undo. For TS1351
with TS1381 near an icon, inspect JSX escapes and use a string expression or
literal character. Keep the previously saved note content and label identities.
"""

PROFILE = TaskProfile(
    key="keep", suite="f38fe91559d85ff1b5a6a264351bf6675f1723927ce91b762eceef7942ae3dbf",
    backend_prompt=prompts.BACKEND_PROMPT + BACKEND_GUIDANCE,
    frontend_prompt=prompts.FRONTEND_PROMPT + FRONTEND_GUIDANCE,
    repair_guidance=REPAIR_GUIDANCE,
    frontend_mode="split", split_output_tokens=24000, style_output_tokens=10000,
    style_attempts=2, build_repair_attempts=2, transient_retries=2,
    rollback_failed_candidates=True,
    allow_zero_progress=True,
    style_guidance="Use shared selectors and CSS variables. Keep CSS under 18000 characters. "
                   "Do not inline images, fonts or application code.",
)

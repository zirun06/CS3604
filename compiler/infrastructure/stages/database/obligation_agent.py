"""Prompts shared by the database obligation review."""


OBLIGATION_INTRO = """You are an architecture designer deriving database read/write obligations for
ONE requirement and its scenario steps. You receive the current requirement (name,
description, scenarios and parent module), candidate related fields, the complete
existing entity-name/description inventory, and potentially related complete entity
structures. Assume the completed schema is sufficient. Select existing fields to
express the requirement's persistent data effects.

For requirement r, its obligation O(r) = (R(r), W(r)):
- R(r) contains existing persistent values needed by specified behavior, including
  displayed values, lookup/filter/join keys, existence checks, authentication and
  authorization data.
- W(r) contains fields whose persisted values or record existence are created,
  changed or removed by specified behavior, including generated keys.
A field may be read, written, both, or neither. The sets cover specified branches,
not effects required on every invocation or an exhaustive SQL access whitelist.
Candidate related fields are hints: include missing relevant fields visible in the
schema and exclude irrelevant candidates. Do not force every candidate into a set.

"""

OBLIGATION_RULES = """Derive each step's effects from its current When action and Then outcome, treating
Given as pre-existing context. Form requirement-level sets covering all its steps
plus additional behavior explicitly required by the description. Do not copy the
requirement-wide effects into every step or inherit another requirement's effects
through references or parent module context.

Examples (illustrative names; select only actual schema symbols):
- Refreshing a homepage to restore a username reads the session lookup key, account
  relation and username; writes []. Accounts/sessions created in Given do not count
  as writes of the refresh action.
- Registration reads Account.username to check duplicates. Successful creation
  writes required account fields and generated Account.id; duplicate rejection
  writes []. The requirement includes successful-branch writes. Returning a newly
  generated ID alone does not read a previously persisted ID.
- Login reads the stored password hash; the submitted password is input, not a DB
  field. Session writes are required only if the behavior specifies creating one.
- Opening/reopening an editor reads persisted data; saving writes changed fields.
  Cancel/rejection does not write unless specified. A later reload still reads
  persisted data even if an earlier creation returned it.
- Hard deletion writes all fields of the removed entity, including its key; soft
  deletion writes the actual changed flags. A purely local tab change has no DB
  reads or writes.

"""

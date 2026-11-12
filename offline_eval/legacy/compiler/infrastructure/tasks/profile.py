"""Immutable compiler settings owned by an individual task."""

from dataclasses import dataclass

from infrastructure.tasks.prompts import BACKEND_PROMPT, FRONTEND_PROMPT


@dataclass(frozen=True)
class TaskProfile:
    key: str
    suite: str = ''
    backend_prompt: str = BACKEND_PROMPT
    frontend_prompt: str = FRONTEND_PROMPT
    report_profile: str = 'compact'
    frontend_mode: str = 'auto'
    generation_attempts: int = 3
    joint_attempts: int = 3
    style_attempts: int = 1
    large_output_tokens: int = 26000
    small_output_tokens: int = 16000
    split_output_tokens: int = 32000
    style_output_tokens: int = 6000
    repair_output_tokens: int = 8000
    build_repair_output_tokens: int = 6000
    build_repair_attempts: int = 1
    transient_retries: int = 0
    rollback_failed_candidates: bool = False
    allow_zero_progress: bool = False
    style_guidance: str = ''
    acceptance_attempts: int = 3
    repair_failure_limit: int = 14
    repair_edit_retries: int = 0
    retry_invalid_edits: bool = False
    build_repair: bool = True
    route_parameter_repair: bool = False
    associate_status_labels: bool = False
    validate_sql_inserts: bool = False
    probe_backend_contract: bool = False
    index_initial_world: bool = False
    railway_contract: bool = False
    railway_navigation_gate: bool = False
    ctrip_contract: bool = False
    adaptive_repairs: bool = False
    repair_dependencies: tuple[tuple[str, str], ...] = ()
    legacy_acceptance: bool = False
    repair_guidance: str = ''


DEFAULT = TaskProfile(key='generic')

"""Select a task using the existing requirements-to-suite identity."""

from pathlib import Path

from infrastructure.tasks import bookstack, ctrip, keep, prestashop, railway12306, stackoverflow
from infrastructure.tasks.profile import DEFAULT, TaskProfile


PROFILES = (
    railway12306.PROFILE, bookstack.PROFILE, ctrip.PROFILE,
    keep.PROFILE, prestashop.PROFILE, stackoverflow.PROFILE,
)
BY_SUITE = {profile.suite: profile for profile in PROFILES}
if len(BY_SUITE) != len(PROFILES):
    raise ValueError('Each task must have a unique requirements suite')


def select_profile(suite: Path | None) -> TaskProfile:
    """Unknown requirement revisions use the generic compiler configuration."""
    return BY_SUITE.get(suite.name, DEFAULT) if suite is not None else DEFAULT

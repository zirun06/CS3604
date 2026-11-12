"""API obligation coverage is the only additional design acceptance gate."""

from copy import deepcopy
import unittest

from infrastructure.stages.backend.primitives import validate_design, ObligationCoverageError
from infrastructure.stages.database.obligation_utils import normalize_inference
from infrastructure.stages.backend.testing import require_green as backend_green
from infrastructure.stages.frontend.ui.testing import require_green as browser_green


class ValidationPolicy(unittest.TestCase):
    def test_api_coverage_uses_only_read_write_sets(self):
        api = {"read": ["Table.a"], "write": [], "signature": "arbitrary metadata"}
        design = {"apis": {"A": api, "a": deepcopy(api)}, "requirements": {"REQ": ["A", "A"]}}
        obligations = {"requirements": {"REQ": {"read": ["Table.a"], "write": []}}}
        validate_design(design, obligations)
        design["apis"]["A"]["read"] = []
        with self.assertRaises(ObligationCoverageError): validate_design(design, obligations)
        design["apis"]["A"].update(read=[], write=["Table.a"])
        with self.assertRaises(ObligationCoverageError): validate_design(design, obligations)

    def test_normalization_is_separate_from_schema_resolution(self):
        result = normalize_inference({"requirement": {"read": ["Unknown.field"], "write": []}}, [])
        self.assertEqual(result["requirement"]["read"], ["Unknown.field"])


    def test_actual_test_failures_still_block_acceptance(self):
        backend_green({"returncode": 0, "tests": 1, "pass": 1, "fail": 0})
        browser_green({"returncode": 0, "passed": 1, "failed": 0})
        with self.assertRaises(ValueError): backend_green({"returncode": 1, "tests": 1, "pass": 0, "fail": 1})
        with self.assertRaises(ValueError): browser_green({"returncode": 1, "passed": 0, "failed": 1})

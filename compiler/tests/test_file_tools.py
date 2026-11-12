"""Shared file tools exercise real partial edits, adaptation and atomic failures."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

from infrastructure.shared.agent.loop import run_file_agent
from infrastructure.shared.agent.tools import FileTools, FileToolError
from infrastructure.utils.files import save_text


def call(tool, **arguments):
    return {"tool": tool, **arguments}


class FileToolTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)


    def test_exact_matching_errors_leave_entire_batch_unchanged(self):
        path, other = "backend/src/main.ts", "backend/src/other.ts"
        save_text(self.root / path, "same\nsame\nunique\n")
        tools = FileTools(self.root, ['backend'], stage='backend', writable=[path, other])
        for old, code in (("missing", "OLD_CONTENT_NOT_FOUND"), ("same", "OLD_CONTENT_NOT_UNIQUE")):
            with self.subTest(code=code), self.assertRaises(FileToolError) as failed:
                tools.execute([call("edit_file", path=other, operation="create", new_content="new"),
                    call("edit_file", path=path, operation="replace", old_content=old, new_content="changed")])
            self.assertEqual(failed.exception.feedback["code"], code)
            self.assertFalse((self.root / other).exists())
            self.assertEqual((self.root / path).read_text(), "same\nsame\nunique\n")

    def test_creation_never_overwrites_existing_files_and_empty_files_allow_insertions(self):
        path = "backend/src/empty.ts"
        save_text(self.root / path, "")
        tools = FileTools(self.root, ['backend'], stage='backend', writable=[path])
        with self.assertRaises(FileToolError) as failed:
            tools.execute([call("edit_file", path=path, operation="create", new_content="overwrite")])
        self.assertEqual(failed.exception.feedback["code"], "FILE_ALREADY_EXISTS")
        tools.execute([call("edit_file", path=path, operation="append", new_content="inserted")])
        self.assertEqual((self.root / path).read_text(), "inserted")

    def test_overlapping_old_content_is_ambiguous(self):
        path = "backend/src/repeated.ts"
        save_text(self.root / path, "aaa")
        tools = FileTools(self.root, ['backend'], stage='backend', writable=[path])
        with self.assertRaises(FileToolError) as failed:
            tools.execute([call("edit_file", path=path, operation="replace", old_content="aa", new_content="b")])
        self.assertEqual(failed.exception.feedback["code"], "OLD_CONTENT_NOT_UNIQUE")

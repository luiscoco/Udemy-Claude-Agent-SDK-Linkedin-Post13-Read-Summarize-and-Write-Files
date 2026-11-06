"""Offline completion and failure checks; no API key or network required."""
import contextlib
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from claude_agent_sdk import AssistantMessage, ResultMessage, ToolUseBlock
import lesson12 as app

SUMMARY = "# Project Summary\n\nA small local application that greets a user.\n"


def result(subtype="success", is_error=False):
    return ResultMessage(subtype=subtype, duration_ms=1, duration_api_ms=1,
                         is_error=is_error, num_turns=3, session_id="offline-test")


class WorkflowTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        # Keep disposable fixtures inside this writable project (also works in sandboxes).
        self.temp = tempfile.TemporaryDirectory(prefix="test-workspace-", dir=Path(__file__).resolve().parent)
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name)
        (self.project / "README.md").write_text("# Demo\nA small local greeting application.\n", encoding="utf-8")
        (self.project / "other.txt").write_text("Keep this file.", encoding="utf-8")
        self.output = self.project / "summary.md"
        self.log = contextlib.redirect_stdout(io.StringIO())
        self.log.__enter__()
        self.addCleanup(self.log.__exit__, None, None, None)

    def fake_query(self, content=SUMMARY, outcome=None, mutation=None):
        async def fake(**kwargs):
            yield AssistantMessage(model="offline", content=[ToolUseBlock(id="r1", name="Read", input={"file_path":str(self.project/"README.md")})])
            if content is not None:
                yield AssistantMessage(model="offline", content=[ToolUseBlock(id="w1", name="Write", input={"file_path":str(self.output)})])
                self.output.write_text(content, encoding="utf-8")
            if mutation:
                mutation()
            yield outcome if outcome is not None else result()
        return fake

    async def test_success_reads_back_artifact(self):
        with patch.object(app, "query", self.fake_query()):
            self.assertEqual(await app.run_workflow(self.project), SUMMARY)

    async def test_existing_output_refused_before_query(self):
        self.output.write_text("Important report", encoding="utf-8")
        with patch.object(app, "query") as query_mock:
            with self.assertRaisesRegex(app.LessonError, "already exists"):
                await app.run_workflow(self.project)
            query_mock.assert_not_called()
        self.assertEqual(self.output.read_text(), "Important report")

    async def test_explicit_overwrite(self):
        self.output.write_text("Old report", encoding="utf-8")
        with patch.object(app, "query", self.fake_query()):
            self.assertEqual(await app.run_workflow(self.project, overwrite=True), SUMMARY)

    async def test_success_claim_without_file_is_incomplete(self):
        with patch.object(app, "query", self.fake_query(content=None)):
            with self.assertRaises(app.LessonError):
                await app.run_workflow(self.project)

    async def test_empty_output_is_incomplete(self):
        with patch.object(app, "query", self.fake_query(content="  \n")):
            with self.assertRaisesRegex(app.LessonError, "empty"):
                await app.run_workflow(self.project)

    async def test_turn_limit_failure_even_when_file_exists(self):
        with patch.object(app, "query", self.fake_query(outcome=result("error_max_turns", True))):
            with self.assertRaisesRegex(app.LessonError, "error_max_turns"):
                await app.run_workflow(self.project)

    async def test_unrelated_change_detected(self):
        mutation = lambda: (self.project / "other.txt").write_text("Changed", encoding="utf-8")
        with patch.object(app, "query", self.fake_query(mutation=mutation)):
            with self.assertRaisesRegex(app.LessonError, "Unexpected workspace changes: other.txt"):
                await app.run_workflow(self.project)

    async def test_source_change_detected_on_stream_failure(self):
        async def broken_query(**kwargs):
            (self.project / "README.md").write_text("Changed", encoding="utf-8")
            raise app.ClaudeSDKError("Simulated SDK failure")
            yield  # Make this a simulated asynchronous stream.
        with patch.object(app, "query", broken_query):
            with self.assertRaisesRegex(app.LessonError, "README.md"):
                await app.run_workflow(self.project)

    async def test_missing_result_is_incomplete(self):
        async def empty_stream(**kwargs):
            if False:
                yield
        with patch.object(app, "query", empty_stream):
            with self.assertRaisesRegex(app.LessonError, "without a ResultMessage"):
                await app.run_workflow(self.project)

    def test_source_missing_and_empty(self):
        source = self.project / "README.md"
        source.write_text("", encoding="utf-8")
        with self.assertRaisesRegex(app.LessonError, "empty"):
            app.prepare_workspace(self.project)
        source.unlink()
        with self.assertRaisesRegex(app.LessonError, "regular README"):
            app.prepare_workspace(self.project)

    def test_content_contract(self):
        for text in ["Missing heading", "# Project Summary\n", "# Project Summary\n" + "word "*151]:
            with self.subTest(text=text[:30]):
                self.output.write_text(text, encoding="utf-8")
                with self.assertRaises(app.LessonError):
                    app.verify_output(self.output)


if __name__ == "__main__":
    unittest.main()

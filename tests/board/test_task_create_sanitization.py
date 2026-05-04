"""T-407: NUL byte sanitization on board write paths.

Verifies that Pydantic schema validation strips U+0000 from any free-form
string field before it can reach the database. Covers create + update paths
for tasks, epics, features, and the agent-facing note/artifact schemas.
"""

from __future__ import annotations

import uuid

from src.agent.schemas import (
    AddTaskNoteRequest,
    CompleteTaskRequest,
    ReportArtifactRequest,
    UpdateTaskStatusRequest,
)
from src.board.schemas import (
    CloseOffTaskCreate,
    EpicCreate,
    EpicUpdate,
    FeatureCreate,
    FeatureUpdate,
    ImportEpic,
    ImportFeature,
    ImportTask,
    TaskCreate,
    TaskUpdate,
)
from src.document.schemas import DocumentCreate

NUL = "\x00"


class TestTaskCreateSanitization:
    def test_nul_in_title_stripped(self) -> None:
        t = TaskCreate(title=f"hello{NUL}world", description="ok")
        assert "\x00" not in t.title
        assert t.title == "helloworld"

    def test_nul_in_description_stripped(self) -> None:
        t = TaskCreate(title="ok", description=f"desc{NUL}with{NUL}nul")
        assert "\x00" not in t.description
        assert t.description == "descwithnul"

    def test_nul_free_payload_unchanged(self) -> None:
        t = TaskCreate(title="clean", description="also clean")
        assert t.title == "clean"
        assert t.description == "also clean"

    def test_multiple_nul_bytes_all_stripped(self) -> None:
        t = TaskCreate(title=f"a{NUL}b{NUL}c{NUL}", description="")
        assert t.title == "abc"


class TestTaskUpdateSanitization:
    def test_nul_in_title_stripped(self) -> None:
        u = TaskUpdate(title=f"up{NUL}dated")
        assert u.title == "updated"

    def test_nul_in_description_stripped(self) -> None:
        u = TaskUpdate(description=f"new{NUL}desc")
        assert u.description == "newdesc"

    def test_none_fields_pass_through(self) -> None:
        u = TaskUpdate(title=None, description=None)
        assert u.title is None
        assert u.description is None


class TestEpicSanitization:
    def test_epic_create_nul_stripped(self) -> None:
        e = EpicCreate(title=f"ep{NUL}ic", description=f"de{NUL}sc")
        assert e.title == "epic"
        assert e.description == "desc"

    def test_epic_update_nul_stripped(self) -> None:
        e = EpicUpdate(title=f"up{NUL}d", context_description=f"ctx{NUL}")
        assert e.title == "upd"
        assert e.context_description == "ctx"


class TestFeatureSanitization:
    def test_feature_create_nul_stripped(self) -> None:
        f = FeatureCreate(title=f"fe{NUL}at")
        assert f.title == "feat"

    def test_feature_update_nul_stripped(self) -> None:
        f = FeatureUpdate(title=f"upd{NUL}")
        assert f.title == "upd"


class TestAgentSchemaSanitization:
    def test_add_task_note_nul_stripped(self) -> None:
        n = AddTaskNoteRequest(task_id=uuid.uuid4(), note=f"note{NUL}text")
        assert n.note == "notetext"

    def test_report_artifact_nul_stripped(self) -> None:
        r = ReportArtifactRequest(task_id=uuid.uuid4(), artifact_path=f"path{NUL}/to/file")
        assert r.artifact_path == "path/to/file"


class TestDocumentCreateSanitization:
    def test_document_content_nul_stripped(self) -> None:
        d = DocumentCreate(title=f"doc{NUL}", content=f"body{NUL}text")
        assert d.title == "doc"
        assert d.content == "bodytext"


class TestImportSchemaSanitization:
    def test_import_task_nul_stripped(self) -> None:
        t = ImportTask(title=f"im{NUL}port", description=f"de{NUL}sc")
        assert t.title == "import"
        assert t.description == "desc"

    def test_import_feature_nul_stripped(self) -> None:
        f = ImportFeature(title=f"fe{NUL}at", description=f"de{NUL}sc")
        assert f.title == "feat"
        assert f.description == "desc"

    def test_import_epic_nul_stripped(self) -> None:
        e = ImportEpic(title=f"ep{NUL}ic", description=f"de{NUL}sc", bounded_context=f"bc{NUL}x")
        assert e.title == "epic"
        assert e.description == "desc"
        assert e.bounded_context == "bcx"


class TestCloseOffTaskSanitization:
    def test_close_off_task_nul_stripped(self) -> None:
        c = CloseOffTaskCreate(worktree_path=f"/wt{NUL}/path", worktree_name=f"wt{NUL}name")
        assert c.worktree_path == "/wt/path"
        assert c.worktree_name == "wtname"


class TestAgentStatusSchemaSanitization:
    def test_complete_task_request_nul_stripped(self) -> None:
        r = CompleteTaskRequest(task_id=uuid.uuid4(), pr_url=f"https://github.com/x/y/pull/{NUL}1")
        assert r.pr_url == "https://github.com/x/y/pull/1"

    def test_update_task_status_nul_stripped(self) -> None:
        r = UpdateTaskStatusRequest(
            task_id=uuid.uuid4(),
            status=f"re{NUL}view",
            pr_url=f"https://github.com/x/y/pull/{NUL}2",
        )
        assert r.status == "review"
        assert r.pr_url == "https://github.com/x/y/pull/2"

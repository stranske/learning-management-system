"""What a malformed import file is told, and where.

`import_jsonl` refuses an import for a dozen distinct reasons, and every one of those messages
carries a LINE NUMBER or a record identity. That is the whole point: an import file is machine
output someone is re-feeding into a database, often thousands of lines long, and "invalid JSON" on
its own is not actionable.

None of those branches were reached. The tests below assert the message locates the problem, not
merely that an error was raised — a refusal that cannot be acted on is only marginally better than
a silent corruption.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from lms.auth.models import User
from lms.export_import import SCHEMA_VERSION, ExportImportError, import_jsonl


def _write(tmp_path: Path, *lines: str) -> Path:
    path = tmp_path / "import.jsonl"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _entry(record_type: str = "User", **record) -> str:
    payload = {"id": "user-1", "email": "a@example.test", "username": "a", "display_name": "A"}
    payload.update(record)
    return json.dumps({"type": record_type, "schema_version": SCHEMA_VERSION, "record": payload})


# ---------------------------------------------------------------------------------------------
# A valid file, so every refusal below is shown to be a refusal of something specific.
# ---------------------------------------------------------------------------------------------


def test_a_valid_file_validates(db_session: Session, tmp_path: Path):
    summary = import_jsonl(db_session, _write(tmp_path, _entry()), dry_run=True)

    assert summary.dry_run is True
    assert summary.counts == {"User": 1}


def test_blank_lines_are_skipped_not_counted(db_session: Session, tmp_path: Path):
    """A trailing newline is not a record. Counting it would report an import of n+1 rows."""
    summary = import_jsonl(db_session, _write(tmp_path, _entry(), "", "   "), dry_run=True)

    assert summary.counts == {"User": 1}


def test_a_dry_run_writes_nothing(db_session: Session, tmp_path: Path):
    """The whole reason `--dry-run` exists: validate a file against this database without
    touching it."""
    import_jsonl(db_session, _write(tmp_path, _entry()), dry_run=True)

    assert db_session.get(User, "user-1") is None


# ---------------------------------------------------------------------------------------------
# Line-level failures, each of which names its line.
# ---------------------------------------------------------------------------------------------


def test_invalid_json_names_the_line(db_session: Session, tmp_path: Path):
    """Third line of a thousand. Without the number the operator bisects the file by hand."""
    path = _write(
        tmp_path, _entry(), _entry(id="user-2", email="b@e.test", username="b"), "{ not json"
    )

    with pytest.raises(ExportImportError, match="line 3"):
        import_jsonl(db_session, path, dry_run=True)

    with pytest.raises(ExportImportError, match="invalid JSON"):
        import_jsonl(db_session, path, dry_run=True)


@pytest.mark.parametrize("payload", ["[1, 2, 3]", '"a string"', "42", "null"])
def test_an_entry_that_is_not_an_object_names_the_line(db_session, tmp_path: Path, payload):
    """All of these parse. The failure would otherwise be an AttributeError somewhere downstream
    with no line to point at."""
    path = _write(tmp_path, _entry(), payload)

    with pytest.raises(ExportImportError, match="line 2: entry must be an object"):
        import_jsonl(db_session, path, dry_run=True)


def test_an_unknown_record_type_is_quoted_back_with_its_line(db_session, tmp_path: Path):
    """A type from a newer export, or a typo. Quoting it is what tells the two apart."""
    line = json.dumps({"type": "Sprocket", "schema_version": SCHEMA_VERSION, "record": {"id": "x"}})

    with pytest.raises(ExportImportError, match="line 1: unknown type 'Sprocket'"):
        import_jsonl(db_session, _write(tmp_path, line), dry_run=True)


def test_a_wrong_schema_version_is_refused_before_anything_is_read(db_session, tmp_path: Path):
    """A future export's fields would be silently dropped, or a past one's silently defaulted.
    Refusing the whole file is the only safe answer."""
    line = json.dumps(
        {"type": "User", "schema_version": SCHEMA_VERSION + 1, "record": {"id": "user-1"}}
    )

    with pytest.raises(ExportImportError, match="line 1: unsupported schema_version"):
        import_jsonl(db_session, _write(tmp_path, line), dry_run=True)


def test_a_missing_schema_version_is_refused(db_session, tmp_path: Path):
    line = json.dumps({"type": "User", "record": {"id": "user-1"}})

    with pytest.raises(ExportImportError, match="unsupported schema_version"):
        import_jsonl(db_session, _write(tmp_path, line), dry_run=True)


def test_a_record_that_is_not_an_object_names_the_line(db_session, tmp_path: Path):
    line = json.dumps({"type": "User", "schema_version": SCHEMA_VERSION, "record": "user-1"})

    with pytest.raises(ExportImportError, match="line 1: record must be an object"):
        import_jsonl(db_session, _write(tmp_path, line), dry_run=True)


@pytest.mark.parametrize("bad_id", [42, None, ["user-1"], {"id": "user-1"}])
def test_a_non_string_record_id_names_the_line(db_session, tmp_path: Path, bad_id):
    """The id is the primary key and the deduplication key. A non-string one would compare unequal
    to every existing row and import as a new record."""
    line = json.dumps({"type": "User", "schema_version": SCHEMA_VERSION, "record": {"id": bad_id}})

    with pytest.raises(ExportImportError, match="line 1: record.id must be a string"):
        import_jsonl(db_session, _write(tmp_path, line), dry_run=True)


# ---------------------------------------------------------------------------------------------
# File-level failures, which name the record instead of the line.
# ---------------------------------------------------------------------------------------------


def test_a_duplicate_record_in_one_file_is_refused_by_identity(db_session, tmp_path: Path):
    """Two rows with one id: whichever lands second silently wins, and the file's own history of
    which is correct is lost. The message names the type and id rather than a line, because BOTH
    lines are implicated."""
    path = _write(tmp_path, _entry(), _entry(username="duplicate"))

    with pytest.raises(ExportImportError, match="duplicate import record User:user-1"):
        import_jsonl(db_session, path, dry_run=True)


def test_the_same_id_under_different_types_is_not_a_duplicate(db_session, tmp_path: Path):
    """Ids are unique per type, not globally. Refusing this would make a legitimate export
    unimportable."""
    user = _entry()
    learner = json.dumps(
        {
            "type": "Learner",
            "schema_version": SCHEMA_VERSION,
            "record": {"id": "user-1", "user_id": "user-1", "display_name": "A"},
        }
    )

    summary = import_jsonl(db_session, _write(tmp_path, user, learner), dry_run=True)

    assert summary.counts == {"User": 1, "Learner": 1}


def test_an_existing_record_is_refused_rather_than_overwritten(db_session, tmp_path: Path):
    """Import is additive. Silently overwriting would let a stale export undo newer work with no
    record that it happened."""
    db_session.add(User(id="user-1", email="a@example.test", username="a", display_name="A"))
    db_session.flush()

    with pytest.raises(ExportImportError, match="User:user-1 already exists"):
        import_jsonl(db_session, _write(tmp_path, _entry()), dry_run=True)


def test_a_missing_dependency_is_refused(db_session, tmp_path: Path):
    """A learner whose user is neither in the file nor in the database would import as an orphan —
    a row nobody can log in as and nothing links to."""
    learner = json.dumps(
        {
            "type": "Learner",
            "schema_version": SCHEMA_VERSION,
            "record": {"id": "learner-1", "user_id": "nobody", "display_name": "A"},
        }
    )

    with pytest.raises(ExportImportError):
        import_jsonl(db_session, _write(tmp_path, learner), dry_run=True)


def test_a_dependency_satisfied_within_the_same_file_is_accepted(db_session, tmp_path: Path):
    """The counterweight: an export writes parents and children into one file, so the check has to
    consider the file as well as the database. Requiring the parent to pre-exist would make every
    full export unimportable."""
    learner = json.dumps(
        {
            "type": "Learner",
            "schema_version": SCHEMA_VERSION,
            "record": {"id": "learner-1", "user_id": "user-1", "display_name": "A"},
        }
    )

    summary = import_jsonl(db_session, _write(tmp_path, _entry(), learner), dry_run=True)

    assert summary.counts == {"User": 1, "Learner": 1}


def test_a_dependency_already_in_the_database_is_accepted(db_session, tmp_path: Path):
    """The other half: importing a child into a database that already holds its parent."""
    db_session.add(User(id="user-9", email="z@example.test", username="z", display_name="Z"))
    db_session.flush()
    learner = json.dumps(
        {
            "type": "Learner",
            "schema_version": SCHEMA_VERSION,
            "record": {"id": "learner-1", "user_id": "user-9", "display_name": "Z"},
        }
    )

    summary = import_jsonl(db_session, _write(tmp_path, learner), dry_run=True)

    assert summary.counts == {"Learner": 1}


# ---------------------------------------------------------------------------------------------
# Applying.
# ---------------------------------------------------------------------------------------------


def test_applying_writes_the_records(db_session: Session, tmp_path: Path):
    summary = import_jsonl(db_session, _write(tmp_path, _entry()), dry_run=False)

    assert summary.dry_run is False
    assert summary.counts == {"User": 1}
    assert db_session.get(User, "user-1") is not None


def test_a_file_that_fails_validation_writes_nothing(db_session: Session, tmp_path: Path):
    """Validation runs over the WHOLE file before anything is applied, so a bad line at the end
    cannot leave the first half imported."""
    path = _write(tmp_path, _entry(), "{ not json")

    with pytest.raises(ExportImportError):
        import_jsonl(db_session, path, dry_run=False)

    assert db_session.get(User, "user-1") is None

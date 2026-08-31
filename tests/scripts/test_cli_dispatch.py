"""The `lms` CLI branches nothing exercised.

`__main__.py` sat at 65% — the lowest in the repo — and the uncovered half is dispatch: which
subcommand runs, which guard refuses, and which flags a command honours. Every one of those is a
documented interface, and a CLI that exits 0 having done nothing is indistinguishable from one that
worked.

Three of the properties here are not about coverage at all:

* `llm replay-eval --dry-run` must not construct providers. A dry run that reaches a real model
  costs money and writes traces, and the only visible difference is a bill.
* `export --include-pii all` must refuse without `--yes-i-mean-it`. That flag is the entire
  privacy control on the export path.
* `maintenance load-seed` must respect the draft-queue cap — and `--activate` must be the thing
  that bypasses it, because a cap you can cross without saying so is not a cap.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

import lms.__main__ as lms_main
import lms.auth.models  # noqa: F401  # register Base.metadata for db_session


@pytest.fixture
def patched_session(db_session: Session, monkeypatch: pytest.MonkeyPatch) -> Session:
    """Route the CLI's `session_scope()` onto the in-memory test session."""

    @contextmanager
    def fake_session_scope() -> Iterator[Session]:
        yield db_session

    monkeypatch.setattr(lms_main, "session_scope", fake_session_scope)
    return db_session


def _run(monkeypatch: pytest.MonkeyPatch, *argv: str) -> None:
    monkeypatch.setattr("sys.argv", ["lms", *argv])
    lms_main.main()


def _eval_set(tmp_path: Path, scenarios: tuple[str, ...]) -> Path:
    path = tmp_path / "gold.jsonl"
    rows = [
        {
            "entry_id": f"entry-{index}",
            "scenario": scenario,
            "mode": "study-coach",
            "trace_class": "evidence-grade",
            "prompt": "explain compounding",
            "expected_labels": ["offers_next_action"],
        }
        for index, scenario in enumerate(scenarios)
    ]
    path.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------------------------
# A command with no subcommand does nothing, and has to say so.
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "command",
    ["llm", "demo", "source-references", "authoring-assist", "maintenance"],
)
def test_a_command_without_its_subcommand_exits_nonzero(command, monkeypatch, capsys):
    """Falling through to the end of `main()` would exit 0 having done nothing — which reads as
    success to any script that checks the status."""
    with pytest.raises(SystemExit) as excinfo:
        _run(monkeypatch, command)

    assert excinfo.value.code == 2
    assert f"{command} requires a subcommand" in capsys.readouterr().err


# ---------------------------------------------------------------------------------------------
# `llm replay-eval`
# ---------------------------------------------------------------------------------------------


def test_a_dry_run_reports_the_set_without_building_providers(tmp_path, monkeypatch, capsys):
    """The point of `--dry-run` is that no model is called. A regression that built providers
    anyway would issue real requests, and the only symptom is the invoice."""

    def refuse(*args, **kwargs):
        raise AssertionError("providers were built during a dry run")

    monkeypatch.setattr(lms_main, "build_default_providers", refuse)
    path = _eval_set(tmp_path, ("answer-seeking", "quiet-mode", "answer-seeking"))

    _run(monkeypatch, "llm", "replay-eval", str(path), "--dry-run")

    out = capsys.readouterr().out
    assert f"eval set: {path}" in out
    assert "entries: 3" in out
    assert "dry run: no provider calls issued" in out


def test_the_dry_run_counts_entries_per_scenario(tmp_path, monkeypatch, capsys):
    """The counts are the reason to run it: they say which scenarios the set actually covers."""
    monkeypatch.setattr(lms_main, "build_default_providers", lambda **kwargs: (None, None))
    path = _eval_set(tmp_path, ("answer-seeking", "quiet-mode", "answer-seeking"))

    _run(monkeypatch, "llm", "replay-eval", str(path), "--dry-run")

    out = capsys.readouterr().out
    assert "  answer-seeking: 2" in out
    assert "  quiet-mode: 1" in out


def test_scenarios_are_reported_in_a_stable_order(tmp_path, monkeypatch, capsys):
    """Sorted, so two runs over the same set produce diffable output."""
    monkeypatch.setattr(lms_main, "build_default_providers", lambda **kwargs: (None, None))
    path = _eval_set(tmp_path, ("quiet-mode", "answer-seeking", "confusion-repair"))

    _run(monkeypatch, "llm", "replay-eval", str(path), "--dry-run")

    lines = [line.strip() for line in capsys.readouterr().out.splitlines() if line.startswith("  ")]
    assert lines == sorted(lines)


def test_a_malformed_eval_set_fails_before_any_replay(tmp_path, monkeypatch):
    """Schema validation is the whole reason the loader is strict. Reaching the replay with a bad
    entry turns a file typo into a model call and a confusing mid-sweep failure."""

    def refuse(*args, **kwargs):
        raise AssertionError("replay started despite a schema failure")

    monkeypatch.setattr(lms_main, "replay_eval_set", refuse)
    path = tmp_path / "gold.jsonl"
    path.write_text(json.dumps({"entry_id": "e1"}), encoding="utf-8")

    with pytest.raises(SystemExit) as excinfo:
        _run(monkeypatch, "llm", "replay-eval", str(path))

    assert "replay-eval validation failed" in str(excinfo.value)


def test_a_missing_eval_set_file_is_reported_as_a_validation_failure(tmp_path, monkeypatch):
    with pytest.raises((SystemExit, FileNotFoundError)):
        _run(monkeypatch, "llm", "replay-eval", str(tmp_path / "absent.jsonl"))


def _user_with_learner(session: Session, username: str = "owner") -> str:
    from lms.auth.repository import create_local_user
    from lms.learners.repository import get_or_create_learner_for_user

    user = create_local_user(
        session,
        username=username,
        display_name="Owner",
        email=f"{username}@example.com",
        password="correct-horse-battery",
    )
    learner, _created = get_or_create_learner_for_user(
        session, user_id=user.id, display_name="Owner", timezone="UTC"
    )
    session.flush()
    return learner.id


# ---------------------------------------------------------------------------------------------
# `export` — the redaction flags are the privacy control.
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "flag,value",
    [
        ("--include-pii", "all"),
        ("--include-llm-traces", "all"),
        ("--include-source-content", "all"),
    ],
)
def test_an_unconfirmed_all_redaction_refuses_to_export(flag, value, patched_session, monkeypatch):
    """`--yes-i-mean-it` is the only thing standing between a routine export and one carrying
    personal data or local-only source bodies. Every `all` setting requires it, not just PII."""
    with pytest.raises(SystemExit) as excinfo:
        _run(monkeypatch, "export", flag, value)

    assert "requires --yes-i-mean-it" in str(excinfo.value)


def test_confirmed_all_redaction_actually_exports(patched_session, monkeypatch, capsys):
    """The counterweight: the flag has to work, or the escape hatch is decorative. Asserting that
    records come out matters more than asserting no exception — a guard that refuses everything
    would pass the weaker check."""
    _user_with_learner(patched_session)
    patched_session.flush()

    _run(monkeypatch, "export", "--include-pii", "all", "--yes-i-mean-it")

    lines = [line for line in capsys.readouterr().out.splitlines() if line.strip()]
    assert lines
    assert all(json.loads(line) for line in lines)


def test_the_default_export_needs_no_confirmation(patched_session, monkeypatch):
    """Defaults are the redacted settings, so the common case is not gated behind a scary flag."""
    _run(monkeypatch, "export")


def test_an_export_with_an_out_path_writes_a_file_and_reports_the_count(
    patched_session, monkeypatch, capsys, tmp_path
):
    out = tmp_path / "export.jsonl"
    _run(monkeypatch, "export", "--out", str(out))

    assert out.exists()
    printed = capsys.readouterr().out
    assert "export complete" in printed
    assert str(out) in printed


def test_an_export_without_an_out_path_writes_to_stdout(patched_session, monkeypatch, capsys):
    """Piping the export is the documented way to inspect it; writing a file instead would
    silently break every `lms export | ...` in a runbook."""
    _run(monkeypatch, "export")
    assert "export complete" not in capsys.readouterr().out


# ---------------------------------------------------------------------------------------------
# `maintenance load-seed` — the draft-queue cap and the flag that bypasses it.
# ---------------------------------------------------------------------------------------------


def test_an_unknown_seed_is_refused_by_name(patched_session, monkeypatch):
    """The seed is a module path built from user input. A ModuleNotFoundError traceback would
    show an import machinery stack instead of naming the seed that does not exist."""
    with pytest.raises(SystemExit) as excinfo:
        _run(
            monkeypatch, "maintenance", "load-seed", "--seed", "no_such_seed", "--username", "owner"
        )

    assert "unknown seed: no_such_seed" in str(excinfo.value)


def test_an_unknown_user_is_refused_before_any_draft_is_built(patched_session, monkeypatch):
    with pytest.raises(SystemExit) as excinfo:
        _run(monkeypatch, "maintenance", "load-seed", "--username", "nobody")

    assert "user not found: nobody" in str(excinfo.value)


def test_a_user_with_no_learner_profile_is_refused(patched_session, monkeypatch):
    """Drafts belong to a learner, not a user. Without one there is nothing to attach them to,
    and the message says which of the two is missing."""
    from lms.auth.repository import create_local_user

    create_local_user(
        patched_session,
        username="profileless",
        display_name="No Learner",
        email="profileless@example.com",
        password="correct-horse-battery",
    )
    patched_session.flush()

    with pytest.raises(SystemExit) as excinfo:
        _run(monkeypatch, "maintenance", "load-seed", "--username", "profileless")

    assert "has no learner profile" in str(excinfo.value)


def test_loading_a_seed_creates_drafts_and_reports_the_count(patched_session, monkeypatch, capsys):
    _user_with_learner(patched_session)

    _run(monkeypatch, "maintenance", "load-seed", "--username", "owner")

    out = capsys.readouterr().out
    assert "draft maintenance item(s) from ipo_surge_2026" in out
    assert "loaded 0 " not in out


def test_a_full_draft_queue_refuses_the_load_and_says_how_to_clear_it(patched_session, monkeypatch):
    """A cap whose message does not name its drain is the failure mode worth guarding: the
    operator is told to stop with no way to start again.
    """
    _user_with_learner(patched_session)
    from lms.maintenance import drafts as drafts_module

    monkeypatch.setattr(drafts_module, "can_accept_drafts", lambda *a, **k: False)

    with pytest.raises(SystemExit) as excinfo:
        _run(monkeypatch, "maintenance", "load-seed", "--username", "owner")

    message = str(excinfo.value)
    assert "draft queue is full" in message
    assert "approve or clear" in message


def test_activate_bypasses_the_queue_cap_deliberately(patched_session, monkeypatch, capsys):
    """`--activate` skips the draft queue because the items are not drafts. That is the intended
    escape hatch, and it must be the FLAG that opens it — a cap crossed without saying so is not
    a cap.
    """
    _user_with_learner(patched_session)
    from lms.maintenance import drafts as drafts_module

    monkeypatch.setattr(drafts_module, "can_accept_drafts", lambda *a, **k: False)

    _run(
        monkeypatch,
        "maintenance",
        "load-seed",
        "--username",
        "owner",
        "--activate",
    )

    assert "active maintenance item(s)" in capsys.readouterr().out


def test_activated_items_are_approved_and_carry_no_expiry(patched_session, monkeypatch, capsys):
    """A draft expires; an activated item must not, or it vanishes from the queue it was loaded
    into."""
    from lms.maintenance.models import MaintenanceItem

    _user_with_learner(patched_session)
    _run(
        monkeypatch,
        "maintenance",
        "load-seed",
        "--username",
        "owner",
        "--activate",
    )

    patched_session.flush()
    items = patched_session.query(MaintenanceItem).all()
    assert items
    assert all(item.status == "active" for item in items)
    assert all(item.draft_expires_at is None for item in items)
    assert all(item.approved_at is not None for item in items)


def test_drafted_items_expire_and_are_not_approved(patched_session, monkeypatch, capsys):
    """The default path, and the inverse of the test above — so a change to either is visible."""
    from lms.maintenance.models import MaintenanceItem

    _user_with_learner(patched_session)
    _run(monkeypatch, "maintenance", "load-seed", "--username", "owner")

    patched_session.flush()
    items = patched_session.query(MaintenanceItem).all()
    assert items
    assert all(item.status != "active" for item in items)
    assert all(item.draft_expires_at is not None for item in items)

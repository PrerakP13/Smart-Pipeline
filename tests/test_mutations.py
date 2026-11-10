import json
import subprocess

import pytest

from experiments import run_mutations as mutations


def config_entry(identifier="flip"):
    return {"id": identifier, "path": "mod.py", "before": "return True", "after": "return False"}


@pytest.mark.parametrize(
    ("full", "selected", "status"),
    [
        ({"t"}, {"t"}, "killed"),
        ({"t"}, set(), "missed"),
        (set(), set(), "survived"),
        ({"t"}, {"u"}, "inconsistent"),
        (set(), {"u"}, "inconsistent"),
    ],
)
def test_fault_verdict_uses_matching_failure(full, selected, status):
    assert mutations.classify(full, selected) == status


def test_rates_exclude_survivors_and_invalid_trials():
    trials = [
        {"outcomes": {"file": "killed", "line": "missed"}},
        {"outcomes": {"file": "survived", "line": "survived"}},
        {"outcomes": {"file": "invalid_mutation", "line": "invalid_mutation"}},
    ]
    summary = mutations.summarize(trials)
    assert summary["file"]["fault_detection_pct"] == 100
    assert summary["line"]["missed_fault_pct"] == 100
    assert mutations.summarize(trials[1:])["line"]["missed_fault_pct"] is None


def test_invalid_edits_do_not_write_source(tmp_path):
    path = tmp_path / "mod.py"
    original = "def f():\n    return True\n"
    path.write_text(original)
    for changes in (
        {"after": "return ("},
        {"before": "missing"},
        {"before": "r"},  # repeated
        {"before": ""},
        {"after": "return True"},
        {"path": "../mod.py"},
    ):
        with pytest.raises(mutations.InvalidMutation):
            mutations.apply_mutation(tmp_path, config_entry() | changes)
        assert path.read_text() == original


def test_preserves_unrelated_bytes(tmp_path):
    path = tmp_path / "mod.py"
    path.write_bytes(b"def f():\r\n    return True\r\n")
    mutations.apply_mutation(tmp_path, config_entry())
    assert path.read_bytes() == b"def f():\r\n    return False\r\n"


def test_duplicate_ids_rejected_before_profiling(tmp_path):
    config = tmp_path / "mutants.json"
    config.write_text(json.dumps({"mutations": [config_entry(), config_entry()]}))
    with pytest.raises(ValueError, match="duplicate"):
        mutations.read_mutations(config)


def test_real_campaign_isolates_edits_and_uses_full_suite_oracle(tmp_path):
    subject = tmp_path / "subject"
    subject.mkdir()
    original = "def flag():\n    return True\n"
    (subject / "mod.py").write_text(original)
    (subject / "test_mod.py").write_text(
        "from mod import flag\n\ndef test_flag():\n    assert flag()\n"
    )
    for args in (
        ["init", "-q"],
        ["add", "mod.py", "test_mod.py"],
        ["-c", "user.name=Tester", "-c", "user.email=t@example.test", "commit", "-qm", "base"],
    ):
        subprocess.run(["git", *args], cwd=subject, check=True)
    # Dirty working files must neither contaminate the base nor be overwritten.
    dirty = original + "# unfinished local edit\n"
    (subject / "mod.py").write_text(dirty)
    cases = [
        config_entry("invalid") | {"after": "return ("},
        config_entry("bad-import") | {"before": "def flag():", "after": "import missing_example_module\n\ndef flag():"},
        config_entry(),
        config_entry("equivalent") | {"after": "return 1 == 1"},
    ]
    config = tmp_path / "mutants.json"
    config.write_text(json.dumps({"mutations": cases}))
    report = mutations.run_campaign(subject, "HEAD", tmp_path / "map.sqlite", config)
    assert [trial["outcomes"]["line"] for trial in report["trials"]] == [
        "invalid_mutation", "infrastructure_error", "killed", "survived"
    ]
    assert report["summary"]["file"]["evaluable_full_suite_kills"] == 1
    assert (subject / "mod.py").read_text() == dirty

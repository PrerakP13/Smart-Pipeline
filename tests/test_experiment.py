"""Run the user-facing CLI against a committed regression and a dirty checkout."""

import json
from pathlib import Path
import subprocess
import sys


PROJECT = Path(__file__).resolve().parents[1]


def git(repo, *args):
    return subprocess.check_output(["git", "-C", str(repo), *args])


def cli(mode, repo, base, database, *args):
    return subprocess.run(
        [sys.executable, "-m", "experiments.run_experiment", mode, "--repo", str(repo),
         "--base", base, "--db", str(database), *args],
        cwd=PROJECT, capture_output=True, text=True, timeout=90,
    )


def test_commit_comparison_reuses_baseline_and_preserves_dirty_checkout(tmp_path):
    repo = tmp_path / "subject with spaces"
    repo.mkdir()
    git(repo, "init", "-q")
    git(repo, "config", "user.name", "Tester")
    git(repo, "config", "user.email", "tester@example.invalid")

    original = "def price():\n    return 20\n\ndef tax():\n    return 5\n"
    source = repo / "pricing.py"
    source.write_text(original)
    (repo / "test_pricing.py").write_text(
        "from pricing import price, tax\n\n"
        "def test_price():\n    assert price() == 20\n\n"
        "def test_tax():\n    assert tax() == 5\n"
    )
    (repo / "test_other.py").write_text("def test_other():\n    assert True\n")
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "green baseline")
    base = git(repo, "rev-parse", "HEAD").decode().strip()

    # The new test passes. The old price test detects the seeded regression.
    source.write_text(original.replace("return 20", "return -1"))
    (repo / "test_new.py").write_text("def test_new():\n    assert True\n")
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "price regression and a new test")
    target = git(repo, "rev-parse", "HEAD").decode().strip()

    source.write_text("staged content, deliberately invalid Python\n")
    git(repo, "add", "pricing.py")
    dirty = "unstaged content, deliberately invalid Python\n"
    source.write_text(dirty)
    (repo / "test_untracked.py").write_text("raise RuntimeError('dirty checkout')\n")
    status_before = git(repo, "status", "--porcelain", "-z")
    index_before = git(repo, "ls-files", "--stage")

    db = tmp_path / "history.sqlite"
    capture = cli("baseline", repo, base, db)
    assert capture.returncode == 0, capture.stderr
    baseline = json.loads(capture.stdout)
    assert (baseline["base"], baseline["test_count"]) == (base, 3)
    snapshot = db.read_bytes()

    result_file = tmp_path / "report.json"
    compared = cli("compare", repo, base, db, "--target", target, "--output", str(result_file))
    assert compared.returncode == 0, compared.stderr
    report = json.loads(result_file.read_text())
    assert report["target_head"] == target
    assert report["base"] == base
    assert {c["new_path"] for c in report["changes"]} == {"pricing.py", "test_new.py"}
    assert report["full"]["count"] == 4
    failure = "test_pricing.py::test_price"
    assert report["full"]["failed"] == [failure]
    new_test = "test_new.py::test_new"
    assert set(report["strategies"]["line"]["selected"]) == {failure, new_test}
    assert set(report["strategies"]["file"]["selected"]) == {
        failure, new_test, "test_pricing.py::test_tax",
    }
    for run in report["strategies"].values():
        assert run["failed"] == [failure]
        assert run["metrics"]["failure_retention_pct"] == 100
        assert run["metrics"]["missed_failures"] == []

    selective = cli("run", repo, base, db, "--target", target, "--strategy", "line")
    assert selective.returncode == 1
    run = json.loads(selective.stdout)
    assert set(run["selected"]) == {failure, new_test}
    assert run["failed"] == [failure]
    assert "full" not in run

    missing = cli("compare", repo, target, db, "--target", target)
    assert missing.returncode != 0
    assert "No coverage snapshot" in missing.stderr
    assert db.read_bytes() == snapshot
    assert git(repo, "status", "--porcelain", "-z") == status_before
    assert git(repo, "ls-files", "--stage") == index_before
    assert git(repo, "rev-parse", "HEAD").decode().strip() == target
    assert source.read_text() == dirty

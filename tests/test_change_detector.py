import subprocess

import pytest

from src.change_detector import Change, detect_changes, git_root, resolve_commit


def git(repo, *args):
    return subprocess.check_output(["git", "-C", str(repo), *args])


@pytest.fixture
def repo(tmp_path):
    git(tmp_path, "init", "-q")
    git(tmp_path, "config", "user.name", "TestMind")
    git(tmp_path, "config", "user.email", "tester@example.invalid")
    (tmp_path / ".gitignore").write_text("*.cache\n")
    (tmp_path / "base.py").write_text("a\nb\nc\nd\ne\nf\ng\nh\n")
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-qm", "base")
    return tmp_path


def test_repo_and_commit_resolution(repo):
    (repo / "nested").mkdir()
    assert git_root(repo / "nested") == repo
    assert resolve_commit(repo, "HEAD") == git(repo, "rev-parse", "HEAD").decode().strip()
    assert detect_changes(repo, "HEAD") == []
    with pytest.raises(ValueError):
        resolve_commit(repo, "--all")
    with pytest.raises(ValueError):
        git_root(repo.parent)


def test_staged_and_unstaged_are_compared_as_one_final_worktree(repo):
    source = repo / "base.py"
    source.write_text("a\nB\nc\nd\ne\nf\ng\nh\n")
    git(repo, "add", "base.py")
    source.write_text("a\nb\nc\nd\nE\nf\ng\nh\ninsert\n")
    assert detect_changes(repo, "HEAD") == [
        Change("M", "base.py", "base.py", frozenset({5}), True)
    ]


def test_commit_pair_uses_baseline_coordinates_and_ignores_worktree(repo):
    source = repo / "base.py"
    source.write_text("a\nc\nd\ne\nf\ng\nh\n")
    git(repo, "commit", "-qam", "remove line 2")
    source.unlink()
    (repo / "unexpected.py").touch()
    assert detect_changes(repo, "HEAD^", "HEAD") == [
        Change("M", "base.py", "base.py", frozenset({2}))
    ]


def test_untracked_renames_ignored_files_and_index_preservation(repo):
    new_name = "-renamed [module].py"
    (repo / "base.py").rename(repo / new_name)
    (repo / new_name).write_text("a\nb\nC\nd\ne\nf\ng\nh\n")
    (repo / "ignored.cache").touch()
    (repo / "[new].py").write_text("pass\n")
    before = git(repo, "ls-files", "--stage")
    changes = detect_changes(repo, "HEAD")
    assert Change("A", None, "[new].py", frozenset(), True) in changes
    assert Change("R", "base.py", new_name, frozenset({3})) in changes
    assert len(changes) == 2
    assert git(repo, "ls-files", "--stage") == before


def test_staged_rename_and_delete(repo):
    git(repo, "mv", "base.py", "moved.py")
    assert detect_changes(repo, "HEAD") == [
        Change("R", "base.py", "moved.py", frozenset())
    ]
    git(repo, "commit", "-qm", "rename")
    (repo / "moved.py").unlink()
    assert detect_changes(repo, "HEAD") == [
        Change("D", "moved.py", None, frozenset(range(1, 9)))
    ]

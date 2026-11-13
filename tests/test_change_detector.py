
import pytest
from git import Repo

from src.change_detector import detect_changes, ChangeDetectionError


@pytest.fixture
def git_repo(tmp_path):
    """Create a temporary Git repository for testing."""
    repo = Repo.init(tmp_path)

    with repo.config_writer() as config:
        config.set_value("user", "name", "Test User")
        config.set_value("user", "email", "test@example.com")

    return repo


def commit_changes(repo, message):
    """Stage all changes and create a commit."""
    repo.git.add(A=True)
    return repo.index.commit(message)


def test_detect_modified_file(git_repo):
    repo = git_repo
    file = repo.working_tree_dir + "/example.py"

    with open(file, "w") as f:
        f.write("print('hello')\n")

    base = commit_changes(repo, "Initial commit")

    with open(file, "w") as f:
        f.write("print('updated')\n")

    target = commit_changes(repo, "Update example")

    result = detect_changes(repo.working_tree_dir, base.hexsha, target.hexsha)

    assert result["modified"] == ["example.py"]
    assert result["added"] == []
    assert result["deleted"] == []
    assert result["renamed"] == []


def test_detect_added_file(git_repo):
    repo = git_repo

    with open(repo.working_tree_dir + "/existing.py", "w") as f:
        f.write("print('existing')\n")

    base = commit_changes(repo, "Initial commit")

    with open(repo.working_tree_dir + "/new.py", "w") as f:
        f.write("print('new')\n")

    target = commit_changes(repo, "Add new file")

    result = detect_changes(repo.working_tree_dir, base.hexsha, target.hexsha)

    assert result["added"] == ["new.py"]


def test_detect_deleted_file(git_repo):
    repo = git_repo
    file = repo.working_tree_dir + "/remove.py"

    with open(file, "w") as f:
        f.write("print('remove me')\n")

    base = commit_changes(repo, "Initial commit")

    import os
    os.remove(file)

    target = commit_changes(repo, "Delete file")

    result = detect_changes(repo.working_tree_dir, base.hexsha, target.hexsha)

    assert result["deleted"] == ["remove.py"]


def test_detect_renamed_file(git_repo):
    repo = git_repo
    old_file = repo.working_tree_dir + "/old_name.py"
    new_file = repo.working_tree_dir + "/new_name.py"

    with open(old_file, "w") as f:
        f.write("def calculate_total(items):\n")
        f.write("    return sum(items)\n")

    base = commit_changes(repo, "Initial commit")

    import os
    os.rename(old_file, new_file)

    target = commit_changes(repo, "Rename file")

    result = detect_changes(repo.working_tree_dir, base.hexsha, target.hexsha)

    assert result["renamed"] == [
        {
            "old_path": "old_name.py",
            "new_path": "new_name.py"
        }
    ]


def test_invalid_repository():
    with pytest.raises(ChangeDetectionError):
        detect_changes(
            "nonexistent_repository",
            "abc123",
            "def456"
        )


def test_invalid_commit(git_repo):
    repo = git_repo

    with open(repo.working_tree_dir + "/example.py", "w") as f:
        f.write("print('hello')\n")

    commit = commit_changes(repo, "Initial commit")

    with pytest.raises(ChangeDetectionError):
        detect_changes(
            repo.working_tree_dir,
            commit.hexsha,
            "invalid_commit"
        )
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

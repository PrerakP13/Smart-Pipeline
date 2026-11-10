"""Compare a baseline Git commit to another commit or the current working tree."""

from contextlib import contextmanager
from dataclasses import dataclass
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile


@dataclass(frozen=True)
class Change:
    """Paths are repository-relative. Line numbers are 1-based in the baseline."""

    status: str
    old_path: str | None
    new_path: str | None
    old_lines: frozenset[int]
    has_insertions: bool = False  # At least one hunk has no baseline lines.


def _git(repo, *args, env=None, input_bytes=None):
    result = subprocess.run(
        ["git", "--literal-pathspecs", "-C", str(repo), *args],
        input=input_bytes,
        capture_output=True,
        env=env,
    )
    if result.returncode:
        raise ValueError(os.fsdecode(result.stderr).strip() or "Git command failed")
    return result.stdout


def git_root(repo: Path) -> Path:
    """Return the root of the Git worktree containing repo."""
    path = _git(repo, "rev-parse", "--show-toplevel")
    return Path(os.fsdecode(path.removesuffix(b"\n")))


def resolve_commit(repo: Path, ref: str) -> str:
    """Resolve a revision or tag to an immutable commit ID."""
    output = _git(repo, "rev-parse", "--verify", "--end-of-options", ref + "^{commit}")
    return output.decode("ascii").strip()


@contextmanager
def _worktree_index(repo):
    """Make untracked paths visible to Git's normal diff and rename detection."""
    if _git(repo, "ls-files", "--unmerged"):
        raise ValueError("Resolve Git merge conflicts before detecting changes")
    untracked = _git(repo, "ls-files", "--others", "--exclude-standard", "-z")
    if not untracked:
        yield None
        return

    # Intent-to-add lets Git read file contents from disk. Never stage the
    # user's files in their actual index, even if a command fails.
    real_index = _git(repo, "rev-parse", "--path-format=absolute", "--git-path", "index")
    with tempfile.TemporaryDirectory() as directory:
        index = Path(directory) / "index"
        real_index = Path(os.fsdecode(real_index.removesuffix(b"\n")))
        if real_index.exists():
            shutil.copyfile(real_index, index)
        env = {**os.environ, "GIT_INDEX_FILE": str(index)}
        _git(repo, "add", "--intent-to-add", "--pathspec-from-file=-",
             "--pathspec-file-nul", env=env, input_bytes=untracked)
        yield env


_HUNK = re.compile(rb"^@@ -(\d+)(?:,(\d+))? \+\d+(?:,\d+)? @@", re.MULTILINE)


def _read_diff(repo, revisions, env=None):
    command = ("diff", "--no-ext-diff", "--no-textconv", "--find-renames",
               "--ignore-submodules=none", "--no-color", *revisions)
    raw = _git(repo, *command, "--name-status", "-z", "--", env=env)
    fields = iter(os.fsdecode(raw).split("\0")[:-1])
    changes = []
    for entry in fields:
        status = entry[0]  # Git appends a similarity score for renames.
        path = next(fields)
        old_path = None if status == "A" else path
        new_path = None if status == "D" else path
        paths = [path]
        if status == "R":
            new_path = next(fields)
            paths.append(new_path)

        lines = set()
        insertions = status == "A"
        if old_path is not None:
            patch = _git(repo, *command, "--unified=0", "--inter-hunk-context=0",
                         "--", *paths, env=env)
            for start, length in _HUNK.findall(patch):
                first, count = int(start), int(length or b"1")
                lines.update(range(first, first + count))
                if count == 0:
                    insertions = True
        changes.append(Change(status, old_path, new_path, frozenset(lines), insertions))
    return changes


def detect_changes(repo: Path, base: str, target: str | None = None) -> list[Change]:
    """Detect changes at all paths, including additions, deletions and renames.

    A commit target ignores the working tree. Omitting the target compares the
    baseline with the final on-disk content, including untracked nonignored
    files. Git's similarity threshold determines whether a move is recognized
    as a rename or reported as a deletion and an addition.
    """
    root = git_root(repo)
    baseline = resolve_commit(root, base)
    if target is not None:
        return _read_diff(root, [baseline, resolve_commit(root, target)])
    with _worktree_index(root) as env:
        return _read_diff(root, [baseline], env)

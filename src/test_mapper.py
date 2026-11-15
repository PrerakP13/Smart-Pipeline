"""Persist reusable coverage snapshots in SQLite, keyed by the baseline commit."""

import json
import sqlite3
from contextlib import closing
from pathlib import Path

CoverageMap = dict[str, dict[str, set[int]]]
SharedLines = dict[str, set[int]]

# Version 2 includes Python subprocess execution. Older captures can silently
# omit CLI dependencies, even when the subject revision has not changed.
CAPTURE_VERSION = 2

_TABLES = (
    "CREATE TABLE IF NOT EXISTS snapshots (revision TEXT PRIMARY KEY)",
    """CREATE TABLE IF NOT EXISTS capture_versions (
           revision TEXT PRIMARY KEY, version INTEGER NOT NULL,
           FOREIGN KEY (revision) REFERENCES snapshots ON DELETE CASCADE)""",
    """CREATE TABLE IF NOT EXISTS tests (
           revision TEXT, nodeid TEXT, PRIMARY KEY (revision, nodeid),
           FOREIGN KEY (revision) REFERENCES snapshots ON DELETE CASCADE)""",
    """CREATE TABLE IF NOT EXISTS coverage (
           revision TEXT, nodeid TEXT, path TEXT, lines TEXT NOT NULL,
           PRIMARY KEY (revision, nodeid, path),
           FOREIGN KEY (revision, nodeid) REFERENCES tests ON DELETE CASCADE)""",
    """CREATE TABLE IF NOT EXISTS shared (
           revision TEXT, path TEXT, lines TEXT NOT NULL,
           PRIMARY KEY (revision, path),
           FOREIGN KEY (revision) REFERENCES snapshots ON DELETE CASCADE)""",
)


def save_map(path: Path, commit: str, mapping: CoverageMap, shared: SharedLines) -> None:
    """Replace one complete snapshot atomically, preserving other revisions."""
    if not commit:
        raise ValueError("A coverage snapshot requires a baseline commit")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path)) as db, db:
        db.execute("PRAGMA foreign_keys = ON")
        db.execute("BEGIN IMMEDIATE")
        for sql in _TABLES:
            db.execute(sql)
        db.execute("DELETE FROM snapshots WHERE revision = ?", (commit,))
        db.execute("INSERT INTO snapshots VALUES (?)", (commit,))
        db.execute("INSERT INTO capture_versions VALUES (?, ?)", (commit, CAPTURE_VERSION))
        db.executemany("INSERT INTO tests VALUES (?, ?)",
                       ((commit, nodeid) for nodeid in mapping))
        # A row per edge keeps the database compact and preserves empty line sets.
        db.executemany("INSERT INTO coverage VALUES (?, ?, ?, ?)", (
            (commit, nodeid, filename, json.dumps(sorted(lines)))
            for nodeid, files in mapping.items() for filename, lines in files.items()
        ))
        db.executemany("INSERT INTO shared VALUES (?, ?, ?)", (
            (commit, filename, json.dumps(sorted(lines))) for filename, lines in shared.items()
        ))


def load_map(path: Path, commit: str) -> tuple[CoverageMap, SharedLines]:
    """Read the inventory and measured lines for exactly one captured commit."""
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"Coverage database does not exist: {path}")
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as db:
        # Pin one read transaction across the inventory, coverage, and shared lines.
        db.execute("BEGIN")
        if not db.execute("SELECT 1 FROM snapshots WHERE revision = ?", (commit,)).fetchone():
            raise ValueError(f"No coverage snapshot for baseline commit {commit}")
        versions = db.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'capture_versions'"
        ).fetchone()
        if not versions or db.execute(
            "SELECT version FROM capture_versions WHERE revision = ?", (commit,)
        ).fetchone() != (CAPTURE_VERSION,):
            raise ValueError(
                "Coverage snapshot uses an incompatible collector version. "
                "Run the baseline command again to capture Python subprocess coverage."
            )
        mapping: CoverageMap = {nodeid: {} for (nodeid,) in
                                db.execute("SELECT nodeid FROM tests WHERE revision = ?", (commit,))}
        for nodeid, filename, lines in db.execute(
            "SELECT nodeid, path, lines FROM coverage WHERE revision = ?", (commit,)
        ):
            mapping[nodeid][filename] = set(json.loads(lines))
        shared = {filename: set(json.loads(lines)) for filename, lines in db.execute(
            "SELECT path, lines FROM shared WHERE revision = ?", (commit,)
        )}
    return mapping, shared

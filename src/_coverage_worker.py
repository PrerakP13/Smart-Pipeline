"""Private single-process pytest worker for baseline line attribution."""

import json
from pathlib import Path
import sys

if __name__ == "__main__" and sys.path[0] == str(Path(__file__).resolve().parent):
    # Keep TestMind modules off the subject import path.
    sys.path.pop(0)

from coverage import Coverage
import pytest


class CoveragePlugin:
    def __init__(self, tracer):
        self.tracer = tracer
        self.nodeids = []
        self.finished = set()
        self.failed = set()
        self.current = ""

    def switch(self, context):
        previous = self.current
        self.current = context
        self.tracer.switch_context(context)
        return previous

    def pytest_configure(self, config):
        if config.getoption("numprocesses", default=0):
            raise pytest.UsageError("TestMind coverage requires single-process pytest (use -n0).")
        if config.getoption("cov_source", default=[]) and not config.getoption("no_cov", default=False):
            raise pytest.UsageError("Disable pytest-cov (--no-cov) while collecting TestMind coverage.")

    def pytest_collection_finish(self, session):
        self.nodeids = [item.nodeid for item in session.items]

    def pytest_runtest_logreport(self, report):
        if report.failed:
            self.failed.add(report.nodeid)
        if report.when == "teardown":
            self.finished.add(report.nodeid)

    @pytest.hookimpl(wrapper=True, tryfirst=True)
    def pytest_runtest_protocol(self, item, nextitem):
        previous = self.switch("test:" + item.nodeid)
        try:
            return (yield)
        finally:
            self.switch(previous)

    @pytest.hookimpl(wrapper=True, tryfirst=True)
    def pytest_fixture_setup(self, fixturedef, request):
        # A module/session fixture may run only for the first of many consumers.
        if request.scope == "function":
            return (yield)
        previous = self.switch("")
        try:
            return (yield)
        finally:
            self.switch(previous)

    @pytest.hookimpl(wrapper=True, tryfirst=True)
    def pytest_runtest_teardown(self, item, nextitem):
        # pytest can finalize either local or shared fixtures here. Keep the
        # attribution to this item as well as a conservative shared-line entry.
        previous = self.switch("teardown:" + item.nodeid)
        try:
            return (yield)
        finally:
            self.switch(previous)


def collect(report_path):
    root = Path.cwd().resolve()
    tracer = Coverage(
        source=[str(root)], omit=["*/site-packages/*", "*/dist-packages/*"],
        config_file=False, data_file=None,
    )
    plugin = CoveragePlugin(tracer)
    tracer.start()
    try:
        status = pytest.main(["-q", "--rootdir=.", "-p", "no:cacheprovider"], plugins=[plugin])
    finally:
        tracer.stop()
    if status:
        return status
    if not plugin.nodeids:
        raise RuntimeError("No pytest items were observed in the baseline process.")
    if plugin.failed or plugin.finished != set(plugin.nodeids):
        raise RuntimeError("Coverage requires a complete baseline with no failed tests.")
    if len(set(plugin.nodeids)) != len(plugin.nodeids):
        raise RuntimeError("Duplicate pytest node IDs cannot identify distinct baseline tests.")

    tests = {nodeid: {} for nodeid in plugin.nodeids}
    shared = {}
    data = tracer.get_data()
    for filename in sorted(data.measured_files()):
        path = Path(filename)
        if path.suffix != ".py" or not path.is_relative_to(root):
            continue
        relative = path.relative_to(root).as_posix()
        for line, contexts in sorted(data.contexts_by_lineno(filename).items()):
            for context in contexts:
                phase, _, nodeid = context.partition(":")
                if phase in {"test", "teardown"}:
                    tests[nodeid].setdefault(relative, []).append(line)
                if phase in {"", "teardown"}:
                    shared.setdefault(relative, set()).add(line)
    report_path.write_text(json.dumps({
        "tests": tests, "shared": {path: sorted(lines) for path, lines in shared.items()},
    }), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(collect(Path(sys.argv[1])))

"""Attribute pytest and Python child-process coverage to baseline test IDs."""

import json
import os
from pathlib import Path
import subprocess
import sys

if __name__ == "__main__" and sys.path[0] == str(Path(__file__).resolve().parent):
    # Keep TestMind modules off the subject import path.
    sys.path.pop(0)

from coverage import Coverage
import pytest


CONTEXT_VARIABLE = "TESTMIND_COVERAGE_CONTEXT"


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
        # A child inherits this value at launch, even if it finishes after the
        # parent switches context. Its coverage config uses it as static context.
        os.environ[CONTEXT_VARIABLE] = context
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
    report_path = report_path.resolve()
    config = report_path.with_suffix(".toml")
    # TOML strings are JSON-compatible. Escape dollars in literal paths because
    # coverage also expands environment variables inside its configuration.
    def literal(path):
        return json.dumps(str(path).replace("$", "$$"), ensure_ascii=False)
    config.write_text(
        "[tool.coverage.run]\n"
        f"source = [{literal(root)}]\n"
        'omit = ["*/site-packages/*", "*/dist-packages/*"]\n'
        f"data_file = {literal(report_path.parent / '.coverage')}\n"
        "parallel = true\n"
        'patch = ["subprocess"]\n'
        f'context = "${{{CONTEXT_VARIABLE}}}"\n',
        encoding="utf-8",
    )
    os.environ[CONTEXT_VARIABLE] = ""
    tracer = Coverage(config_file=str(config))
    plugin = CoveragePlugin(tracer)
    tracer.start()
    # The native patch installs a temporary startup hook in this Python
    # environment. Its serialized config freezes the initial empty context, so
    # children must read our config using their launch-time context instead.
    os.environ.pop("COVERAGE_PROCESS_CONFIG", None)
    os.environ["COVERAGE_PROCESS_START"] = str(config)
    try:
        probe = subprocess.run(
            [sys.executable, "-c",
             "from coverage import Coverage; raise SystemExit(Coverage.current() is None)"],
            capture_output=True, text=True,
        )
        if probe.returncode:
            raise RuntimeError(
                "Python subprocess coverage could not start. Use a writable virtual "
                "environment with coverage installed.\n" + probe.stderr
            )
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
    tracer.save()
    tracer.combine(data_paths=[str(report_path.parent)])
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

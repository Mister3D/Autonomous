"""A crashed CDP worker must surface the exception, not the traceback header."""

from autonomous.services.browser import _cdp_failure_text


def test_failure_text_keeps_the_exception_line():
    err = (
        "Traceback (most recent call last):\n"
        '  File "/home/autonomous/workspace/.autonomous/_chrome_cdp_worker.py", '
        "line 1013, in <module>\n"
        "    sys.exit(main(sys.argv))\n"
        "TimeoutError: timed out waiting for page\n"
    )
    assert _cdp_failure_text(err) == "TimeoutError: timed out waiting for page"


def test_failure_text_is_empty_output_when_stderr_is_blank():
    assert _cdp_failure_text("") == "empty output"
    assert _cdp_failure_text("   \n") == "empty output"


def test_worker_returns_the_exception_instead_of_dying(capsys, monkeypatch):
    import sys
    import types

    stub = types.ModuleType("cdp_client")

    class CdpError(RuntimeError):
        pass

    stub.CdpError = CdpError
    stub.connect_page = lambda *a, **k: None
    stub.connect_target = lambda *a, **k: None

    def boom(*_args, **_kwargs):
        raise RuntimeError("boom")

    stub.list_targets = boom
    monkeypatch.setitem(sys.modules, "cdp_client", stub)
    sys.modules.pop("autonomous.services.chrome_cdp_worker", None)
    import autonomous.services.chrome_cdp_worker as worker

    code = worker.main(["worker", "tabs"])
    assert code == 1
    err = capsys.readouterr().out.strip().splitlines()[-1]
    assert "RuntimeError: boom" in err
    assert "Traceback" not in err

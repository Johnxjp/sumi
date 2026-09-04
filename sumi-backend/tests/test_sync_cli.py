import asyncio
from unittest import mock

import pytest

import scripts.sync as sync_cli
from src.notion.sync import SyncReport, describe_index_staleness


def run_cli(argv: list[str]) -> None:
    with mock.patch("sys.argv", ["scripts.sync", *argv]):
        asyncio.run(sync_cli.main())


@pytest.fixture
def run_sync():
    with mock.patch.object(sync_cli, "run_sync", autospec=True) as patched:

        async def succeed(**kwargs):
            return SyncReport()

        patched.side_effect = succeed
        yield patched


@pytest.mark.parametrize(
    ("argv", "expected"),
    [
        ([], {"mode": "incremental", "reindex": False, "limit": None}),
        (["--full"], {"mode": "full", "reindex": False, "limit": None}),
        (["--reindex"], {"mode": "incremental", "reindex": True, "limit": None}),
        (["--limit", "20"], {"mode": "incremental", "reindex": False, "limit": 20}),
    ],
    ids=["default-is-incremental", "full", "reindex", "limit"],
)
def test_flags_reach_run_sync(run_sync, argv, expected):
    run_cli(argv)

    kwargs = run_sync.call_args.kwargs
    assert {key: kwargs[key] for key in expected} == expected


@pytest.mark.parametrize(
    ("flag", "key"), [("--dry-run", "dry_run"), ("--mirror-only", "mirror_only")]
)
def test_mode_flags_reach_run_sync(run_sync, flag, key):
    run_cli([flag])
    assert run_sync.call_args.kwargs[key] is True


def test_progress_is_off_unless_asked_for(run_sync):
    run_cli([])
    assert run_sync.call_args.kwargs["on_progress"] is None

    run_cli(["--verbose"])
    assert run_sync.call_args.kwargs["on_progress"] is not None


@pytest.mark.parametrize(
    "report",
    [SyncReport(status="failed"), SyncReport(pages_failed=1)],
    ids=["the-run-failed", "a-page-failed"],
)
def test_a_failure_exits_non_zero(report):
    async def fail(**kwargs):
        return report

    with (
        mock.patch.object(sync_cli, "run_sync", autospec=True, side_effect=fail),
        pytest.raises(SystemExit) as exit_info,
    ):
        run_cli([])
    assert exit_info.value.code == 1


def test_a_clean_run_exits_zero(run_sync):
    run_cli([])


def test_the_report_describes_what_happened():
    report = SyncReport(
        mode="full",
        pages_listed=3,
        pages_indexed=2,
        pages_failed=1,
        failed_pages=["abc"],
        dropped_tags={"embed": 2},
    )

    described = report.describe()

    assert "full sync ok" in described
    assert "pages listed:  3" in described
    assert "embed x2" in described
    assert "abc" in described


def test_staleness_is_none_without_a_reachable_database():
    assert describe_index_staleness("postgresql://localhost:1/does-not-exist") is None

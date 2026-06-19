from pathlib import Path

from activity_monitor import cli

FIXTURE = Path(__file__).parent / "fixtures" / "sample_collection.json"


def test_full_flow_init_ingest_report(tmp_path, capsys):
    dbfile = str(tmp_path / "activity.db")
    config = tmp_path / "config.toml"
    config.write_text(
        "[thresholds]\ncritical_total_max = 0\nwarn_total_min = 3\nwarn_pr_created_min = 1\n"
    )
    out = tmp_path / "reports"

    assert cli.main(["--db", dbfile, "init-db"]) == 0
    assert cli.main(["--db", dbfile, "ingest", str(FIXTURE)]) == 0
    assert cli.main(["--db", dbfile, "detect", "--config", str(config)]) == 0
    rc = cli.main(["--db", dbfile, "report", "--config", str(config), "--out", str(out)])
    assert rc == 0

    reports = list(out.glob("activity-*.md"))
    assert len(reports) == 1
    body = reports[0].read_text(encoding="utf-8")
    assert "baz" in body and "critical" in body.lower()


def test_report_without_data_returns_error(tmp_path):
    dbfile = str(tmp_path / "empty.db")
    cli.main(["--db", dbfile, "init-db"])
    rc = cli.main(["--db", dbfile, "report", "--out", str(tmp_path / "r")])
    assert rc == 1

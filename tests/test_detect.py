from pathlib import Path

from activity_monitor import detect, ingest, models

FIXTURE = Path(__file__).parent / "fixtures" / "sample_collection.json"
T = detect.Thresholds(critical_total_max=0, warn_total_min=3, warn_pr_created_min=1)


def _row(total, pr_created=1, pr_reviews=0, issue_comments=0, pr_review_comments=0):
    return {
        "user_id": 1, "login": "x", "total": total, "pr_created": pr_created,
        "pr_reviews": pr_reviews, "issue_comments": issue_comments,
        "pr_review_comments": pr_review_comments,
    }


def test_classify_critical_when_total_at_or_below_max():
    status, reasons = detect.classify(_row(total=0, pr_created=0), T)
    assert status == "critical"
    assert reasons  # 理由が付く


def test_classify_warn_when_total_below_min():
    status, _ = detect.classify(_row(total=2, pr_created=1), T)
    assert status == "warn"


def test_classify_warn_when_no_pr_created_despite_activity():
    # 合計は足りるが PR 作成が無い → warn
    status, reasons = detect.classify(_row(total=5, pr_created=0, issue_comments=5), T)
    assert status == "warn"
    assert any("PR" in r for r in reasons)


def test_classify_ok_at_boundary():
    # total == warn_total_min(3), pr_created == warn_pr_created_min(1) は ok
    status, reasons = detect.classify(_row(total=3, pr_created=1), T)
    assert status == "ok"
    assert reasons == []


def test_classify_critical_precedence_over_warn():
    status, _ = detect.classify(_row(total=0, pr_created=0), T)
    assert status == "critical"  # warn ではなく critical


def test_load_thresholds_from_toml(tmp_path):
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        "[thresholds]\n"
        "critical_total_max = 1\n"
        "warn_total_min = 5\n"
        "warn_pr_created_min = 2\n"
    )
    t = detect.load_thresholds(cfg)
    assert (t.critical_total_max, t.warn_total_min, t.warn_pr_created_min) == (1, 5, 2)


def test_detect_over_db_classifies_each_member(conn):
    ingest.ingest_collection(conn, models.load_collection(FIXTURE))
    verdicts = {v.login: v for v in detect.detect(conn, T)}
    assert verdicts["foo"].status == "ok"        # total 7, PR 2
    assert verdicts["bar"].status == "warn"      # total 1
    assert verdicts["baz"].status == "critical"  # total 0


def test_detect_targets_latest_collection_by_default(conn):
    # 期間違いで 2 回取り込み、デフォルトは最新を対象にする
    c1 = models.load_collection(FIXTURE)
    ingest.ingest_collection(conn, c1)
    c2 = models.Collection(
        period_from="2026-06-19", period_to="2026-07-03",
        collected_at="2026-07-03T00:00:00Z", members=c1.members,
        signals={s: [] for s in models.SIGNALS},
    )
    ingest.ingest_collection(conn, c2)
    verdicts = detect.detect(conn, T)
    # 最新 c2 は全員無活動 → 全員 critical
    assert all(v.status == "critical" for v in verdicts)

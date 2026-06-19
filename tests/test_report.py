from activity_monitor import detect, report


def _v(login, status, total, reasons=None, pr_created=0):
    return detect.MemberVerdict(
        user_id=hash(login) % 1000, login=login, pr_created=pr_created,
        pr_reviews=0, issue_comments=0, pr_review_comments=0, total=total,
        status=status, reasons=reasons or [],
    )


VERDICTS = [
    _v("baz", "critical", 0, ["活動なし"]),
    _v("bar", "warn", 1, ["合計が閾値未満"]),
    _v("foo", "ok", 7, pr_created=2),
]


def test_render_includes_period_and_warning_section():
    md = report.render_report("2026-06-05", "2026-06-19", VERDICTS)
    assert "2026-06-05" in md and "2026-06-19" in md
    assert "baz" in md and "bar" in md
    # 理由が出力に含まれる
    assert "活動なし" in md


def test_render_marks_critical_and_warn():
    md = report.render_report("2026-06-05", "2026-06-19", VERDICTS)
    # critical/warn の件数サマリが出る
    assert "critical" in md.lower()
    assert "warn" in md.lower()


def test_render_lists_all_members_in_full_table():
    md = report.render_report("2026-06-05", "2026-06-19", VERDICTS)
    # ok の foo も全体テーブルには出る
    assert "foo" in md


def test_write_report_creates_file(tmp_path):
    path = report.write_report(tmp_path, "2026-06-05", "2026-06-19", VERDICTS)
    assert path.exists()
    assert path.read_text(encoding="utf-8").strip() != ""


def test_write_report_does_not_overwrite(tmp_path):
    p1 = report.write_report(tmp_path, "2026-06-05", "2026-06-19", VERDICTS)
    p2 = report.write_report(tmp_path, "2026-06-05", "2026-06-19", VERDICTS)
    assert p1 != p2
    assert p1.exists() and p2.exists()

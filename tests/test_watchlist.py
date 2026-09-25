from datetime import date, datetime

import pytest

from ctwatch.schedule import KST
from ctwatch.watchlist import Target, load


def write(tmp_path, text):
    p = tmp_path / "w.yaml"
    p.write_text(text)
    return p


def test_load_minimal(tmp_path):
    p = write(tmp_path, "targets:\n  - shop: mingles\n    dates: [2026-12-24, 2026-12-25]\n    party: 2\n")
    assert load(p) == [Target("mingles", (date(2026, 12, 24), date(2026, 12, 25)), 2)]


def test_open_at_override_is_kst(tmp_path):
    p = write(tmp_path, "targets:\n  - shop: x\n    dates: [2026-12-24]\n    party: 4\n    open_at: 2026-10-01 14:00\n")
    assert load(p)[0].open_at == datetime(2026, 10, 1, 14, 0, tzinfo=KST)


@pytest.mark.parametrize("body", [
    "  - shop: x\n    dates: []\n    party: 2\n",
    "  - shop: x\n    dates: [2026-12-24]\n    party: 0\n",
    "  - dates: [2026-12-24]\n    party: 2\n",
])
def test_invalid_target_rejected(tmp_path, body):
    with pytest.raises(ValueError):
        load(write(tmp_path, "targets:\n" + body))


@pytest.mark.parametrize("text", ["2026-10-01T05:00:00+00:00", "'2026-10-01T05:00:00+00:00'", "2026-10-01 14:00:00+09:00"])
def test_open_at_with_explicit_timezone_is_converted_not_overwritten(tmp_path, text):
    p = write(tmp_path, f"targets:\n  - shop: x\n    dates: [2026-12-24]\n    party: 2\n    open_at: {text}\n")
    assert load(p)[0].open_at == datetime(2026, 10, 1, 14, 0, tzinfo=KST)


def test_times_and_table_for_auto_mode(tmp_path):
    p = write(tmp_path, "targets:\n  - shop: x\n    dates: [2026-12-24]\n    party: 2\n    times: ['18:00', '18:30']\n    table: 홀\n")
    t = load(p)[0]
    assert t.times == ("18:00", "18:30") and t.table == "홀"


def test_times_must_be_hh_mm(tmp_path):
    with pytest.raises(ValueError):
        load(write(tmp_path, "targets:\n  - shop: x\n    dates: [2026-12-24]\n    party: 2\n    times: [18]\n"))

from ctwatch.book import time_label


def test_time_label_matches_catchtable_buttons():
    assert time_label("11:30") == "오전 11:30"
    assert time_label("12:00") == "오후 12:00"
    assert time_label("18:30") == "오후 6:30"
    assert time_label("00:00") == "오전 0:00"

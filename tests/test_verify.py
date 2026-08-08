from cutup.verify import MATCH, MISMATCH, UNREAD, compare


def test_compare_match():
    assert compare("3", "7", "3", "7") == MATCH
    assert compare("1", "10", 1, 10) == MATCH        # ints vs strings compare equal


def test_compare_mismatch():
    assert compare("1", "10", "2", "8") == MISMATCH
    assert compare("3", "7", "3", "8") == MISMATCH    # distance differs
    assert compare("1", "10", "2", "10") == MISMATCH  # down differs


def test_compare_unread_when_video_blank():
    assert compare(None, None, "1", "10") == UNREAD
    assert compare("1", None, "1", "10") == UNREAD
    assert compare("", "10", "1", "10") == UNREAD


def test_compare_unread_when_no_pbp():
    assert compare("1", "10", None, None) == UNREAD

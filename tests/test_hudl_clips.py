from pathlib import Path

import pytest

from cutup.errors import CutupError
from cutup.ingest.hudl_clips import extract_number, list_clip_files, match_clips


def _rows(*numbers):
    return [{"play_no": n, "t_start": None, "t_end": None, "tags": {"i": str(n)}}
            for n in numbers]


def test_extract_number_default_last_run():
    assert extract_number("7.mp4") == 7
    assert extract_number("Game1_Play07.mov") == 7
    assert extract_number("clip-012.mp4") == 12
    assert extract_number("nonumber.mp4") is None


def test_extract_number_custom_pattern():
    assert extract_number("P07_G1.mp4", pattern=r"P(\d+)") == 7


def test_list_clip_files_natural_sort_and_filter(tmp_path):
    for n in ("clip2.mp4", "clip10.mp4", "clip1.mp4", "notes.txt"):
        (tmp_path / n).write_bytes(b"x")
    files = list_clip_files(tmp_path)
    assert [f.name for f in files] == ["clip1.mp4", "clip2.mp4", "clip10.mp4"]


def test_list_clip_files_rejects_non_folder(tmp_path):
    f = tmp_path / "x.mp4"
    f.write_bytes(b"x")
    with pytest.raises(CutupError):
        list_clip_files(f)


def test_match_index_equal():
    files = [Path("a.mp4"), Path("b.mp4"), Path("c.mp4")]
    rec = match_clips(files, _rows(1, 2, 3), strategy="index")
    assert len(rec.matched) == 3
    assert not rec.unmatched_files and not rec.unmatched_rows


def test_match_index_more_rows_than_files():
    # download skipped a play (penalty): 2 files, 3 rows -> one row unmatched
    files = [Path("a.mp4"), Path("b.mp4")]
    rec = match_clips(files, _rows(1, 2, 3), strategy="index")
    assert len(rec.matched) == 2
    assert not rec.unmatched_files
    assert [r["play_no"] for r in rec.unmatched_rows] == [3]


def test_match_index_more_files_than_rows():
    files = [Path("a.mp4"), Path("b.mp4"), Path("c.mp4")]
    rec = match_clips(files, _rows(1, 2), strategy="index")
    assert [f.name for f in rec.unmatched_files] == ["c.mp4"]


def test_match_by_number():
    files = [Path("1.mp4"), Path("2.mp4"), Path("4.mp4")]  # no clip for row 3
    rec = match_clips(files, _rows(1, 2, 3), strategy="number")
    matched_nums = sorted(r["play_no"] for _, r in rec.matched)
    assert matched_nums == [1, 2]
    assert [f.name for f in rec.unmatched_files] == ["4.mp4"]   # no row 4
    assert [r["play_no"] for r in rec.unmatched_rows] == [3]


def test_match_by_number_unnumbered_file():
    files = [Path("intro.mp4"), Path("1.mp4")]
    rec = match_clips(files, _rows(1), strategy="number")
    assert [f.name for f in rec.unmatched_files] == ["intro.mp4"]
    assert len(rec.matched) == 1


def test_unknown_strategy():
    with pytest.raises(CutupError):
        match_clips([], [], strategy="bogus")

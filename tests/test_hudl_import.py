from pathlib import Path

import pytest

from cutup.ingest.hudl_csv import prepare_import, read_table
from cutup.ingest.profiles import suggest_profile

FIXTURE = Path(__file__).parent / "fixtures" / "hudl" / "PlaylistData_2026-07-22.xlsx"


def test_read_csv_and_prepare(tmp_path):
    csv = tmp_path / "b.csv"
    csv.write_text(
        "PLAY #,START,END,DN,DIST,OFF FORM\n"
        "1,0:05,0:07,3,6,TRIPS\n"
        "2,0:12,0:14,1,10,ACE\n",
        encoding="utf-8",
    )
    headers, data = read_table(csv)
    assert headers[0] == "PLAY #"
    prof = suggest_profile(headers)
    result = prepare_import(headers, data, prof)
    assert result.count == 2
    assert result.has_times is True
    assert result.numbered_by_order is False
    first = result.plays[0]
    assert first["play_no"] == 1
    assert first["t_start"] == 5.0 and first["t_end"] == 7.0
    assert first["tags"] == {"down": "3", "distance": "6", "off_form": "TRIPS"}


def test_chart_without_playno_numbers_by_order(tmp_path):
    csv = tmp_path / "c.csv"
    csv.write_text("ODK,DN,DIST\nO,1,10\nO,2,7\nD,1,10\n", encoding="utf-8")
    headers, data = read_table(csv)
    result = prepare_import(headers, data, suggest_profile(headers))
    assert result.numbered_by_order is True
    assert [p["play_no"] for p in result.plays] == [1, 2, 3]
    assert result.has_times is False
    assert all(p["t_start"] is None for p in result.plays)
    # a helpful warning is emitted about ordering and about missing times
    assert any("row order" in w for w in result.warnings)
    assert any("without cut times" in w for w in result.warnings)


def test_empty_cells_do_not_become_tags(tmp_path):
    csv = tmp_path / "d.csv"
    csv.write_text("ODK,DN,DIST\nS,,\nO,1,10\n", encoding="utf-8")
    headers, data = read_table(csv)
    result = prepare_import(headers, data, suggest_profile(headers))
    # special-teams row: only ODK present
    assert result.plays[0]["tags"] == {"odk": "S"}
    assert result.plays[1]["tags"] == {"odk": "O", "down": "1", "distance": "10"}


@pytest.mark.skipif(not FIXTURE.exists(), reason="real Hudl fixture not present")
def test_real_fixture_imports():
    headers, data = read_table(FIXTURE)
    assert headers == ["ODK", "DN", "DIST", "YARD LN", "PLAY TYPE", "RESULT",
                       "GN/LS", "OFF FORM", "OFF PLAY", "DEF FRONT", "COVERAGE"]
    result = prepare_import(headers, data, suggest_profile(headers))
    assert result.count == 142
    assert result.numbered_by_order is True   # no PLAY # column in this export
    assert result.has_times is False
    # ODK is fully populated -> every play carries an odk tag
    assert all("odk" in p["tags"] for p in result.plays)
    odk = [p["tags"]["odk"] for p in result.plays]
    assert odk.count("O") == 54 and odk.count("D") == 51
    # DEF FRONT / COVERAGE are empty in this file -> never appear as tags
    assert not any("def_front" in p["tags"] or "coverage" in p["tags"]
                   for p in result.plays)

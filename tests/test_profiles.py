from cutup.ingest.profiles import (
    ImportProfile,
    normalize_header,
    slug,
    suggest_profile,
    suggest_target,
)


def test_normalize_and_slug():
    assert normalize_header("  Play #  ") == "PLAY #"
    assert normalize_header("Dist.") == "DIST"
    assert slug("GN/LS") == "gn_ls"
    assert slug("YARD LN") == "yard_ln"


def test_suggest_target_reserved_and_tags():
    assert suggest_target("PLAY #").target == "play_no"
    assert suggest_target("Start Time").target == "t_start"
    dn = suggest_target("DN")
    assert dn.target == "tag" and dn.key == "down"
    dist = suggest_target("DIST")
    assert dist.target == "tag" and dist.key == "distance"


def test_suggest_target_falls_back_to_slug_tag():
    m = suggest_target("Some Custom Column")
    assert m.target == "tag" and m.key == "some_custom_column"


def test_real_hudl_headers_map_cleanly():
    # The exact headers from the real fixture export.
    headers = ["ODK", "DN", "DIST", "YARD LN", "PLAY TYPE", "RESULT", "GN/LS",
               "OFF FORM", "OFF PLAY", "DEF FRONT", "COVERAGE"]
    prof = suggest_profile(headers)
    keys = {h: (prof.resolve(h).key or prof.resolve(h).target) for h in headers}
    assert keys == {
        "ODK": "odk", "DN": "down", "DIST": "distance", "YARD LN": "yard_line",
        "PLAY TYPE": "play_type", "RESULT": "result", "GN/LS": "gain",
        "OFF FORM": "off_form", "OFF PLAY": "off_play", "DEF FRONT": "def_front",
        "COVERAGE": "coverage",
    }


def test_unmapped_defaults_to_tag_and_ignore_option():
    prof = ImportProfile(name="p", columns={}, unmapped="tag")
    assert prof.resolve("Weird Col").target == "tag"
    prof.unmapped = "ignore"
    assert prof.resolve("Weird Col").target == "ignore"


def test_profile_roundtrip(tmp_path):
    prof = suggest_profile(["PLAY #", "DN", "DIST"], name="hudl-default")
    prof.verified = True
    prof.save(tmp_path)
    loaded = ImportProfile.load(tmp_path, "hudl-default")
    assert loaded.verified is True
    assert loaded.resolve("DN").key == "down"
    assert "hudl-default" in ImportProfile.list_names(tmp_path)

from pathlib import Path

from cutup import sizes as S
from cutup import presets as P
from cutup.render import build_argv


# -- output sizes -----------------------------------------------------------

def test_source_size_means_no_filter():
    assert S.get_size("source") is None
    assert S.get_size(None) is None
    assert S.video_filter(None) is None


def test_pad_filter_letterboxes_to_target():
    vf = S.video_filter(S.get_size("vertical_1080"))
    assert "scale=1080:1920:force_original_aspect_ratio=decrease" in vf
    assert "pad=1080:1920" in vf
    assert vf.endswith("format=yuv420p")


def test_crop_filter_fills_frame():
    crop = S.OutputSize("x", "X", "P", 1080, 1080, "crop")
    vf = S.video_filter(crop)
    assert "force_original_aspect_ratio=increase" in vf and "crop=1080:1080" in vf


def test_size_catalog_has_the_social_platforms():
    blob = " ".join(s["platform"] for s in S.list_sizes())
    for p in ("YouTube", "Hudl", "X", "Instagram", "TikTok", "Snapchat"):
        assert p in blob


# -- clip renderer honors a size -------------------------------------------

def test_build_argv_size_forces_reencode():
    vf = S.video_filter(S.get_size("square_1080"))
    argv = build_argv("ffmpeg", Path("g.mp4"), 10.0, 5.0, Path("o.mp4"),
                      accurate=False, encoder="libx264", size_vf=vf)
    assert "-vf" in argv and vf in argv
    assert "-c:v" in argv and "libx264" in argv
    assert "-c" not in argv[:argv.index("libx264")] or "copy" not in argv  # not a stream copy


def test_build_argv_size_and_watermark_compose():
    from cutup.render import WatermarkSpec
    wm = WatermarkSpec(logo=Path("logo.png"), position="bottom-right", scale=0.18)
    vf = S.video_filter(S.get_size("vertical_1080"))
    argv = build_argv("ffmpeg", Path("g.mp4"), 0.0, 3.0, Path("o.mp4"),
                      accurate=False, encoder="libx264", watermark=wm, size_vf=vf)
    graph = argv[argv.index("-filter_complex") + 1]
    assert "[base]" in graph and "overlay=" in graph and graph.endswith("[v]")
    assert "-map" in argv and "[v]" in argv


# -- starter presets --------------------------------------------------------

def test_seed_starter_presets_is_idempotent(tmp_path):
    from cutup.library import Library
    lib = Library.init(tmp_path / "lib")
    names = {p["name"] for p in P.list_presets(lib.conn)}
    # init already seeded them
    assert "3rd & Long" in names and "Explosive (15+ yds)" in names
    assert len(names) >= len(P.STARTER_PRESETS)
    # re-seeding adds nothing
    assert P.seed_starter_presets(lib.conn) == 0
    lib.close()


def test_starter_predicates_use_real_tag_values():
    by_name = dict(P.STARTER_PRESETS)
    assert by_name["Touchdowns"] == ["result=touchdown"]
    assert by_name["Pass Plays"] == ["play_type=pass"]
    assert "gain>=15" in by_name["Explosive (15+ yds)"]

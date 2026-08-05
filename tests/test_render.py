from pathlib import Path

from cutup.render import build_argv, execute, manifest_rows, plan_clips, WatermarkSpec


def _row(pid, no, ts, te, path="game.mp4", label="Game 1", source_type="broadcast"):
    return {"id": pid, "play_no": no, "t_start": ts, "t_end": te,
            "film_path": path, "film_label": label, "film_source_type": source_type}


def _resolve(root, stored):
    return Path(root) / stored


def test_fast_argv_uses_stream_copy():
    argv = build_argv("ffmpeg", Path("g.mp4"), 10.0, 5.0, Path("out.mp4"),
                      accurate=False, encoder="libx264")
    assert "-c" in argv and "copy" in argv
    # fast seek is before -i
    assert argv.index("-ss") < argv.index("-i")


def test_accurate_argv_reencodes_after_input():
    argv = build_argv("ffmpeg", Path("g.mp4"), 10.0, 5.0, Path("out.mp4"),
                      accurate=True, encoder="h264_nvenc")
    assert "h264_nvenc" in argv
    # accurate seek is after -i
    assert argv.index("-i") < argv.index("-ss")


def test_plan_applies_padding_and_clamps():
    rows = [_row(1, 1, 10.0, 15.0), _row(2, 2, 1.0, 4.0)]
    clips = plan_clips(
        rows, {}, ffmpeg="ffmpeg", library_root=Path("/lib"), out_dir=Path("/out"),
        pre_roll=3.0, post_roll=2.0, accurate=False, encoder="libx264",
        output_template="{play_no:03d}.mp4", resolve_film=_resolve,
    )
    assert clips[0].t_in == 7.0 and clips[0].t_out == 17.0
    # second play would go negative; pre-roll is clamped to 0
    assert clips[1].t_in == 0.0


def test_plan_disambiguates_duplicate_names():
    rows = [_row(1, 1, 10.0, 15.0), _row(2, 1, 20.0, 25.0)]  # same play_no -> same name
    clips = plan_clips(
        rows, {}, ffmpeg="ffmpeg", library_root=Path("/lib"), out_dir=Path("/out"),
        pre_roll=0, post_roll=0, accurate=False, encoder="libx264",
        output_template="{play_no:03d}.mp4", resolve_film=_resolve,
    )
    names = {c.out_path.name for c in clips}
    assert names == {"001.mp4", "001_2.mp4"}


def test_template_uses_tags():
    rows = [_row(1, 7, 10.0, 15.0)]
    clips = plan_clips(
        rows, {1: {"formation": "trips"}}, ffmpeg="ffmpeg", library_root=Path("/lib"),
        out_dir=Path("/out"), pre_roll=0, post_roll=0, accurate=False, encoder="libx264",
        output_template="{play_no:03d}_{formation}.mp4", resolve_film=_resolve,
    )
    assert clips[0].out_path.name == "007_trips.mp4"


def test_precut_clip_plans_as_whole_file_copy(tmp_path):
    src = tmp_path / "0007.mov"
    src.write_bytes(b"video-bytes")
    row = _row(1, 7, 0.0, 3.0, path="0007.mov", label="G1 #7", source_type="hudl_clip")
    clips = plan_clips(
        [row], {}, ffmpeg="ffmpeg", library_root=tmp_path, out_dir=tmp_path / "out",
        pre_roll=3.0, post_roll=2.0, accurate=False, encoder="libx264",
        output_template="{play_no:03d}.mp4", resolve_film=lambda r, s: tmp_path / s,
    )
    c = clips[0]
    assert c.mode == "file"
    assert c.argv == []
    assert c.out_path.name == "007.mov"   # source extension preserved, no padding
    assert c.t_in == 0.0

    results = execute(clips)
    assert results[0].ok
    assert (tmp_path / "out" / "007.mov").read_bytes() == b"video-bytes"


def test_watermark_argv_overlays_and_reencodes():
    wm = WatermarkSpec(logo=Path("logo.png"), position="top-left", scale=0.2)
    argv = build_argv("ffmpeg", Path("g.mp4"), 10.0, 5.0, Path("out.mp4"),
                      accurate=False, encoder="libx264", watermark=wm)
    joined = " ".join(argv)
    assert "-filter_complex" in argv
    assert "overlay=12:12" in joined                 # top-left position
    assert "scale2ref=w=main_w*0.2:h=-1" in joined   # 20% of video width, aspect kept
    assert "copy" not in argv                        # not a stream copy
    assert "libx264" in argv


def test_watermark_forces_precut_reencode():
    # a hudl_clip would normally be a file copy; with a watermark it re-encodes
    row = _row(1, 7, 0.0, 3.0, path="c.mp4", source_type="hudl_clip")
    wm = WatermarkSpec(logo=Path("logo.png"))
    clips = plan_clips(
        [row], {}, ffmpeg="ffmpeg", library_root=Path("/lib"), out_dir=Path("/out"),
        pre_roll=3.0, post_roll=2.0, accurate=False, encoder="libx264",
        output_template="{play_no:03d}.mp4", resolve_film=_resolve, watermark=wm,
    )
    assert clips[0].mode == "watermark"
    assert clips[0].argv != []                  # not a copy
    assert clips[0].t_in == 0.0                 # whole clip, no padding


def test_manifest_rows_shape():
    rows = [_row(1, 1, 10.0, 15.0)]
    clips = plan_clips(
        rows, {}, ffmpeg="ffmpeg", library_root=Path("/lib"), out_dir=Path("/out"),
        pre_roll=3.0, post_roll=2.0, accurate=False, encoder="libx264",
        output_template="{play_no:03d}.mp4", resolve_film=_resolve,
    )
    m = manifest_rows(clips)[0]
    assert m["mode"] == "copy"
    assert m["output"] == "001.mp4"
    assert isinstance(m["argv"], list)

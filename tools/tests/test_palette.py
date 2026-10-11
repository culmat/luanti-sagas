import numpy as np

from sagas import palette


def test_file_matches_generator():
    assert list(palette.load()) == palette.generate()


def test_unique_and_layout():
    cols = palette.load()
    assert len(cols) == 256 and len(set(cols)) == 256
    assert cols[0] == "#000000" and cols[23] == "#ffffff"
    assert cols[204:] == palette.ANCHORS


def test_quantize_exact_entries():
    rgb = palette.rgb_array()
    assert np.array_equal(palette.quantize(rgb), np.arange(256))


def test_quantize_is_nearest():
    q = palette.quantize(np.array([[250, 250, 250], [5, 5, 5]], np.uint8))
    assert list(q) == [23, 0]


def test_png_roundtrip(tmp_path):
    p = tmp_path / "pal.png"
    palette.write_png(p)
    assert palette.png_matches(p)

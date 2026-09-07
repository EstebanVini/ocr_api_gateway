from io import BytesIO

import pytest
from PIL import Image

from app.core.exceptions import CompressionFailedError
from app.services.compressor.base import CompressionStrategy
from app.services.compressor.image import _flatten_to_white, compress_image
from tests.conftest import (
    make_exif_rotated_jpeg_bytes,
    make_high_entropy_image_bytes,
    make_image_bytes,
    make_low_entropy_png_bytes,
    make_transparent_image,
)

_DEFAULT_KWARGS = {
    "min_quality": 60,
    "min_longest_side_px": 1500,
    "min_scale_factor": 0.5,
}


def test_passthrough_when_already_under_threshold() -> None:
    data = make_image_bytes("PNG", size=(10, 10))
    result = compress_image(data, max_bytes=1_048_576, **_DEFAULT_KWARGS)
    assert result.was_compressed is False
    assert result.strategy == CompressionStrategy.NONE
    assert result.data == data


def test_png_optimize_succeeds_losslessly() -> None:
    data = make_low_entropy_png_bytes(size=(1200, 1200))
    assert len(data) > 1_000_000  # sanity: the raw fixture is genuinely oversized

    result = compress_image(data, max_bytes=50_000, **_DEFAULT_KWARGS)

    assert result.strategy == CompressionStrategy.PNG_OPTIMIZE
    assert result.was_compressed is True
    assert len(result.data) <= 50_000
    assert Image.open(BytesIO(result.data)).format == "PNG"


def test_jpeg_quality_search_without_scaling() -> None:
    data = make_high_entropy_image_bytes(size=(1600, 1600))
    result = compress_image(data, max_bytes=1_100_000, **_DEFAULT_KWARGS)

    assert result.strategy == CompressionStrategy.JPEG_QUALITY_SEARCH
    assert result.scale_factor == 1.0
    assert 60 <= result.quality <= 95
    assert len(result.data) <= 1_100_000
    out = Image.open(BytesIO(result.data))
    assert out.format == "JPEG"
    assert out.mode == "RGB"  # never grayscale by default


def test_scale_reduction_kicks_in_when_quality_search_alone_is_not_enough() -> None:
    data = make_high_entropy_image_bytes(size=(2200, 2200))
    result = compress_image(data, max_bytes=1_100_000, **_DEFAULT_KWARGS)

    assert result.strategy == CompressionStrategy.JPEG_QUALITY_SEARCH_SCALED
    assert result.scale_factor == 0.8
    assert 60 <= result.quality < 70
    assert len(result.data) <= 1_100_000

    out = Image.open(BytesIO(result.data))
    longest_side = max(out.size)
    floor_px = max(1500, 0.5 * 2200)
    assert longest_side >= floor_px


def test_compression_exhaustion_raises_with_full_detail() -> None:
    data = make_high_entropy_image_bytes(size=(2200, 2200))

    with pytest.raises(CompressionFailedError) as exc_info:
        compress_image(data, max_bytes=50_000, **_DEFAULT_KWARGS)

    details = exc_info.value.details
    assert details["original_size_bytes"] == len(data)
    assert details["final_size_bytes"] > 0
    assert details["strategy"] == CompressionStrategy.JPEG_QUALITY_SEARCH_SCALED.value
    assert details["last_parameter_tried"] == {"quality": 60, "scale_factor": 0.7}


def test_flatten_to_white_avoids_black_artifacts() -> None:
    transparent = make_transparent_image()
    flattened = _flatten_to_white(transparent)

    assert flattened.mode == "RGB"
    corner_pixel = flattened.getpixel((0, 0))  # was fully transparent originally
    assert all(channel >= 250 for channel in corner_pixel)


def test_exif_orientation_is_applied_and_not_re_embedded() -> None:
    data = make_exif_rotated_jpeg_bytes(size=(40, 20))

    result = compress_image(data, max_bytes=600, **_DEFAULT_KWARGS)

    out = Image.open(BytesIO(result.data))
    assert out.size == (20, 40)  # dimensions swapped by the 90-degree EXIF rotation
    assert "exif" not in out.info

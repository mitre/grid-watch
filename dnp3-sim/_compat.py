"""Runtime fix for dnp3py 0.1.0 — binary qualifier encoding bug.

dnp3py 0.1.0 encodes binary input/output blocks with count+prefix qualifiers
(0x17 / 0x28).  The dnp3-actions Caldera payload only accepts start-stop range
qualifiers (0x00 / 0x01), so integrity polls return empty results without this
fix.

Importing this module replaces the two affected methods on ``Outstation`` before
any server code runs.  Remove this file once the fix is merged upstream.

Upstream issue: https://github.com/craigpnnl/dnp3py/issues/6
"""

from __future__ import annotations

from typing import Any

from dnp3.application.fragment import ObjectBlock
from dnp3.application.qualifiers import ObjectHeader, StartStopRange
from dnp3.core.flags import BinaryQuality
from dnp3.outstation.outstation import (
    GV_BINARY_INPUT_FLAGS,
    GV_BINARY_OUTPUT_FLAGS,
    Outstation,
    _serialize_binary_input,
    _serialize_binary_output,
)

_MAX_INDEX_SPAN = 2000


def _build_binary_input_blocks(
    self: Outstation, points: list[Any]
) -> list[ObjectBlock]:
    if not points:
        return []
    data = bytearray()
    points_sorted = sorted(points, key=lambda p: p.index)
    min_index = points_sorted[0].index
    max_index = points_sorted[-1].index
    point_map = {p.index: p for p in points_sorted}
    if max_index - min_index > _MAX_INDEX_SPAN:
        raise ValueError(
            f"binary input index span {max_index - min_index} exceeds {_MAX_INDEX_SPAN}; "
            "use contiguous point indices"
        )
    if max_index <= 255:
        range_data = StartStopRange(min_index, max_index).to_bytes_1()
        qualifier = 0x00
    else:
        range_data = StartStopRange(min_index, max_index).to_bytes_2()
        qualifier = 0x01
    for idx in range(min_index, max_index + 1):
        if idx in point_map:
            data.extend(
                _serialize_binary_input(point_map[idx].value, point_map[idx].quality)
            )
        else:
            data.extend(_serialize_binary_input(False, BinaryQuality(0)))
    header = ObjectHeader(
        group=GV_BINARY_INPUT_FLAGS[0],
        variation=GV_BINARY_INPUT_FLAGS[1],
        qualifier=qualifier,
    )
    return [ObjectBlock(header=header, data=range_data + bytes(data))]


def _build_binary_output_blocks(
    self: Outstation, points: list[Any]
) -> list[ObjectBlock]:
    if not points:
        return []
    data = bytearray()
    points_sorted = sorted(points, key=lambda p: p.index)
    min_index = points_sorted[0].index
    max_index = points_sorted[-1].index
    point_map = {p.index: p for p in points_sorted}
    if max_index - min_index > _MAX_INDEX_SPAN:
        raise ValueError(
            f"binary output index span {max_index - min_index} exceeds {_MAX_INDEX_SPAN}; "
            "use contiguous point indices"
        )
    if max_index <= 255:
        range_data = StartStopRange(min_index, max_index).to_bytes_1()
        qualifier = 0x00
    else:
        range_data = StartStopRange(min_index, max_index).to_bytes_2()
        qualifier = 0x01
    for idx in range(min_index, max_index + 1):
        if idx in point_map:
            data.extend(
                _serialize_binary_output(point_map[idx].value, point_map[idx].quality)
            )
        else:
            data.extend(_serialize_binary_output(False, BinaryQuality(0)))
    header = ObjectHeader(
        group=GV_BINARY_OUTPUT_FLAGS[0],
        variation=GV_BINARY_OUTPUT_FLAGS[1],
        qualifier=qualifier,
    )
    return [ObjectBlock(header=header, data=range_data + bytes(data))]


Outstation._build_binary_input_blocks = _build_binary_input_blocks  # type: ignore[method-assign]
Outstation._build_binary_output_blocks = _build_binary_output_blocks  # type: ignore[method-assign]

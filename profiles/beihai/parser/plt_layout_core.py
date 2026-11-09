"""Standalone PLT layout primitives extracted from the validated Chengda layout.

Original module: inject_sha_weld_callouts.py; SHA file readers and project data are excluded.
The retained definitions preserve the source implementation.
"""
from __future__ import annotations
import math
import random
from collections import defaultdict
from dataclasses import dataclass

SHEET_UNIT = 16800


TEXT_NUMBER_TEMPLATE = "12345"


SOURCE_MARKER_CLEARANCE = 20.0


WELD_CALLOUT_FONT_HEIGHT = 88.0


WELD_CALLOUT_MARKER_RADIUS = 120.0


AVOIDABLE_SOURCE_CROSSING_PENALTY = 20000.0


PREFERRED_ROOT_CLEARANCE = 150.0


SOURCE_LINE_CROSSING_PENALTY = 20000.0


SOURCE_TEXT_CROSSING_PENALTY = 50000.0


SOURCE_CORRIDOR_CLEARANCE = 42.0


SOURCE_CORRIDOR_PENALTY = 18000.0


LOCAL_GEOMETRY_RADIUS = 1100.0


DIRECTIONAL_SECTOR_HALF_ANGLE = math.radians(42.5)


DIRECTIONAL_SECTOR_PENALTY = 28000.0


PEER_ROOT_RADIUS = 1700.0


PEER_ROOT_DIRECTION_PENALTY = 140000.0


CONGESTED_CARDINAL_RATIO = 0.20


CONGESTED_CARDINAL_PENALTY = 90000.0


@dataclass
class PointTarget:
    graphic_ref: int
    uci: str
    center_x: float
    center_y: float
    page: int
    # Logical annotation identity is distinct from the shared physical root.
    # Upstream mapping authorizes OLET/PAD sharing; preserve every accepted row.
    weld_number: str = ""
    weld_type: str = ""


@dataclass
class CalloutPlacement:
    center_x: float
    center_y: float
    leader_x: float
    leader_y: float
    number: str
    score: float = 0.0
    marker_radius: float = 0.0


@dataclass(frozen=True)
class LayoutRegion:
    """Physical frame and the smaller area available to ISO annotations."""

    outer: tuple[float, float, float, float]
    drawing: tuple[float, float, float, float]
    source: str


@dataclass(frozen=True)
class PlacementCandidate:
    placement: CalloutPlacement
    marker_box: tuple[float, float, float, float]
    remote_source_clear: bool = True
    source_line_crossings: int = 0
    source_text_crossings: int = 0


def point_segment_distance(px: float, py: float, x1: float, y1: float, x2: float, y2: float) -> float:
    dx = x2 - x1
    dy = y2 - y1
    if dx == 0 and dy == 0:
        return math.hypot(px - x1, py - y1)
    t = ((px - x1) * dx + (py - y1) * dy) / (dx * dx + dy * dy)
    t = max(0.0, min(1.0, t))
    qx = x1 + t * dx
    qy = y1 + t * dy
    return math.hypot(px - qx, py - qy)


def segment_distance(
    first: tuple[float, float, float, float],
    second: tuple[float, float, float, float],
) -> float:
    if segments_intersect(first, second):
        return 0.0
    ax1, ay1, ax2, ay2 = first
    bx1, by1, bx2, by2 = second
    return min(
        point_segment_distance(ax1, ay1, bx1, by1, bx2, by2),
        point_segment_distance(ax2, ay2, bx1, by1, bx2, by2),
        point_segment_distance(bx1, by1, ax1, ay1, ax2, ay2),
        point_segment_distance(bx2, by2, ax1, ay1, ax2, ay2),
    )


def boxes_overlap(
    first: tuple[float, float, float, float],
    second: tuple[float, float, float, float],
    tolerance: float = 1e-6,
) -> bool:
    left, bottom, right, top = first
    other_left, other_bottom, other_right, other_top = second
    return not (
        right <= other_left + tolerance
        or left >= other_right - tolerance
        or top <= other_bottom + tolerance
        or bottom >= other_top - tolerance
    )


def point_in_box(
    x: float,
    y: float,
    box: tuple[float, float, float, float],
    tolerance: float = 1e-6,
) -> bool:
    left, bottom, right, top = box
    return left - tolerance <= x <= right + tolerance and bottom - tolerance <= y <= top + tolerance


def orientation(
    ax: float,
    ay: float,
    bx: float,
    by: float,
    cx: float,
    cy: float,
) -> float:
    return (bx - ax) * (cy - ay) - (by - ay) * (cx - ax)


def segments_intersect(
    first: tuple[float, float, float, float],
    second: tuple[float, float, float, float],
    tolerance: float = 1e-6,
) -> bool:
    """Return True for proper, touching, or collinear segment intersections."""

    ax, ay, bx, by = first
    cx, cy, dx, dy = second
    if (
        max(ax, bx) < min(cx, dx) - tolerance
        or max(cx, dx) < min(ax, bx) - tolerance
        or max(ay, by) < min(cy, dy) - tolerance
        or max(cy, dy) < min(ay, by) - tolerance
    ):
        return False
    values = (
        orientation(ax, ay, bx, by, cx, cy),
        orientation(ax, ay, bx, by, dx, dy),
        orientation(cx, cy, dx, dy, ax, ay),
        orientation(cx, cy, dx, dy, bx, by),
    )
    first_a, first_b, second_a, second_b = values
    if first_a * first_b < -tolerance and second_a * second_b < -tolerance:
        return True
    def on_segment(px: float, py: float, qx: float, qy: float, rx: float, ry: float) -> bool:
        return (
            min(px, rx) - tolerance <= qx <= max(px, rx) + tolerance
            and min(py, ry) - tolerance <= qy <= max(py, ry) + tolerance
        )

    return (
        abs(first_a) <= tolerance and on_segment(ax, ay, cx, cy, bx, by)
        or abs(first_b) <= tolerance and on_segment(ax, ay, dx, dy, bx, by)
        or abs(second_a) <= tolerance and on_segment(cx, cy, ax, ay, dx, dy)
        or abs(second_b) <= tolerance and on_segment(cx, cy, bx, by, dx, dy)
    )


def segment_intersects_box(
    segment: tuple[float, float, float, float],
    box: tuple[float, float, float, float],
) -> bool:
    x1, y1, x2, y2 = segment
    if point_in_box(x1, y1, box) or point_in_box(x2, y2, box):
        return True
    left, bottom, right, top = box
    return any(
        segments_intersect(segment, edge)
        for edge in (
            (left, bottom, right, bottom),
            (right, bottom, right, top),
            (right, top, left, top),
            (left, top, left, bottom),
        )
    )


def truncate_segment_start(
    segment: tuple[float, float, float, float], distance: float
) -> tuple[float, float, float, float] | None:
    x1, y1, x2, y2 = segment
    length = math.hypot(x2 - x1, y2 - y1)
    if length <= distance + 1e-6:
        return None
    scale = distance / length
    return (
        x1 + (x2 - x1) * scale,
        y1 + (y2 - y1) * scale,
        x2,
        y2,
    )


def marker_edge(
    source_x: float,
    source_y: float,
    center_x: float,
    center_y: float,
    marker_shape: str,
    marker_radius: float,
    marker_width: float | None = None,
    marker_height: float | None = None,
) -> tuple[float, float]:
    delta_x = source_x - center_x
    delta_y = source_y - center_y
    if abs(delta_x) + abs(delta_y) <= 1e-6:
        raise ValueError("Callout marker centre coincides with its weld point")
    if marker_shape == "rectangle" and marker_width and marker_height:
        scales = []
        if abs(delta_x) > 1e-6:
            scales.append((marker_width / 2.0) / abs(delta_x))
        if abs(delta_y) > 1e-6:
            scales.append((marker_height / 2.0) / abs(delta_y))
        scale = min(scales)
        return center_x + delta_x * scale, center_y + delta_y * scale
    denominator = math.hypot(delta_x, delta_y) if marker_shape == "circle" else abs(delta_x) + abs(delta_y)
    scale = marker_radius / denominator
    return center_x + delta_x * scale, center_y + delta_y * scale


def leader_clear_of_source(
    leader: tuple[float, float, float, float],
    source_segments: list[tuple[float, float, float, float, int, int]],
    source_boxes: list[tuple[float, float, float, float]],
    root_clearance: float = 700.0,
) -> bool:
    visible_leader = truncate_segment_start(leader, root_clearance)
    if visible_leader is None:
        return True
    vx1, vy1, vx2, vy2 = visible_leader
    leader_bounds = (min(vx1, vx2), min(vy1, vy2), max(vx1, vx2), max(vy1, vy2))
    for x1, y1, x2, y2, _, _ in source_segments:
        source = (x1 * SHEET_UNIT, y1 * SHEET_UNIT, x2 * SHEET_UNIT, y2 * SHEET_UNIT)
        sx1, sy1, sx2, sy2 = source
        source_bounds = (min(sx1, sx2), min(sy1, sy2), max(sx1, sx2), max(sy1, sy2))
        if not boxes_overlap(leader_bounds, source_bounds, tolerance=-1.0):
            continue
        if segments_intersect(visible_leader, source):
            return False
    return not any(
        boxes_overlap(leader_bounds, box, tolerance=-1.0) and segment_intersects_box(visible_leader, box)
        for box in source_boxes
    )


def leader_source_crossing_counts(
    leader: tuple[float, float, float, float],
    source_segments: list[tuple[float, float, float, float, int, int]],
    source_boxes: list[tuple[float, float, float, float]],
    root_clearance: float = 20.0,
) -> tuple[int, int]:
    """Count visible line/text obstacles crossed beyond the weld symbol itself.

    A dense fitting can enclose its weld dot with several local strokes, so a
    binary clear/not-clear score sends a callout through a much busier remote
    lane merely to avoid one nearby stroke.  Counting crossings makes one
    unavoidable local exit cheaper than crossing several dimensions or text
    labels.  Coordinate keys prevent duplicate decoded primitives from
    overstating the same visible obstacle.
    """

    visible_leader = truncate_segment_start(leader, root_clearance)
    if visible_leader is None:
        return 0, 0
    vx1, vy1, vx2, vy2 = visible_leader
    leader_bounds = (min(vx1, vx2), min(vy1, vy2), max(vx1, vx2), max(vy1, vy2))
    crossed_lines: set[tuple[int, int, int, int]] = set()
    for x1, y1, x2, y2, _, _ in source_segments:
        source = (x1 * SHEET_UNIT, y1 * SHEET_UNIT, x2 * SHEET_UNIT, y2 * SHEET_UNIT)
        sx1, sy1, sx2, sy2 = source
        source_bounds = (min(sx1, sx2), min(sy1, sy2), max(sx1, sx2), max(sy1, sy2))
        if not boxes_overlap(leader_bounds, source_bounds, tolerance=-1.0):
            continue
        if segments_intersect(visible_leader, source):
            first = (round(sx1), round(sy1))
            second = (round(sx2), round(sy2))
            crossed_lines.add((*first, *second) if first <= second else (*second, *first))
    crossed_boxes = {
        tuple(round(value) for value in box)
        for box in source_boxes
        if boxes_overlap(leader_bounds, box, tolerance=-1.0)
        and segment_intersects_box(visible_leader, box)
    }
    return len(crossed_lines), len(crossed_boxes)


def leader_corridor_congestion(
    leader: tuple[float, float, float, float],
    source_segments: list[tuple[float, float, float, float, int, int]],
    root_clearance: float = 45.0,
    corridor_clearance: float = SOURCE_CORRIDOR_CLEARANCE,
) -> float:
    """Measure geometry close enough to make a leader look crossed/merged.

    Exact intersection tests miss the common bad case where a leader follows
    an elbow, pipe or dimension line at almost the same angle.  This returns
    a continuous congestion value: 1.0 for contact, tapering to zero at the
    edge of the visual clearance corridor.
    """

    visible_leader = truncate_segment_start(leader, root_clearance)
    if visible_leader is None:
        return 0.0
    unique_segments: dict[tuple[int, int, int, int], tuple[float, float, float, float]] = {}
    for x1, y1, x2, y2, _, _ in source_segments:
        source = (x1 * SHEET_UNIT, y1 * SHEET_UNIT, x2 * SHEET_UNIT, y2 * SHEET_UNIT)
        first = (round(source[0]), round(source[1]))
        second = (round(source[2]), round(source[3]))
        key = (*first, *second) if first <= second else (*second, *first)
        unique_segments.setdefault(key, source)
    congestion = 0.0
    for source in unique_segments.values():
        distance = segment_distance(visible_leader, source)
        if distance < corridor_clearance:
            congestion += (corridor_clearance - distance) / corridor_clearance
    return congestion


def directional_sector_congestion(
    point: PointTarget,
    direction: tuple[float, float],
    source_segments: list[tuple[float, float, float, float, int, int]],
) -> float:
    """Measure visible drawing mass in the proposed leader's forward sector.

    A centroid vector can cancel two occupied directions and incorrectly call
    their bisector empty. Sampling a finite angular sector instead rewards a
    genuinely open wedge and works for elbows, tees and dense dimensions.
    """

    threshold = math.cos(DIRECTIONAL_SECTOR_HALF_ANGLE)
    congestion = 0.0
    seen: set[tuple[int, int, int, int]] = set()
    for x1, y1, x2, y2, _, _ in source_segments:
        ax, ay = x1 * SHEET_UNIT, y1 * SHEET_UNIT
        bx, by = x2 * SHEET_UNIT, y2 * SHEET_UNIT
        first = (round(ax), round(ay))
        second = (round(bx), round(by))
        key = (*first, *second) if first <= second else (*second, *first)
        if key in seen:
            continue
        seen.add(key)
        length = math.hypot(bx - ax, by - ay)
        length_weight = min(1.0, length / 300.0)
        for fraction in (0.25, 0.5, 0.75):
            sample_x = ax + (bx - ax) * fraction
            sample_y = ay + (by - ay) * fraction
            offset_x = sample_x - point.center_x
            offset_y = sample_y - point.center_y
            distance = math.hypot(offset_x, offset_y)
            if distance < 90.0 or distance > LOCAL_GEOMETRY_RADIUS:
                continue
            alignment = (offset_x * direction[0] + offset_y * direction[1]) / distance
            if alignment <= threshold:
                continue
            angular_weight = (alignment - threshold) / (1.0 - threshold)
            distance_weight = 1.0 - distance / LOCAL_GEOMETRY_RADIUS
            congestion += angular_weight * distance_weight * length_weight / 3.0
    return congestion


def peer_root_direction_congestion(
    point: PointTarget,
    direction: tuple[float, float],
    peer_points: tuple[PointTarget, ...],
) -> float:
    """Penalize leaders aimed into a nearby cluster of other weld roots."""

    congestion = 0.0
    threshold = math.cos(math.radians(65.0))
    for peer in peer_points:
        if peer is point:
            continue
        offset_x = peer.center_x - point.center_x
        offset_y = peer.center_y - point.center_y
        distance = math.hypot(offset_x, offset_y)
        if distance <= 1e-6 or distance > PEER_ROOT_RADIUS:
            continue
        alignment = (offset_x * direction[0] + offset_y * direction[1]) / distance
        if alignment <= threshold:
            continue
        angular_weight = (alignment - threshold) / (1.0 - threshold)
        congestion += angular_weight * (1.0 - distance / PEER_ROOT_RADIUS)
    return congestion


BEST_EFFORT_GRID_SIZE = 500.0


_BEST_EFFORT_GRID_CACHE: dict[
    tuple[int, int, int],
    tuple[
        dict[tuple[int, int], set[int]],
        dict[tuple[int, int], set[int]],
        dict[tuple[int, int], set[int]],
    ],
] = {}


def _grid_cells(box: tuple[float, float, float, float]) -> tuple[tuple[int, int], ...]:
    left, bottom, right, top = box
    return tuple(
        (x, y)
        for x in range(math.floor(left / BEST_EFFORT_GRID_SIZE), math.floor(right / BEST_EFFORT_GRID_SIZE) + 1)
        for y in range(math.floor(bottom / BEST_EFFORT_GRID_SIZE), math.floor(top / BEST_EFFORT_GRID_SIZE) + 1)
    )


def _build_box_grid(
    boxes: list[tuple[float, float, float, float]],
) -> dict[tuple[int, int], set[int]]:
    grid: dict[tuple[int, int], set[int]] = defaultdict(set)
    for index, box in enumerate(boxes):
        for cell in _grid_cells(box):
            grid[cell].add(index)
    return grid


def _build_segment_grid(
    segments: list[tuple[float, float, float, float, int, int]],
) -> dict[tuple[int, int], set[int]]:
    boxes = [
        (
            min(x1, x2) * SHEET_UNIT,
            min(y1, y2) * SHEET_UNIT,
            max(x1, x2) * SHEET_UNIT,
            max(y1, y2) * SHEET_UNIT,
        )
        for x1, y1, x2, y2, _, _ in segments
    ]
    return _build_box_grid(boxes)


def _grid_indexes(
    grid: dict[tuple[int, int], set[int]],
    box: tuple[float, float, float, float],
) -> set[int]:
    result: set[int] = set()
    for cell in _grid_cells(box):
        result.update(grid.get(cell, ()))
    return result


def candidate_options(
    point: PointTarget,
    source_segments: list[tuple[float, float, float, float, int, int]],
    source_boxes: list[tuple[float, float, float, float]],
    leader_boxes: list[tuple[float, float, float, float]],
    region: LayoutRegion,
    marker_radius: float,
    gap: float,
    normal: tuple[float, float],
    marker_shape: str,
    strict_normal: bool = False,
    preferred_side: int | None = None,
    max_candidates: int = 48,
    fine_search: bool = False,
    root_clearance: float = 700.0,
    semantic_boxes: tuple[tuple[float, float, float, float], ...] = (),
    peer_points: tuple[PointTarget, ...] = (),
    marker_width: float | None = None,
    marker_height: float | None = None,
    best_effort: bool = False,
    allow_fine_fallback: bool = True,
) -> list[PlacementCandidate]:
    min_x, min_y, max_x, max_y = region.drawing
    normal_angle = math.atan2(normal[1], normal[0])
    if strict_normal:
        direction_specs = [(preferred_side or side, 0.0) for side in ((preferred_side,) if preferred_side else (1, -1))]
    else:
        if best_effort:
            # Dense pages need enough angular diversity to separate many
            # nearby roots.  The spatial obstacle grids keep this wider
            # inventory inexpensive; the former 0/+/-45-degree set forced
            # otherwise avoidable marker/leader conflicts on crowded pages.
            angles = (15.0, 30.0, 45.0, 60.0, 75.0)
        else:
            angles = (
                tuple(step * 2.5 for step in range(1, 36))
                if fine_search
                else (7.5, 15.0, 22.5, 30.0, 37.5, 45.0, 52.5, 60.0, 67.5, 75.0, 82.5)
            )
        deviations = (0.0,) + tuple(
            signed * angle for angle in angles for signed in (1, -1)
        )
        sides = (preferred_side,) if preferred_side else (1, -1)
        direction_specs = [(side, math.radians(deviation)) for side in sides for deviation in deviations]

    options: list[PlacementCandidate] = []
    rejected: dict[str, int] = defaultdict(int)
    seen: set[tuple[int, int]] = set()
    sector_congestion_by_direction: dict[tuple[int, int], float] = {}
    segment_grid = text_grid = leader_text_grid = None
    if best_effort:
        cache_key = (id(source_segments), id(source_boxes), id(leader_boxes))
        cached = _BEST_EFFORT_GRID_CACHE.get(cache_key)
        if cached is None:
            cached = (
                _build_segment_grid(source_segments),
                _build_box_grid(source_boxes),
                _build_box_grid(leader_boxes),
            )
            _BEST_EFFORT_GRID_CACHE[cache_key] = cached
        segment_grid, text_grid, leader_text_grid = cached
    radial_steps = (
        (700, 1100, 1600, 2200, 3000, 4000, 5000)
        if best_effort
        else (range(350, 6501, 50) if fine_search else range(400, 5201, 100))
    )
    for radius in radial_steps:
        for side, deviation in direction_specs:
            angle = normal_angle + (0 if side == 1 else math.pi) + deviation
            dx, dy = math.cos(angle), math.sin(angle)
            center_x = point.center_x + dx * radius
            center_y = point.center_y + dy * radius
            half_width = marker_width / 2.0 if marker_width is not None else marker_radius
            half_height = marker_height / 2.0 if marker_height is not None else marker_radius
            marker_box = (
                center_x - half_width - gap,
                center_y - half_height - gap,
                center_x + half_width + gap,
                center_y + half_height + gap,
            )
            source_gap = min(gap, SOURCE_MARKER_CLEARANCE)
            source_marker_box = (
                center_x - half_width - source_gap,
                center_y - half_height - source_gap,
                center_x + half_width + source_gap,
                center_y + half_height + source_gap,
            )
            if (
                marker_box[0] < min_x
                or marker_box[1] < min_y
                or marker_box[2] > max_x
                or marker_box[3] > max_y
            ):
                rejected["drawing-boundary"] += 1
                continue
            key = (round(center_x), round(center_y))
            marker_text_boxes = (
                [source_boxes[index] for index in _grid_indexes(text_grid, source_marker_box)]
                if best_effort and text_grid is not None
                else source_boxes
            )
            text_overlap_count = (
                int(any(boxes_overlap(source_marker_box, obstacle) for obstacle in marker_text_boxes))
                if best_effort
                else sum(
                    boxes_overlap(source_marker_box, obstacle)
                    for obstacle in source_boxes
                )
            )
            if key in seen or (text_overlap_count and not best_effort):
                rejected["marker-text"] += 1
                continue
            marker_segments = (
                [source_segments[index] for index in _grid_indexes(segment_grid, source_marker_box)]
                if best_effort and segment_grid is not None
                else source_segments
            )
            geometry_tests = (
                segment_intersects_box(
                    (x1 * SHEET_UNIT, y1 * SHEET_UNIT, x2 * SHEET_UNIT, y2 * SHEET_UNIT),
                    source_marker_box,
                )
                for x1, y1, x2, y2, _, _ in marker_segments
            )
            geometry_overlap_count = (
                int(any(geometry_tests)) if best_effort else sum(geometry_tests)
            )
            if geometry_overlap_count and not best_effort:
                rejected["marker-geometry"] += 1
                continue
            leader_x, leader_y = marker_edge(
                point.center_x,
                point.center_y,
                center_x,
                center_y,
                marker_shape,
                marker_radius,
                marker_width,
                marker_height,
            )
            leader = (point.center_x, point.center_y, leader_x, leader_y)
            leader_bounds = (
                min(leader[0], leader[2]),
                min(leader[1], leader[3]),
                max(leader[0], leader[2]),
                max(leader[1], leader[3]),
            )
            candidate_leader_segments = (
                [source_segments[index] for index in _grid_indexes(segment_grid, leader_bounds)]
                if best_effort and segment_grid is not None
                else source_segments
            )
            candidate_leader_boxes = (
                [leader_boxes[index] for index in _grid_indexes(leader_text_grid, leader_bounds)]
                if best_effort and leader_text_grid is not None
                else leader_boxes
            )
            strict_leader_clear = leader_clear_of_source(
                leader,
                candidate_leader_segments,
                candidate_leader_boxes,
                root_clearance=root_clearance,
            )
            if not strict_leader_clear and not best_effort:
                rejected["leader-source"] += 1
                continue
            # The broad root exemption above is needed for welds embedded in
            # dense tee/flange symbols, but it used to make every short leader
            # look equally clear. Re-evaluate with only a small root allowance
            # and strongly prefer a genuinely blank lane whenever one exists.
            remote_source_clear = (
                strict_leader_clear
                if best_effort
                else leader_clear_of_source(
                    leader,
                    source_segments,
                    leader_boxes,
                    root_clearance=PREFERRED_ROOT_CLEARANCE,
                )
            )
            avoidable_crossing_penalty = (
                0.0 if remote_source_clear else AVOIDABLE_SOURCE_CROSSING_PENALTY
            )
            crossed_lines, crossed_text_boxes = (
                (0, 0)
                if best_effort
                else leader_source_crossing_counts(
                    leader,
                    source_segments,
                    leader_boxes,
                    # Fitting, elbow and weld-symbol strokes immediately around
                    # the root are unavoidable exit geometry, not routing
                    # obstacles. Collinear/near-parallel overlap is assessed
                    # separately by the corridor metric below.
                    root_clearance=PREFERRED_ROOT_CLEARANCE,
                )
            )
            crossing_count_penalty = (
                crossed_lines * SOURCE_LINE_CROSSING_PENALTY
                + crossed_text_boxes * SOURCE_TEXT_CROSSING_PENALTY
            )
            corridor_penalty = (
                0.0
                if best_effort
                else leader_corridor_congestion(leader, source_segments)
                * SOURCE_CORRIDOR_PENALTY
            )
            direction_ratio = min(abs(dx), abs(dy)) / max(abs(dx), abs(dy), 1e-9)
            cardinal_collapse = max(
                0.0,
                (CONGESTED_CARDINAL_RATIO - direction_ratio) / CONGESTED_CARDINAL_RATIO,
            )
            congested_cardinal_penalty = (
                cardinal_collapse
                * min(1.0, corridor_penalty / (2.0 * SOURCE_CORRIDOR_PENALTY))
                * CONGESTED_CARDINAL_PENALTY
            )
            direction_key = (round(dx * 10000), round(dy * 10000))
            sector_congestion = 0.0 if best_effort else sector_congestion_by_direction.get(direction_key)
            if sector_congestion is None:
                sector_congestion = directional_sector_congestion(
                    point, (dx, dy), source_segments
                )
                sector_congestion_by_direction[direction_key] = sector_congestion
            sector_penalty = sector_congestion * DIRECTIONAL_SECTOR_PENALTY
            peer_penalty = (
                peer_root_direction_congestion(point, (dx, dy), peer_points)
                * PEER_ROOT_DIRECTION_PENALTY
            )
            angular_penalty = abs(math.degrees(deviation)) * 7.0
            side_penalty = 0.0 if preferred_side is None or side == preferred_side else 800.0
            edge_clearance = min(
                marker_box[0] - min_x,
                marker_box[1] - min_y,
                max_x - marker_box[2],
                max_y - marker_box[3],
            )
            edge_penalty = max(0.0, 180.0 - edge_clearance) * 1.5
            # Boxed source material/component numbers are semantically easy
            # to confuse with weld numbers. Prefer candidates outside their
            # vicinity, but keep this as a cost rather than a rejection so a
            # dense page never loses all otherwise valid straight leaders.
            semantic_penalty = 5000.0 * sum(
                boxes_overlap(
                    marker_box,
                    (
                        box[0] - 85.0,
                        box[1] - 85.0,
                        box[2] + 85.0,
                        box[3] + 85.0,
                    ),
                )
                for box in semantic_boxes
            )
            placement = CalloutPlacement(
                center_x,
                center_y,
                leader_x,
                leader_y,
                TEXT_NUMBER_TEMPLATE,
                score=(
                    radius
                    + angular_penalty
                    + side_penalty
                    + edge_penalty
                    + semantic_penalty
                    + avoidable_crossing_penalty
                    + crossing_count_penalty
                    + corridor_penalty
                    + congested_cardinal_penalty
                    + sector_penalty
                    + peer_penalty
                    + text_overlap_count * 2_000_000.0
                    + geometry_overlap_count * 3_000_000.0
                    + (0.0 if strict_leader_clear else 4_000_000.0)
                ),
                marker_radius=marker_radius,
            )
            options.append(
                PlacementCandidate(
                    placement=placement,
                    marker_box=marker_box,
                    remote_source_clear=remote_source_clear,
                    source_line_crossings=crossed_lines,
                    source_text_crossings=crossed_text_boxes,
                )
            )
            seen.add(key)
    options.sort(key=lambda candidate: candidate.placement.score)
    if (
        allow_fine_fallback
        and 0 < len(options) < 8
        and not fine_search
        and not strict_normal
    ):
        # A handful of coarse candidates can still be pairwise unusable for
        # adjacent welds. The fine grid is a superset of the coarse angular
        # and radial lattice, so replace the sparse set before global solving.
        return candidate_options(
            point=point,
            source_segments=source_segments,
            source_boxes=source_boxes,
            leader_boxes=leader_boxes,
            region=region,
            marker_radius=marker_radius,
            gap=gap,
            normal=normal,
            marker_shape=marker_shape,
            strict_normal=strict_normal,
            preferred_side=preferred_side,
            max_candidates=max_candidates,
            fine_search=True,
            root_clearance=root_clearance,
            semantic_boxes=semantic_boxes,
            peer_points=peer_points,
            marker_width=marker_width,
            marker_height=marker_height,
            best_effort=best_effort,
            allow_fine_fallback=allow_fine_fallback,
        )
    if allow_fine_fallback and not options and not fine_search and not strict_normal:
        return candidate_options(
            point=point,
            source_segments=source_segments,
            source_boxes=source_boxes,
            leader_boxes=leader_boxes,
            region=region,
            marker_radius=marker_radius,
            gap=gap,
            normal=normal,
            marker_shape=marker_shape,
            strict_normal=strict_normal,
            preferred_side=preferred_side,
            max_candidates=max_candidates,
            fine_search=True,
            root_clearance=root_clearance,
            semantic_boxes=semantic_boxes,
            peer_points=peer_points,
            marker_width=marker_width,
            marker_height=marker_height,
            best_effort=best_effort,
            allow_fine_fallback=allow_fine_fallback,
        )
    if fine_search and len(options) < 24 and root_clearance < 700.0:
        # Some weld dots sit inside a dense tee/valve/flange symbol. A straight
        # leader cannot leave that closed local envelope without crossing one
        # of the symbol's own strokes. Sparse fine-search results also leave
        # adjacent welds with no separable pair, so widen only the root-local
        # exemption; all geometry beyond it remains strictly protected.
        return candidate_options(
            point=point,
            source_segments=source_segments,
            source_boxes=source_boxes,
            leader_boxes=leader_boxes,
            region=region,
            marker_radius=marker_radius,
            gap=gap,
            normal=normal,
            marker_shape=marker_shape,
            strict_normal=strict_normal,
            preferred_side=preferred_side,
            max_candidates=max_candidates,
            fine_search=True,
            root_clearance=700.0,
            semantic_boxes=semantic_boxes,
            peer_points=peer_points,
            marker_width=marker_width,
            marker_height=marker_height,
            best_effort=best_effort,
            allow_fine_fallback=allow_fine_fallback,
        )
    if not options:
        print(
            f"No candidates after {'fine' if fine_search else 'coarse'} search "
            f"with root-clearance {root_clearance:.0f} "
            f"for page {point.page} weld-ref {point.graphic_ref} at "
            f"({point.center_x:.1f}, {point.center_y:.1f}); rejected={dict(rejected)}"
        )
    if len(options) <= max_candidates:
        return options
    # Keep short preferred candidates plus a deterministic sample of farther
    # lanes; dense pages often need one non-local move to remove crossings.
    head_count = max_candidates // 2
    selected = list(options[:head_count])
    remainder = options[head_count:]
    for index in range(max_candidates - head_count):
        position = round(index * (len(remainder) - 1) / max(1, max_candidates - head_count - 1))
        selected.append(remainder[position])
    return selected


def candidates_conflict(
    first_point: PointTarget,
    first: PlacementCandidate,
    second_point: PointTarget,
    second: PlacementCandidate,
) -> bool:
    return bool(
        candidate_conflict_reasons(
            first_point, first, second_point, second
        )
    )


def candidate_conflict_reasons(
    first_point: PointTarget,
    first: PlacementCandidate,
    second_point: PointTarget,
    second: PlacementCandidate,
) -> tuple[str, ...]:
    def marker_spacing_box(box: tuple[float, float, float, float]) -> tuple[float, float, float, float]:
        # Preserve 20 units between visible markers. The larger 60-unit box
        # is retained for frame and source-geometry clearance.
        left, bottom, right, top = box
        # Match the verifier's physical marker + 10-unit spacing envelope.
        # Candidate boxes include the 60-unit source clearance, so a 50-unit
        # inset removes only that excess without permitting visible overlap.
        inset = min(50.0, (right - left) * 0.15, (top - bottom) * 0.15)
        return left + inset, bottom + inset, right - inset, top - inset

    if boxes_overlap(marker_spacing_box(first.marker_box), marker_spacing_box(second.marker_box)):
        return ("marker-marker",)
    def physical_marker_box(box: tuple[float, float, float, float]) -> tuple[float, float, float, float]:
        # Candidate boxes carry the 60-unit marker-to-marker clearance. A
        # leader only needs to avoid the visible marker itself.
        left, bottom, right, top = box
        inset = min(60.0, (right - left) * 0.20, (top - bottom) * 0.20)
        return left + inset, bottom + inset, right - inset, top - inset

    first_leader = (
        first_point.center_x,
        first_point.center_y,
        first.placement.leader_x,
        first.placement.leader_y,
    )
    second_leader = (
        second_point.center_x,
        second_point.center_y,
        second.placement.leader_x,
        second.placement.leader_y,
    )
    reasons = []
    shared_root = math.hypot(
        first_point.center_x - second_point.center_x,
        first_point.center_y - second_point.center_y,
    ) <= 1.0
    if not shared_root and segments_intersect(first_leader, second_leader):
        reasons.append("leader-leader")
    if segment_intersects_box(
        first_leader, physical_marker_box(second.marker_box)
    ):
        reasons.append("first-leader-second-marker")
    if segment_intersects_box(
        second_leader, physical_marker_box(first.marker_box)
    ):
        reasons.append("second-leader-first-marker")
    return tuple(reasons)


def solve_page_layout(
    points: list[PointTarget],
    options_by_point: list[list[PlacementCandidate]],
    node_limit: int = 180_000,
    allow_conflicts: bool = False,
) -> list[CalloutPlacement]:
    """Choose one locally valid candidate per weld with zero page conflicts."""

    if len(points) != len(options_by_point):
        raise ValueError("Point/candidate count mismatch")
    empty = [index for index, options in enumerate(options_by_point) if not options]
    if empty:
        raise ValueError(f"No locally valid straight-leader candidate for weld indexes {empty}")

    count = len(points)
    full_domains = [(1 << len(options)) - 1 for options in options_by_point]
    compatible: list[list[list[int]]] = [
        [[full_domains[other] for other in range(count)] for _ in options]
        for options in options_by_point
    ]
    for first_index in range(count):
        for second_index in range(first_index + 1, count):
            for first_candidate, first in enumerate(options_by_point[first_index]):
                second_mask = 0
                for second_candidate, second in enumerate(options_by_point[second_index]):
                    if not candidates_conflict(
                        points[first_index], first, points[second_index], second
                    ):
                        second_mask |= 1 << second_candidate
                        compatible[second_index][second_candidate][first_index] |= 1 << first_candidate
                    else:
                        compatible[second_index][second_candidate][first_index] &= ~(1 << first_candidate)
                compatible[first_index][first_candidate][second_index] = second_mask

    impossible_pairs = [
        (first_index, second_index)
        for first_index in range(count)
        for second_index in range(first_index + 1, count)
        if not any(
            compatible[first_index][candidate][second_index]
            for candidate in range(len(options_by_point[first_index]))
        )
    ]
    if impossible_pairs:
        details = [
            (
                pair,
                points[pair[0]].graphic_ref,
                points[pair[1]].graphic_ref,
                len(options_by_point[pair[0]]),
                len(options_by_point[pair[1]]),
            )
            for pair in impossible_pairs
        ]
        print(f"Globally incompatible weld pairs: {details}")
        for first_index, second_index in impossible_pairs:
            reason_counts: dict[str, int] = defaultdict(int)
            for first in options_by_point[first_index]:
                for second in options_by_point[second_index]:
                    for reason in candidate_conflict_reasons(
                        points[first_index],
                        first,
                        points[second_index],
                        second,
                    ):
                        reason_counts[reason] += 1
            print(
                "Incompatible pair diagnostics: "
                f"refs=({points[first_index].graphic_ref}, "
                f"{points[second_index].graphic_ref}) "
                f"roots=(({points[first_index].center_x:.1f},"
                f"{points[first_index].center_y:.1f}),"
                f"({points[second_index].center_x:.1f},"
                f"{points[second_index].center_y:.1f})) "
                f"reason-counts={dict(reason_counts)}"
            )

    assigned = [-1] * count
    nodes = 0

    def search(current_domains: list[int], assigned_count: int) -> bool:
        nonlocal nodes
        nodes += 1
        if nodes > node_limit:
            return False
        if assigned_count == count:
            return True
        variable = min(
            (index for index in range(count) if assigned[index] < 0),
            key=lambda index: current_domains[index].bit_count(),
        )
        domain = current_domains[variable]
        values = [candidate for candidate in range(len(options_by_point[variable])) if domain & (1 << candidate)]
        for candidate in values:
            reduced = list(current_domains)
            reduced[variable] = 1 << candidate
            feasible = True
            for other in range(count):
                if other == variable or assigned[other] >= 0:
                    continue
                reduced[other] &= compatible[variable][candidate][other]
                if reduced[other] == 0:
                    feasible = False
                    break
            if not feasible:
                continue
            assigned[variable] = candidate
            if search(reduced, assigned_count + 1):
                return True
            assigned[variable] = -1
        return False

    # A best-effort retry follows a strict pass that has already proved the
    # page unsatisfiable.  Do not repeat the exponential proof here.
    solved = False if allow_conflicts else search(list(full_domains), 0)
    best_relaxed: tuple[tuple[int, int, float], list[int]] | None = None
    if not solved:
        # Deterministic min-conflicts fallback handles large dense components
        # without ever accepting a crossing as a valid final result.
        rng = random.Random(0x534841)
        # The best-effort path is used only after the strict layout failed.
        # With the spatially bounded 48-candidate inventory, a deeper
        # deterministic min-conflicts search is still cheap and materially
        # reduces avoidable clashes on very dense pages.
        restart_count = 8 if allow_conflicts else 24
        iteration_count = 1500 if allow_conflicts else 2500
        for restart in range(restart_count):
            chosen = [
                (restart * 7 + index * 11) % len(options)
                for index, options in enumerate(options_by_point)
            ]
            for _ in range(iteration_count):
                conflict_pairs = sum(
                    not (
                        compatible[first][chosen[first]][second]
                        & (1 << chosen[second])
                    )
                    for first in range(count)
                    for second in range(first + 1, count)
                )
                conflict_callouts = sum(
                    any(
                        other != index
                        and not (
                            compatible[index][chosen[index]][other]
                            & (1 << chosen[other])
                        )
                        for other in range(count)
                    )
                    for index in range(count)
                )
                relaxed_rank = (
                    conflict_pairs,
                    conflict_callouts,
                    sum(
                        options_by_point[index][candidate].placement.score
                        for index, candidate in enumerate(chosen)
                    ),
                )
                if best_relaxed is None or relaxed_rank < best_relaxed[0]:
                    best_relaxed = (relaxed_rank, list(chosen))
                bad = [
                    index
                    for index in range(count)
                    if any(
                        other != index
                        and not (compatible[index][chosen[index]][other] & (1 << chosen[other]))
                        for other in range(count)
                    )
                ]
                if not bad:
                    assigned = list(chosen)
                    solved = True
                    break
                variable = (
                    rng.choice(bad)
                    if allow_conflicts
                    else max(
                        bad,
                        key=lambda index: sum(
                            not (compatible[index][chosen[index]][other] & (1 << chosen[other]))
                            for other in range(count)
                            if other != index
                        ),
                    )
                )
                ranked = []
                for candidate in range(len(options_by_point[variable])):
                    conflict_count = sum(
                        not (compatible[variable][candidate][other] & (1 << chosen[other]))
                        for other in range(len(points))
                        if other != variable
                    )
                    ranked.append((conflict_count, options_by_point[variable][candidate].placement.score, candidate))
                best_count = min(item[0] for item in ranked)
                best = [item for item in ranked if item[0] == best_count]
                chosen[variable] = (
                    rng.choice(best)[2]
                    if allow_conflicts
                    else min(best, key=lambda item: (item[1], rng.random()))[2]
                )
            if solved:
                break
    if not solved:
        if allow_conflicts and best_relaxed is not None:
            assigned = best_relaxed[1]
            print(
                "Best-effort straight-leader layout used; "
                f"conflict-rank={best_relaxed[0]}"
            )
        else:
            raise ValueError(
                f"No zero-crossing global layout after {nodes} exact-search nodes and deterministic min-conflicts"
            )

    if allow_conflicts:
        # The refinements below assume an already conflict-free assignment
        # and search compatible single/pair moves.  Running them on an
        # intentionally minimum-conflict fallback is both invalid and cubic
        # in dense-page size; retain the audited min-conflicts result.
        return [
            options_by_point[index][candidate].placement
            for index, candidate in enumerate(assigned)
        ]

    # Improve local length/angle cost without changing feasibility.
    for variable in range(len(assigned)):
        current = assigned[variable]
        for candidate in range(current):
            if not any(
                other != variable
                and not (compatible[variable][candidate][other] & (1 << assigned[other]))
                for other in range(len(assigned))
            ):
                assigned[variable] = candidate
                break

    # A single-variable improvement can be trapped when a clear lane for one
    # weld is occupied by a neighbour's otherwise cheap marker. Allow a pair
    # to move together when their combined score decreases. The large
    # avoidable-crossing penalty makes a genuinely blank lane dominate while
    # preserving the zero-conflict constraints established above.
    for _ in range(count):
        improved = False
        for first in range(count):
            current_first = assigned[first]
            if (
                options_by_point[first][current_first].placement.score
                < AVOIDABLE_SOURCE_CROSSING_PENALTY
            ):
                continue
            best_move: tuple[float, int, int, int] | None = None
            for second in range(count):
                if second == first:
                    continue
                current_second = assigned[second]
                current_pair_score = (
                    options_by_point[first][current_first].placement.score
                    + options_by_point[second][current_second].placement.score
                )
                for first_candidate, first_option in enumerate(options_by_point[first]):
                    if first_option.placement.score >= current_pair_score:
                        break
                    if any(
                        other not in {first, second}
                        and not (
                            compatible[first][first_candidate][other]
                            & (1 << assigned[other])
                        )
                        for other in range(count)
                    ):
                        continue
                    for second_candidate, second_option in enumerate(options_by_point[second]):
                        pair_score = (
                            first_option.placement.score
                            + second_option.placement.score
                        )
                        if pair_score >= current_pair_score:
                            break
                        if not (
                            compatible[first][first_candidate][second]
                            & (1 << second_candidate)
                        ):
                            continue
                        if any(
                            other not in {first, second}
                            and not (
                                compatible[second][second_candidate][other]
                                & (1 << assigned[other])
                            )
                            for other in range(count)
                        ):
                            continue
                        gain = current_pair_score - pair_score
                        if best_move is None or gain > best_move[0]:
                            best_move = (
                                gain,
                                second,
                                first_candidate,
                                second_candidate,
                            )
            if best_move is not None:
                _, second, first_candidate, second_candidate = best_move
                assigned[first] = first_candidate
                assigned[second] = second_candidate
                improved = True
                break
        if not improved:
            break

    return [options_by_point[index][assigned[index]].placement for index in range(len(points))]


def solve_page_layout_in_preferred_bands(
    points: list[PointTarget],
    options_by_point: list[list[PlacementCandidate]],
    preferred_ranges: list[tuple[float, float]],
    node_limit: int = 180_000,
    layout_audit: dict[str, object] | None = None,
) -> list[CalloutPlacement]:
    """Solve zero-conflict layout in a normal leader-length band first.

    Uniform, readable leaders are preferable to globally shortest leaders.
    The search therefore admits only the normal band first and widens it in
    deterministic stages.  A very short or very long leader can only appear
    after the tighter stages have proved infeasible.
    """

    if len(points) != len(options_by_point) or len(points) != len(preferred_ranges):
        raise ValueError("Point/candidate/preferred-range count mismatch")

    stages: tuple[tuple[str, float | None, float | None], ...] = (
        ("preferred", 0.0, 0.0),
        ("near", 150.0, 250.0),
        ("expanded", 300.0, 650.0),
        ("wide", 500.0, 1400.0),
        ("unbounded", None, None),
    )
    last_error: ValueError | None = None
    for stage_name, shorten, extend in stages:
        staged: list[list[PlacementCandidate]] = []
        for point, options, (preferred_min, preferred_max) in zip(
            points, options_by_point, preferred_ranges
        ):
            if shorten is None or extend is None:
                selected = list(options)
            else:
                lower = max(0.0, preferred_min - shorten)
                upper = preferred_max + extend
                selected = [
                    option
                    for option in options
                    if lower
                    <= math.hypot(
                        option.placement.leader_x - point.center_x,
                        option.placement.leader_y - point.center_y,
                    )
                    <= upper
                ]
            staged.append(selected)
        if any(not options for options in staged):
            continue
        try:
            placements = solve_page_layout(
                points,
                staged,
                node_limit=node_limit,
                allow_conflicts=False,
            )
        except ValueError as exc:
            last_error = exc
            continue
        if layout_audit is not None:
            lengths = [
                math.hypot(
                    placement.leader_x - point.center_x,
                    placement.leader_y - point.center_y,
                )
                for point, placement in zip(points, placements)
            ]
            layout_audit.update(
                {
                    "leader_length_stage": stage_name,
                    "leader_length_min": round(min(lengths), 1) if lengths else 0.0,
                    "leader_length_max": round(max(lengths), 1) if lengths else 0.0,
                }
            )
        return placements
    raise ValueError(f"No zero-conflict layout in any leader-length band: {last_error}")


def nearest_segment_guide(
    point: PointTarget, source_segments: list[tuple[float, float, float, float, int, int]]
) -> tuple[tuple[float, float], tuple[float, float], tuple[int, int]]:
    """Return a stable tangent/normal and a coarse key for one pipe run."""

    # Do not orient a weld callout from a flange edge, small reducer outline,
    # or symbol stroke. Long Sheet segments are the actual pipe-run evidence.
    pipe_segments = [
        item
        for item in source_segments
        if math.hypot((item[2] - item[0]) * SHEET_UNIT, (item[3] - item[1]) * SHEET_UNIT) >= 220.0
    ] or source_segments
    x1, y1, x2, y2, _, _ = min(
        pipe_segments,
        key=lambda item: point_segment_distance(
            point.center_x, point.center_y,
            item[0] * SHEET_UNIT, item[1] * SHEET_UNIT,
            item[2] * SHEET_UNIT, item[3] * SHEET_UNIT,
        ),
    )
    dx, dy = (x2 - x1) * SHEET_UNIT, (y2 - y1) * SHEET_UNIT
    length = math.hypot(dx, dy)
    if length < 1e-6:
        return (1.0, 0.0), (0.0, 1.0), (0, 0)
    tangent = (dx / length, dy / length)
    if tangent[0] < 0 or (abs(tangent[0]) < 1e-6 and tangent[1] < 0):
        tangent = (-tangent[0], -tangent[1])
    normal = (-tangent[1], tangent[0])
    angle_bin = round(math.degrees(math.atan2(tangent[1], tangent[0])) / 10)
    offset_bin = round((point.center_x * normal[0] + point.center_y * normal[1]) / 200)
    return tangent, normal, (angle_bin, offset_bin)

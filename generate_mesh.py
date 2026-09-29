#!/usr/bin/env python3
"""Generate a compact low-poly treasure chest as a Wavefront OBJ.

The script uses only the Python standard library. Geometry is built directly
as triangles and quads so it can be validated without Blender.
"""

from __future__ import annotations

import argparse
import math
from pathlib import Path


REGRESSION_WIDTH_SCALE = 1.5


def format_coordinate(value: float) -> str:
    """Format a coordinate with six decimals, never emitting a negative zero.

    Trigonometric terms such as cos(pi / 2) yield tiny values whose sign can
    differ between platforms. Rounding them to six decimals gives "-0.000000"
    or "0.000000" depending on that sign, so the sign of any value that rounds
    to zero is dropped when it is serialized.
    """
    text = f"{value:.6f}"
    return "0.000000" if text == "-0.000000" else text


class MeshBuilder:
    def __init__(self) -> None:
        self.vertices: list[tuple[float, float, float]] = []
        self.faces: list[tuple[int, ...]] = []

    def add_vertex(self, point: tuple[float, float, float]) -> int:
        self.vertices.append(tuple(float(v) for v in point))
        return len(self.vertices)

    def add_face(self, indices: tuple[int, ...] | list[int]) -> None:
        if len(indices) not in (3, 4):
            raise ValueError("Generated faces must be triangles or quads")
        self.faces.append(tuple(indices))

    def add_box(
        self,
        center: tuple[float, float, float],
        size: tuple[float, float, float],
    ) -> None:
        cx, cy, cz = center
        sx, sy, sz = (value / 2.0 for value in size)
        points = [
            (cx - sx, cy - sy, cz - sz),
            (cx + sx, cy - sy, cz - sz),
            (cx + sx, cy + sy, cz - sz),
            (cx - sx, cy + sy, cz - sz),
            (cx - sx, cy - sy, cz + sz),
            (cx + sx, cy - sy, cz + sz),
            (cx + sx, cy + sy, cz + sz),
            (cx - sx, cy + sy, cz + sz),
        ]
        first = len(self.vertices) + 1
        self.vertices.extend(points)
        faces = (
            (0, 3, 2, 1),  # bottom
            (4, 5, 6, 7),  # top
            (0, 1, 5, 4),  # front (-Y)
            (3, 7, 6, 2),  # back (+Y)
            (0, 4, 7, 3),  # left (-X)
            (1, 2, 6, 5),  # right (+X)
        )
        for face in faces:
            self.add_face([first + index for index in face])

    def add_extruded_profile_x(
        self,
        x_min: float,
        x_max: float,
        profile_yz: list[tuple[float, float]],
    ) -> None:
        """Extrude a simple YZ polygon along X; triangulate both end caps."""
        if len(profile_yz) < 3:
            raise ValueError("An extruded profile needs at least three points")

        first = len(self.vertices) + 1
        for x in (x_min, x_max):
            self.vertices.extend((x, y, z) for y, z in profile_yz)
        count = len(profile_yz)

        for index in range(count):
            following = (index + 1) % count
            self.add_face(
                (
                    first + index,
                    first + following,
                    first + count + following,
                    first + count + index,
                )
            )

        center_y = sum(point[0] for point in profile_yz) / count
        center_z = sum(point[1] for point in profile_yz) / count
        cap_min = self.add_vertex((x_min, center_y, center_z))
        cap_max = self.add_vertex((x_max, center_y, center_z))
        for index in range(count):
            following = (index + 1) % count
            self.add_face((cap_min, first + following, first + index))
            self.add_face(
                (
                    cap_max,
                    first + count + index,
                    first + count + following,
                )
            )

    def add_half_round_plank(
        self,
        x_min: float,
        x_max: float,
        radius: float,
        base_z: float,
        segments: int = 12,
    ) -> None:
        profile = [
            (
                radius * math.cos(math.pi * index / segments),
                base_z + radius * math.sin(math.pi * index / segments),
            )
            for index in range(segments + 1)
        ]
        self.add_extruded_profile_x(x_min, x_max, profile)

    def add_uv_sphere(
        self,
        center: tuple[float, float, float],
        radius: float,
        segments: int = 8,
        rings: int = 4,
    ) -> None:
        cx, cy, cz = center
        bottom = self.add_vertex((cx, cy, cz - radius))
        ring_starts: list[int] = []
        for ring in range(1, rings):
            theta = math.pi * ring / rings
            start = len(self.vertices) + 1
            ring_starts.append(start)
            for segment in range(segments):
                phi = 2.0 * math.pi * segment / segments
                self.vertices.append(
                    (
                        cx + radius * math.sin(theta) * math.cos(phi),
                        cy + radius * math.sin(theta) * math.sin(phi),
                        cz - radius * math.cos(theta),
                    )
                )
        top = self.add_vertex((cx, cy, cz + radius))

        first_ring = ring_starts[0]
        for segment in range(segments):
            following = (segment + 1) % segments
            self.add_face((bottom, first_ring + following, first_ring + segment))

        for ring_index in range(len(ring_starts) - 1):
            lower = ring_starts[ring_index]
            upper = ring_starts[ring_index + 1]
            for segment in range(segments):
                following = (segment + 1) % segments
                self.add_face(
                    (
                        lower + segment,
                        lower + following,
                        upper + following,
                        upper + segment,
                    )
                )

        last_ring = ring_starts[-1]
        for segment in range(segments):
            following = (segment + 1) % segments
            self.add_face((top, last_ring + segment, last_ring + following))

    def add_torus_yz(
        self,
        side: float,
        center_x: float,
        center_y: float,
        center_z: float,
        major_radius: float,
        tube_radius: float,
        path_segments: int = 12,
        tube_segments: int = 6,
    ) -> None:
        """Create a small polygonal ring handle in a YZ plane."""
        first = len(self.vertices) + 1
        for path_index in range(path_segments):
            phi = 2.0 * math.pi * path_index / path_segments
            radial_y = math.cos(phi)
            radial_z = math.sin(phi)
            path_y = center_y + major_radius * radial_y
            path_z = center_z + major_radius * radial_z
            for tube_index in range(tube_segments):
                psi = 2.0 * math.pi * tube_index / tube_segments
                self.vertices.append(
                    (
                        center_x + side * tube_radius * math.cos(psi),
                        path_y + tube_radius * radial_y * math.sin(psi),
                        path_z + tube_radius * radial_z * math.sin(psi),
                    )
                )

        for path_index in range(path_segments):
            next_path = (path_index + 1) % path_segments
            for tube_index in range(tube_segments):
                next_tube = (tube_index + 1) % tube_segments
                a = first + path_index * tube_segments + tube_index
                b = first + next_path * tube_segments + tube_index
                c = first + next_path * tube_segments + next_tube
                d = first + path_index * tube_segments + next_tube
                self.add_face((a, b, c, d))

    def export_obj(self, path: Path) -> None:
        lines = [
            "# Procedural low-poly treasure chest",
            "# Generated by generate_mesh.py; dimensions are in meters.",
            "o LowPolyTreasureChest",
        ]
        lines.extend(
            "v " + " ".join(format_coordinate(axis) for axis in vertex)
            for vertex in self.vertices
        )
        lines.extend(
            "f " + " ".join(str(index) for index in face)
            for face in self.faces
        )
        # Write bytes so line endings are "\n" on every platform.
        path.write_bytes(("\n".join(lines) + "\n").encode("utf-8"))


def build_chest(*, width_scale: float = 1.0) -> MeshBuilder:
    mesh = MeshBuilder()

    # Solid core and five horizontal boards on each side of the chest body.
    body_width = 1.30
    body_depth = 0.78
    body_bottom = 0.08
    body_top = 0.60
    mesh.add_box(
        (0.0, 0.0, (body_bottom + body_top) / 2.0),
        (body_width, body_depth, body_top - body_bottom),
    )

    row_count = 5
    board_height = 0.082
    board_gap = 0.012
    first_board_z = 0.13 + board_height / 2.0
    front_y = -(body_depth / 2.0 + 0.021)
    back_y = body_depth / 2.0 + 0.021
    for row in range(row_count):
        z = first_board_z + row * (board_height + board_gap)
        mesh.add_box((0.0, front_y, z), (body_width, 0.036, board_height))
        mesh.add_box((0.0, back_y, z), (body_width, 0.036, board_height))
        mesh.add_box(
            (-(body_width / 2.0 + 0.014), 0.0, z),
            (0.032, body_depth, board_height),
        )
        mesh.add_box(
            ((body_width / 2.0 + 0.014), 0.0, z),
            (0.032, body_depth, board_height),
        )

    # A sturdy lower wooden rail and four short feet.
    mesh.add_box((0.0, -0.414, 0.12), (1.32, 0.052, 0.09))
    mesh.add_box((0.0, 0.414, 0.12), (1.32, 0.052, 0.09))
    mesh.add_box((-0.664, 0.0, 0.12), (0.052, 0.82, 0.09))
    mesh.add_box((0.664, 0.0, 0.12), (0.052, 0.82, 0.09))
    for x in (-0.55, 0.55):
        for y in (-0.29, 0.29):
            mesh.add_box((x, y, 0.052), (0.17, 0.14, 0.104))

    # Seven curved lid boards with narrow seams between them.
    lid_width = 1.34
    lid_radius = 0.41
    lid_base_z = 0.59
    panel_count = 7
    seam = 0.006
    panel_width = (lid_width - seam * (panel_count - 1)) / panel_count
    x_start = -lid_width / 2.0
    for panel in range(panel_count):
        x_min = x_start + panel * (panel_width + seam)
        mesh.add_half_round_plank(
            x_min,
            x_min + panel_width,
            lid_radius,
            lid_base_z,
            segments=12,
        )

    # Three raised arch ribs make the lid read as a reinforced chest.
    for center_x in (-0.45, 0.0, 0.45):
        mesh.add_half_round_plank(
            center_x - 0.030,
            center_x + 0.030,
            lid_radius + 0.022,
            lid_base_z,
            segments=12,
        )

    # Rear hinges, front latch, and low-poly side handles.
    for x in (-0.43, 0.43):
        mesh.add_box((x, 0.401, 0.625), (0.15, 0.045, 0.075))
        mesh.add_box((x, 0.424, 0.655), (0.070, 0.035, 0.050))

    mesh.add_box((0.0, -0.438, 0.405), (0.15, 0.026, 0.19))
    mesh.add_box((0.0, -0.449, 0.515), (0.070, 0.022, 0.13))
    mesh.add_box((0.0, -0.455, 0.405), (0.070, 0.018, 0.095))
    mesh.add_uv_sphere((0.0, -0.468, 0.405), 0.020, segments=8, rings=4)

    for side in (-1.0, 1.0):
        handle_x = side * 0.686
        for y in (-0.095, 0.095):
            mesh.add_box(
                (handle_x, y, 0.355),
                (0.050, 0.070, 0.075),
            )
        mesh.add_torus_yz(
            side=side,
            center_x=side * 0.704,
            center_y=0.0,
            center_z=0.355,
            major_radius=0.105,
            tube_radius=0.018,
        )

    # Small faceted nails on the front/back boards and on the lid ribs.
    for row in range(row_count):
        z = first_board_z + row * (board_height + board_gap)
        for x in (-0.535, 0.535):
            mesh.add_uv_sphere((x, -0.439, z), 0.012, segments=8, rings=4)
            mesh.add_uv_sphere((x, 0.439, z), 0.012, segments=8, rings=4)
    for x in (-0.45, 0.0, 0.45):
        for y in (-0.420, 0.420):
            mesh.add_uv_sphere((x, y, 0.635), 0.014, segments=8, rings=4)

    if width_scale != 1.0:
        mesh.vertices = [
            (x * width_scale, y, z)
            for x, y, z in mesh.vertices
        ]
    return mesh


def build_invalid_asset() -> MeshBuilder:
    """Build a valid OBJ box that exceeds only the contract's width limit."""
    mesh = MeshBuilder()
    mesh.add_box((0.0, 0.0, 0.20), (2.20, 0.40, 0.40))
    return mesh


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--variant",
        choices=("valid", "invalid", "regression"),
        default="valid",
        help=(
            "generate the baseline chest, a synthetic invalid box, or a chest "
            "with a width regression"
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help=(
            "output OBJ path (default: asset.obj, invalid_asset.obj, or "
            "regression_asset.obj for the selected variant)"
        ),
    )
    args = parser.parse_args()

    default_outputs = {
        "valid": "asset.obj",
        "invalid": "invalid_asset.obj",
        "regression": "regression_asset.obj",
    }
    output = args.output or Path(default_outputs[args.variant])
    if args.variant == "invalid":
        mesh = build_invalid_asset()
    elif args.variant == "regression":
        mesh = build_chest(width_scale=REGRESSION_WIDTH_SCALE)
    else:
        mesh = build_chest()
    mesh.export_obj(output)
    triangles = sum(len(face) - 2 for face in mesh.faces)
    mins = [min(vertex[axis] for vertex in mesh.vertices) for axis in range(3)]
    maxs = [max(vertex[axis] for vertex in mesh.vertices) for axis in range(3)]
    dimensions = [maxs[axis] - mins[axis] for axis in range(3)]

    print(f"Variant: {args.variant}")
    print(f"Wrote {output}")
    print(f"Vertices: {len(mesh.vertices)}")
    print(f"Faces: {len(mesh.faces)}")
    print(f"Triangles: {triangles}")
    print(
        "Dimensions (width x depth x height): "
        f"{dimensions[0]:.3f} x {dimensions[1]:.3f} x {dimensions[2]:.3f} m"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

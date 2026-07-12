import argparse
import json
import math
import sys
import urllib.request
from pathlib import Path
from xml.sax.saxutils import escape

# Blender runs this file with backend/app on sys.path, not the backend package root.
BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.coordinate_frame import MAX_E, MAX_N, MIN_E, MIN_N, SceneFrame


def _clamp(value, low, high):
    return max(low, min(high, value))


def _extent_delta_by_zoom(zoom: int) -> float:
    # Quality mode: widen bbox aggressively for better object completeness.
    if zoom >= 19:
        return 0.0020
    if zoom >= 18:
        return 0.0028
    if zoom >= 17:
        return 0.0036
    if zoom >= 16:
        return 0.0048
    if zoom >= 15:
        return 0.0062
    return 0.0078


def _basemap_size_by_zoom(zoom: int) -> float:
    # Larger-than-coverage mapping so imported blosm geometry stays on top of the basemap.
    if zoom >= 18:
        return 640.0
    if zoom >= 17:
        return 768.0
    if zoom >= 16:
        return 1024.0
    if zoom >= 15:
        return 1280.0
    return 1792.0


def _latlon_to_tile(lat: float, lon: float, zoom: int) -> tuple[int, int]:
    lat_rad = math.radians(lat)
    n = 2.0 ** zoom
    x = int((lon + 180.0) / 360.0 * n)
    y = int((1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n)
    return x, y


def _latlon_to_tile_float(lat: float, lon: float, zoom: int) -> tuple[float, float]:
    lat_rad = math.radians(lat)
    n = 2.0 ** zoom
    x = (lon + 180.0) / 360.0 * n
    y = (1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n
    return x, y


def _tile_xy_to_latlon(tile_x: float, tile_y: float, zoom: int) -> tuple[float, float]:
    n = 2.0 ** zoom
    lon = tile_x / n * 360.0 - 180.0
    lat_rad = math.atan(math.sinh(math.pi * (1.0 - 2.0 * tile_y / n)))
    lat = math.degrees(lat_rad)
    return lat, lon


def _bbox_by_zoom_centered(lat: float, lon: float, zoom: int, span_tiles: float = 2.0) -> tuple[float, float, float, float]:
    """Return min_lat, max_lat, min_lon, max_lon for a bbox centered at lat/lon and sized by zoom tile span."""
    z = max(0, min(19, int(zoom)))
    n = 2.0 ** z
    half_span = max(0.5, float(span_tiles) * 0.5)

    x_f, y_f = _latlon_to_tile_float(lat, lon, z)
    min_x = _clamp(x_f - half_span, 0.0, n)
    max_x = _clamp(x_f + half_span, 0.0, n)
    min_y = _clamp(y_f - half_span, 0.0, n)
    max_y = _clamp(y_f + half_span, 0.0, n)

    max_lat, min_lon = _tile_xy_to_latlon(min_x, min_y, z)
    min_lat, max_lon = _tile_xy_to_latlon(max_x, max_y, z)

    return min(min_lat, max_lat), max(min_lat, max_lat), min(min_lon, max_lon), max(min_lon, max_lon)


def _tile_to_bounds(x: int, y: int, zoom: int) -> tuple[float, float, float, float]:
    """Return north, south, west, east bounds (degrees) for a tile."""
    n = 2.0 ** zoom
    west = x / n * 360.0 - 180.0
    east = (x + 1) / n * 360.0 - 180.0

    def _tile_y_to_lat(tile_y: float) -> float:
        lat_rad = math.atan(math.sinh(math.pi * (1 - 2 * tile_y / n)))
        return math.degrees(lat_rad)

    north = _tile_y_to_lat(y)
    south = _tile_y_to_lat(y + 1)
    return north, south, west, east


def _choose_covering_tile(min_lat: float, max_lat: float, min_lon: float, max_lon: float, start_zoom: int) -> tuple[int, int, int]:
    """Pick a tile (zoom, x, y) that fully covers the bbox, preferring higher zoom."""
    start_zoom = max(0, min(19, int(start_zoom)))
    for z in range(start_zoom, -1, -1):
        x1, y1 = _latlon_to_tile(max_lat, min_lon, z)
        x2, y2 = _latlon_to_tile(min_lat, max_lon, z)
        if x1 == x2 and y1 == y2:
            return z, x1, y1

    cx, cy = _latlon_to_tile((min_lat + max_lat) * 0.5, (min_lon + max_lon) * 0.5, 0)
    return 0, cx, cy


def _degree_to_meter_scales(lat: float) -> tuple[float, float]:
    meters_per_deg_lat = 111320.0
    meters_per_deg_lon = meters_per_deg_lat * math.cos(math.radians(lat))
    return meters_per_deg_lat, max(1.0, meters_per_deg_lon)


GENERATED_SCENE_AREA_M = 512.0
BASEMAP_COVER_PADDING = 1.0
DETAIL_BBOX_SPAN_TILES = 2.6


def _bbox_by_center_meters(lat: float, lon: float, area_m: float) -> tuple[float, float, float, float]:
    half_m = max(1.0, float(area_m)) * 0.5
    meters_per_deg_lat, meters_per_deg_lon = _degree_to_meter_scales(lat)
    lat_delta = half_m / meters_per_deg_lat
    lon_delta = half_m / meters_per_deg_lon
    min_lat = _clamp(lat - lat_delta, -89.0, 89.0)
    max_lat = _clamp(lat + lat_delta, -89.0, 89.0)
    min_lon = _clamp(lon - lon_delta, -180.0, 180.0)
    max_lon = _clamp(lon + lon_delta, -180.0, 180.0)
    return min_lat, max_lat, min_lon, max_lon


def scene_frame_metadata(scene_key: str, lat: float, lon: float, alt_m: float = 0.0) -> dict:
    return SceneFrame(
        frame_id=f"scene-{scene_key.lower()}",
        origin_lat=float(lat),
        origin_lon=float(lon),
        origin_alt_m=float(alt_m),
    ).to_dict()


def _basemap_size_for_imported_bounds(area_m: float, imported_width: float, imported_height: float) -> tuple[float, float, str]:
    base_size = max(1.0, float(area_m))
    return base_size, base_size, "fixed_area"


def _plane_scale_for_unit_size(width: float, height: float) -> tuple[float, float]:
    return max(1.0, float(width)), max(1.0, float(height))


def _match_excluded_layer(name: str) -> str | None:
    n = (name or "").lower()
    if any(k in n for k in ["water", "lake", "river", "pond"]):
        return "water"
    if any(k in n for k in ["forest", "wood", "tree", "park"]):
        return "forests"
    if any(k in n for k in ["vegetation", "grass", "bush", "shrub"]):
        return "vegetation"
    return None


def _clip_meshes_to_scene_frame(objects) -> None:
    import bmesh
    from mathutils import Matrix

    planes = (
        ((MIN_E, 0.0, 0.0), (-1.0, 0.0, 0.0)),
        ((MAX_E, 0.0, 0.0), (1.0, 0.0, 0.0)),
        ((0.0, MIN_N, 0.0), (0.0, -1.0, 0.0)),
        ((0.0, MAX_N, 0.0), (0.0, 1.0, 0.0)),
    )
    for obj in objects:
        if getattr(obj, "type", None) != "MESH":
            continue
        for vertex in obj.data.vertices:
            vertex.co = obj.matrix_world @ vertex.co
        obj.matrix_world = Matrix.Identity(4)
        mesh = bmesh.new()
        mesh.from_mesh(obj.data)
        for plane_co, plane_no in planes:
            bmesh.ops.bisect_plane(
                mesh,
                geom=list(mesh.verts) + list(mesh.edges) + list(mesh.faces),
                plane_co=plane_co,
                plane_no=plane_no,
                clear_outer=True,
                clear_inner=False,
            )
        mesh.to_mesh(obj.data)
        mesh.free()
        obj.data.update()


def _world_bounds_xy(objects) -> tuple[float, float, float, float, float]:
    """Return min_x, max_x, min_y, max_y, min_z for objects in world space."""
    from mathutils import Vector  # type: ignore

    min_x = float("inf")
    max_x = float("-inf")
    min_y = float("inf")
    max_y = float("-inf")
    min_z = float("inf")

    for obj in objects:
        for corner in obj.bound_box:
            world_corner = obj.matrix_world @ Vector(corner)
            min_x = min(min_x, world_corner.x)
            max_x = max(max_x, world_corner.x)
            min_y = min(min_y, world_corner.y)
            max_y = max(max_y, world_corner.y)
            min_z = min(min_z, world_corner.z)

    return min_x, max_x, min_y, max_y, min_z


def _write_sionna_xml(scene_key: str, xml_path: Path, mesh_entries: list[dict]) -> None:
    """Write a Mitsuba/Sionna scene XML using NTPU-compatible ITU materials."""
    lines = [
        '<?xml version="1.0" ?>',
        '<scene version="2.1.0">',
        '    <default name="spp" value="4096"/>',
        '    <default name="resx" value="1024"/>',
        '    <default name="resy" value="768"/>',
        '    <integrator type="path">',
        '        <integer name="max_depth" value="12"/>',
        '    </integrator>',
        '    <bsdf type="twosided" id="mat-itu_concrete">',
        '        <bsdf type="diffuse">',
        '            <rgb value="0.539479 0.539479 0.53948" name="reflectance"/>',
        '        </bsdf>',
        '    </bsdf>',
        '    <bsdf type="twosided" id="mat-itu_marble">',
        '        <bsdf type="diffuse">',
        '            <rgb value="0.701101 0.644479 0.48515" name="reflectance"/>',
        '        </bsdf>',
        '    </bsdf>',
        '    <bsdf type="twosided" id="mat-itu_metal">',
        '        <bsdf type="diffuse">',
        '            <rgb value="0.219526 0.219526 0.254152" name="reflectance"/>',
        '        </bsdf>',
        '    </bsdf>',
        '    <bsdf type="twosided" id="mat-itu_wood">',
        '        <bsdf type="diffuse">',
        '            <rgb value="0.043 0.58 0.184" name="reflectance"/>',
        '        </bsdf>',
        '    </bsdf>',
        '    <bsdf type="twosided" id="mat-itu_wet_ground">',
        '        <bsdf type="diffuse">',
        '            <rgb value="0.91 0.569 0.055" name="reflectance"/>',
        '        </bsdf>',
        '    </bsdf>',
        '    <emitter type="constant" id="World">',
        '        <rgb value="1.000000 1.000000 1.000000" name="radiance"/>',
        '    </emitter>',
        '    <sensor type="perspective" id="Camera">',
        '        <string name="fov_axis" value="x"/>',
        '        <float name="fov" value="42.854885"/>',
        '        <float name="near_clip" value="0.100000"/>',
        '        <float name="far_clip" value="10000.000000"/>',
        '        <transform name="to_world">',
        '            <rotate x="1" angle="0"/>',
        '            <rotate y="1" angle="0"/>',
        '            <rotate z="1" angle="-90"/>',
        '            <translate value="0 0 100"/>',
        '        </transform>',
        '        <sampler type="independent">',
        '            <integer name="sample_count" value="$spp"/>',
        '        </sampler>',
        '        <film type="hdrfilm">',
        '            <integer name="width" value="$resx"/>',
        '            <integer name="height" value="$resy"/>',
        '        </film>',
        '    </sensor>',
    ]

    for entry in mesh_entries:
        shape_id = escape(entry["id"])
        filename = escape(entry["filename"])
        material = escape(entry["material"])
        lines.extend(
            [
                f'    <shape type="ply" id="{shape_id}">',
                f'        <string name="filename" value="{filename}"/>',
                f'        <ref id="{material}" name="bsdf"/>',
                '        <boolean name="face_normals" value="true"/>',
                '    </shape>',
            ]
        )

    lines.append("</scene>")
    xml_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args(argv):
    parser = argparse.ArgumentParser(description="Blender scene generation entry for map-picked tasks")
    parser.add_argument("--lat", type=float, required=True)
    parser.add_argument("--lon", type=float, required=True)
    parser.add_argument("--zoom", type=int, default=16)
    parser.add_argument("--area-m", type=float, default=GENERATED_SCENE_AREA_M)
    parser.add_argument("--scene-name", type=str, default="custom_scene")
    parser.add_argument("--scene-key", type=str, default="CUSTOM")
    parser.add_argument("--output-dir", type=str, required=True)
    parser.add_argument("--basemap-style", type=str, default="satellite", choices=["satellite", "osm"])
    return parser.parse_args(argv)


def main():
    args = parse_args(sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else [])
    args.area_m = GENERATED_SCENE_AREA_M
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    scene_key = args.scene_key.upper()
    bbox_min_lat, bbox_max_lat, bbox_min_lon, bbox_max_lon = _bbox_by_center_meters(args.lat, args.lon, args.area_m)

    metadata = {
        "scene_name": args.scene_name,
        "scene_key": scene_key,
        "model_url": f"/generated-scenes/{scene_key}/{scene_key}.glb",
        "lat": args.lat,
        "lon": args.lon,
        "zoom": args.zoom,
        "area_m": args.area_m,
        "bbox_mode": "fixed_meters",
        "bbox_size_m": [args.area_m, args.area_m],
        "bbox_min_lat_used": bbox_min_lat,
        "bbox_max_lat_used": bbox_max_lat,
        "bbox_min_lon_used": bbox_min_lon,
        "bbox_max_lon_used": bbox_max_lon,
        "status": "started",
        "frame": scene_frame_metadata(scene_key, args.lat, args.lon),
    }

    # This script runs inside Blender's Python runtime.
    try:
        import bpy  # type: ignore

        def _normalize_materials_for_gltf_export() -> None:
            """Convert scene materials to simple Principled setup for loader compatibility."""
            for mat in bpy.data.materials:
                if mat is None:
                    continue

                # Keep a best-effort color/texture from existing material.
                base_color = tuple(mat.diffuse_color) if hasattr(mat, "diffuse_color") else (1.0, 1.0, 1.0, 1.0)
                image_node = None

                if mat.use_nodes and mat.node_tree:
                    for node in mat.node_tree.nodes:
                        if node.type == "TEX_IMAGE" and getattr(node, "image", None) is not None:
                            image_node = node
                            break
                        if node.type == "BSDF_PRINCIPLED":
                            try:
                                c = node.inputs["Base Color"].default_value
                                base_color = (c[0], c[1], c[2], c[3])
                            except Exception:
                                pass

                mat.use_nodes = True
                nodes = mat.node_tree.nodes
                links = mat.node_tree.links
                nodes.clear()

                tex = nodes.new(type="ShaderNodeTexImage") if image_node is not None else None
                if tex is not None:
                    tex.image = image_node.image
                    tex.interpolation = "Linear"

                bsdf = nodes.new(type="ShaderNodeBsdfPrincipled")
                bsdf.inputs["Base Color"].default_value = base_color
                bsdf.inputs["Roughness"].default_value = 1.0
                out = nodes.new(type="ShaderNodeOutputMaterial")

                if tex is not None:
                    links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
                links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])

        def _mesh_count() -> int:
            return sum(1 for obj in bpy.data.objects if getattr(obj, "type", None) == "MESH")

        def _mesh_face_components(obj) -> list[list[int]]:
            mesh = obj.data
            face_indices = [poly.index for poly in mesh.polygons if len(poly.vertices) >= 3]
            if not face_indices:
                return []

            vertex_to_faces = {}
            for face_idx in face_indices:
                for vertex_idx in mesh.polygons[face_idx].vertices:
                    vertex_to_faces.setdefault(vertex_idx, set()).add(face_idx)

            remaining = set(face_indices)
            components = []
            while remaining:
                start = remaining.pop()
                stack = [start]
                component = [start]
                while stack:
                    current = stack.pop()
                    for vertex_idx in mesh.polygons[current].vertices:
                        connected = vertex_to_faces.get(vertex_idx, set())
                        for next_face in list(connected & remaining):
                            remaining.remove(next_face)
                            stack.append(next_face)
                            component.append(next_face)
                components.append(component)

            return components

        def _copy_mesh_component(src_obj, face_indices: list[int], name: str):
            mesh = src_obj.data
            vertex_map = {}
            vertices = []
            faces = []
            material_indices = []

            for face_idx in face_indices:
                poly = mesh.polygons[face_idx]
                new_face = []
                for old_idx in poly.vertices:
                    if old_idx not in vertex_map:
                        vertex_map[old_idx] = len(vertices)
                        vertices.append(tuple(mesh.vertices[old_idx].co))
                    new_face.append(vertex_map[old_idx])
                if len(new_face) >= 3:
                    faces.append(new_face)
                    material_indices.append(poly.material_index)

            if not faces:
                return None

            new_mesh = bpy.data.meshes.new(f"{name}_Mesh")
            new_mesh.from_pydata(vertices, [], faces)
            new_mesh.update()
            for mat in mesh.materials:
                new_mesh.materials.append(mat)
            for idx, material_index in enumerate(material_indices):
                if idx < len(new_mesh.polygons):
                    new_mesh.polygons[idx].material_index = material_index

            new_obj = bpy.data.objects.new(name, new_mesh)
            new_obj.matrix_world = src_obj.matrix_world.copy()
            bpy.context.collection.objects.link(new_obj)
            return new_obj

        def _building_source_objects(objects) -> list:
            sources = [
                obj for obj in objects
                if getattr(obj, "type", None) == "MESH" and "building" in getattr(obj, "name", "").lower()
            ]
            if sources:
                return sources
            return [
                obj for obj in objects
                if getattr(obj, "type", None) == "MESH" and getattr(obj, "dimensions", None) and obj.dimensions.z > 0.5
            ]

        def _split_building_objects(objects) -> list:
            buildings = []
            source_objects = _building_source_objects(objects)
            for src_obj in source_objects:
                components = _mesh_face_components(src_obj)
                for component in components:
                    building = _copy_mesh_component(src_obj, component, f"Sionna_Building_{len(buildings):04d}")
                    if building is not None:
                        buildings.append(building)
                try:
                    bpy.data.objects.remove(src_obj, do_unlink=True)
                except Exception:
                    pass
            return buildings

        def _triangulated_faces(mesh) -> list[list[int]]:
            triangles = []
            for poly in mesh.polygons:
                verts = list(poly.vertices)
                if len(verts) == 3:
                    triangles.append(verts)
                elif len(verts) > 3:
                    for idx in range(1, len(verts) - 1):
                        triangles.append([verts[0], verts[idx], verts[idx + 1]])
            return triangles

        def _export_ascii_ply(obj, ply_path: Path) -> tuple[int, int]:
            depsgraph = bpy.context.evaluated_depsgraph_get()
            eval_obj = obj.evaluated_get(depsgraph)
            mesh = eval_obj.to_mesh()
            try:
                vertices = [eval_obj.matrix_world @ vertex.co for vertex in mesh.vertices]
                faces = _triangulated_faces(mesh)
                ply_path.parent.mkdir(parents=True, exist_ok=True)
                with ply_path.open("w", encoding="ascii", newline="\n") as fh:
                    fh.write("ply\n")
                    fh.write("format ascii 1.0\n")
                    fh.write("comment Created by integrated-simworld2\n")
                    fh.write(f"element vertex {len(vertices)}\n")
                    fh.write("property float x\n")
                    fh.write("property float y\n")
                    fh.write("property float z\n")
                    fh.write(f"element face {len(faces)}\n")
                    fh.write("property list uchar uint vertex_indices\n")
                    fh.write("end_header\n")
                    for vertex in vertices:
                        fh.write(f"{vertex.x:.9g} {vertex.y:.9g} {vertex.z:.9g}\n")
                    for face in faces:
                        fh.write(f"3 {face[0]} {face[1]} {face[2]}\n")
                return len(vertices), len(faces)
            finally:
                eval_obj.to_mesh_clear()

        # Remove the default startup cube so exported scene reflects imported OSM content.
        default_cube = bpy.data.objects.get("Cube")
        if default_cube is not None:
            bpy.data.objects.remove(default_cube, do_unlink=True)

        # Save a basic blend file so the pipeline has a concrete artifact.
        blend_path = out_dir / f"{scene_key}.blend"

        # Best-effort: enable blosm addon if available.
        blosm_enabled = False
        blosm_error = None
        try:
            bpy.ops.preferences.addon_enable(module="blosm")
            blosm_enabled = True
        except Exception as exc:
            blosm_error = str(exc)

        import_result = None
        import_error = None
        basemap_error = None
        basemap_added = False
        ground_object = None
        sionna_export_error = None
        imported_mesh_objects = []
        used_min_lat = None
        used_max_lat = None
        used_min_lon = None
        used_max_lon = None
        object_count_before = len(bpy.data.objects)
        mesh_count_before = _mesh_count()
        mesh_names_before = {obj.name for obj in bpy.data.objects if getattr(obj, "type", None) == "MESH"}

        if blosm_enabled:
            try:
                prefs = bpy.context.preferences.addons["blosm"].preferences
                data_dir = out_dir / "blosm_data"
                data_dir.mkdir(parents=True, exist_ok=True)
                prefs.dataDir = str(data_dir)

                scene = bpy.context.scene
                addon = scene.blosm
                addon.commandLineMode = True
                addon.dataType = "osm"
                addon.osmSource = "server"
                # Use the base OSM 3D mode by default. "3Drealistic" requires
                # the separate blosm assets pack (building_materials.blend,
                # vegetation.blend), which is not guaranteed to be installed.
                addon.mode = "3Dsimple"

                addon.buildings = True
                addon.highways = True
                addon.railways = True
                addon.water = False
                addon.forests = False
                addon.vegetation = False
                metadata["blosm_layers"] = {
                    "buildings": True,
                    "highways": True,
                    "railways": True,
                    "water": False,
                    "forests": False,
                    "vegetation": False,
                }
                metadata["blosm_mode"] = getattr(addon, "mode", "unknown")

                server_candidates = []
                current_server = getattr(prefs, "osmServer", None)
                # Prefer faster community mirrors first.
                for fallback_server in ["private.coffee", "overpass-api.de", "vk maps"]:
                    if fallback_server not in server_candidates:
                        server_candidates.append(fallback_server)
                if current_server and current_server not in server_candidates:
                    server_candidates.append(current_server)

                attempt_errors = []
                min_lat, max_lat, min_lon, max_lon = _bbox_by_center_meters(args.lat, args.lon, args.area_m)
                addon.minLat = _clamp(min_lat, -89.0, 89.0)
                addon.maxLat = _clamp(max_lat, -89.0, 89.0)
                addon.minLon = _clamp(min_lon, -180.0, 180.0)
                addon.maxLon = _clamp(max_lon, -180.0, 180.0)
                used_min_lat = addon.minLat
                used_max_lat = addon.maxLat
                used_min_lon = addon.minLon
                used_max_lon = addon.maxLon

                for server in server_candidates:
                    try:
                        prefs.osmServer = server
                    except Exception:
                        # Keep going even if the addon version doesn't expose osmServer.
                        pass

                    try:
                        import_result = bpy.ops.blosm.import_data()
                        imported_meshes = _mesh_count() - mesh_count_before
                        if import_result and "FINISHED" in import_result and imported_meshes > 0:
                            metadata["osm_server_used"] = server
                            metadata["bbox_mode"] = "fixed_meters"
                            metadata["area_m"] = args.area_m
                            metadata["bbox_size_m"] = [args.area_m, args.area_m]
                            metadata["bbox_min_lat_used"] = used_min_lat
                            metadata["bbox_max_lat_used"] = used_max_lat
                            metadata["bbox_min_lon_used"] = used_min_lon
                            metadata["bbox_max_lon_used"] = used_max_lon
                            break
                        attempt_errors.append(
                            f"{server} (fixed_meters): returned {import_result}, imported_meshes={imported_meshes}"
                        )
                    except Exception as exc:
                        attempt_errors.append(f"{server} (fixed_meters): {exc}")

                if import_result is None:
                    import_error = " ; ".join(attempt_errors) if attempt_errors else "Unknown import failure"
                    metadata["osm_server_attempts"] = server_candidates
                else:
                    metadata["osm_server_attempts"] = server_candidates
                    if not metadata.get("osm_server_used"):
                        import_error = " ; ".join(attempt_errors) if attempt_errors else "OSM import returned FINISHED but no mesh data"

                imported_mesh_objects = [
                    obj for obj in bpy.data.objects
                    if getattr(obj, "type", None) == "MESH" and obj.name not in mesh_names_before
                ]

                # Safety cleanup: detect and remove excluded natural-water layers if addon still imported them.
                removed_excluded = {"water": 0, "forests": 0, "vegetation": 0}
                detected_excluded = {"water": 0, "forests": 0, "vegetation": 0}
                kept_meshes = []
                for obj in imported_mesh_objects:
                    excluded_key = _match_excluded_layer(getattr(obj, "name", ""))
                    if excluded_key:
                        detected_excluded[excluded_key] += 1
                        try:
                            bpy.data.objects.remove(obj, do_unlink=True)
                            removed_excluded[excluded_key] += 1
                        except Exception:
                            pass
                    else:
                        kept_meshes.append(obj)

                imported_mesh_objects = kept_meshes
                metadata["excluded_layer_detected"] = detected_excluded
                metadata["excluded_layer_removed"] = removed_excluded
                _clip_meshes_to_scene_frame(imported_mesh_objects)
            except Exception as exc:
                import_error = str(exc)

        # Add textured basemap tiles and fit them to imported geometry bounds.
        try:
            zoom = max(0, min(19, int(args.zoom)))
            center_tile_x, center_tile_y = _latlon_to_tile(args.lat, args.lon, zoom)
            default_min_lat, default_max_lat, default_min_lon, default_max_lon = _bbox_by_center_meters(
                args.lat, args.lon, args.area_m
            )
            geo_min_lat = float(metadata.get("bbox_min_lat_used", default_min_lat))
            geo_max_lat = float(metadata.get("bbox_max_lat_used", default_max_lat))
            geo_min_lon = float(metadata.get("bbox_min_lon_used", default_min_lon))
            geo_max_lon = float(metadata.get("bbox_max_lon_used", default_max_lon))

            def _download_tile(tile_x: int, tile_y: int, tile_zoom: int, tile_path: Path) -> tuple[str, str]:
                if args.basemap_style == "satellite":
                    tile_candidates = [
                        (
                            "satellite",
                            f"https://services.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{tile_zoom}/{tile_y}/{tile_x}",
                        ),
                        ("osm", f"https://tile.openstreetmap.org/{tile_zoom}/{tile_x}/{tile_y}.png"),
                    ]
                else:
                    tile_candidates = [("osm", f"https://tile.openstreetmap.org/{tile_zoom}/{tile_x}/{tile_y}.png")]

                last_exc = None
                for source, candidate_url in tile_candidates:
                    try:
                        req = urllib.request.Request(candidate_url, headers={"User-Agent": "integrated-sim-world/1.0"})
                        with urllib.request.urlopen(req, timeout=8) as resp:
                            tile_path.write_bytes(resp.read())
                        return source, candidate_url
                    except Exception as exc:
                        last_exc = exc
                raise RuntimeError(f"Failed to download basemap tile: {last_exc}")

            def _create_tile_material(mat_name: str, image_path: Path):
                mat = bpy.data.materials.new(name=mat_name)
                mat.use_nodes = True
                nodes = mat.node_tree.nodes
                links = mat.node_tree.links
                nodes.clear()

                tex_node = nodes.new(type="ShaderNodeTexImage")
                tex_node.interpolation = "Linear"
                tex_node.image = bpy.data.images.load(str(image_path), check_existing=True)

                bsdf_node = nodes.new(type="ShaderNodeBsdfPrincipled")
                bsdf_node.inputs["Roughness"].default_value = 1.0
                out_node = nodes.new(type="ShaderNodeOutputMaterial")

                links.new(tex_node.outputs["Color"], bsdf_node.inputs["Base Color"])
                links.new(bsdf_node.outputs["BSDF"], out_node.inputs["Surface"])
                return mat

            tile_infos = []
            if imported_mesh_objects:
                min_x, max_x, min_y, max_y, min_z = _world_bounds_xy(imported_mesh_objects)
                imported_width = max(1.0, max_x - min_x)
                imported_height = max(1.0, max_y - min_y)
                ground_z = min_z - 0.05

                # Build a single basemap image for the entire bbox to avoid visible tile splitting.
                # SceneFrame is centered at (0, 0); keep the basemap anchored there
                # even when imported OSM bounds are slightly asymmetric.
                world_cx = 0.0
                world_cy = 0.0
                coverage_padding = BASEMAP_COVER_PADDING
                geo_center_lat = (geo_min_lat + geo_max_lat) * 0.5
                meters_per_deg_lat, meters_per_deg_lon = _degree_to_meter_scales(geo_center_lat)
                geo_world_w = max(1.0, abs(geo_max_lon - geo_min_lon) * meters_per_deg_lon)
                geo_world_h = max(1.0, abs(geo_max_lat - geo_min_lat) * meters_per_deg_lat)
                world_w, world_h, basemap_alignment_mode = _basemap_size_for_imported_bounds(
                    args.area_m,
                    imported_width,
                    imported_height,
                )

                def _download_bbox_image(min_lon: float, min_lat: float, max_lon: float, max_lat: float, out_path: Path) -> tuple[str, str]:
                    if args.basemap_style == "satellite":
                        if zoom >= 19:
                            max_px = 2048
                        elif zoom >= 18:
                            max_px = 1536
                        else:
                            max_px = 1280

                        # Preserve geographic aspect ratio to avoid texture distortion.
                        center_lat = (min_lat + max_lat) * 0.5
                        meters_per_deg_lat, meters_per_deg_lon = _degree_to_meter_scales(center_lat)
                        bbox_w_m = max(1.0, abs(max_lon - min_lon) * meters_per_deg_lon)
                        bbox_h_m = max(1.0, abs(max_lat - min_lat) * meters_per_deg_lat)
                        if bbox_w_m >= bbox_h_m:
                            width_px = max_px
                            height_px = max(512, int(round(max_px * (bbox_h_m / bbox_w_m))))
                        else:
                            height_px = max_px
                            width_px = max(512, int(round(max_px * (bbox_w_m / bbox_h_m))))

                        export_url = (
                            "https://services.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/export"
                            f"?bbox={min_lon},{min_lat},{max_lon},{max_lat}"
                            "&bboxSR=4326"
                            "&imageSR=4326"
                            f"&size={width_px},{height_px}"
                            "&format=png32"
                            "&f=image"
                        )
                        try:
                            req = urllib.request.Request(export_url, headers={"User-Agent": "integrated-sim-world/1.0"})
                            with urllib.request.urlopen(req, timeout=12) as resp:
                                out_path.write_bytes(resp.read())
                            return "satellite_export", export_url
                        except Exception:
                            pass

                    # Fallback: single tile if export endpoint is unavailable.
                    fallback_path = out_path
                    source, fallback_url = _download_tile(center_tile_x, center_tile_y, zoom, fallback_path)
                    return source, fallback_url

                tile_path = out_dir / f"osm_basemap_bbox_{zoom}.png"
                source, tile_url = _download_bbox_image(
                    geo_min_lon,
                    geo_min_lat,
                    geo_max_lon,
                    geo_max_lat,
                    tile_path,
                )

                bpy.ops.mesh.primitive_plane_add(size=1.0, location=(world_cx, world_cy, ground_z))
                ground = bpy.context.active_object
                ground.name = "OSM_BaseMap"
                scale_x, scale_y = _plane_scale_for_unit_size(world_w, world_h)
                ground.scale = (scale_x, scale_y, 1.0)
                mat = _create_tile_material("OSM_BaseMap_Mat", tile_path)
                ground.data.materials.clear()
                ground.data.materials.append(mat)
                ground_object = ground

                basemap_added = True
                metadata["basemap_fit_mode"] = "geo_bbox_single_image"
                metadata["basemap_scale_mode"] = "fixed_meters"
                metadata["imported_bounds_xy"] = {
                    "min_x": min_x,
                    "max_x": max_x,
                    "min_y": min_y,
                    "max_y": max_y,
                    "width": imported_width,
                    "height": imported_height,
                }
                metadata["basemap_applied_size"] = [world_w, world_h]
                metadata["basemap_plane_scale"] = [scale_x, scale_y, 1.0]
                metadata["basemap_alignment_mode"] = basemap_alignment_mode
                metadata["basemap_cover_padding"] = coverage_padding
                metadata["basemap_tile_strategy"] = "single_image_bbox"
                metadata["geo_bbox_world_size"] = [geo_world_w, geo_world_h]
                metadata["generation_quality"] = "quality"
                tile_infos.append({
                    "x": center_tile_x,
                    "y": center_tile_y,
                    "zoom": zoom,
                    "source": source,
                    "url": tile_url,
                    "file": str(tile_path),
                    "geo_bounds": {
                        "min_lat": geo_min_lat,
                        "max_lat": geo_max_lat,
                        "min_lon": geo_min_lon,
                        "max_lon": geo_max_lon,
                    },
                })
            else:
                coverage_padding = BASEMAP_COVER_PADDING
                size_x = float(args.area_m)
                size_y = float(args.area_m)
                center_x = 0.0
                center_y = 0.0
                ground_z = -0.05

                tile_path = out_dir / f"osm_basemap_tile_{zoom}_{center_tile_x}_{center_tile_y}.png"
                source, tile_url = _download_tile(center_tile_x, center_tile_y, zoom, tile_path)
                bpy.ops.mesh.primitive_plane_add(size=1.0, location=(center_x, center_y, ground_z))
                ground = bpy.context.active_object
                ground.name = "OSM_BaseMap"
                scale_x, scale_y = _plane_scale_for_unit_size(size_x, size_y)
                ground.scale = (scale_x, scale_y, 1.0)
                mat = _create_tile_material("OSM_BaseMap_Mat", tile_path)
                ground.data.materials.clear()
                ground.data.materials.append(mat)
                ground_object = ground

                basemap_added = True
                metadata["basemap_fit_mode"] = "fixed_meter_fallback"
                metadata["basemap_scale_mode"] = "fixed_meters"
                metadata["basemap_cover_padding"] = coverage_padding
                metadata["basemap_applied_size"] = [size_x, size_y]
                metadata["basemap_plane_scale"] = [scale_x, scale_y, 1.0]
                tile_infos.append({
                    "x": center_tile_x,
                    "y": center_tile_y,
                    "zoom": zoom,
                    "source": source,
                    "url": tile_url,
                    "file": str(tile_path),
                })

            metadata["basemap_tile_count"] = len(tile_infos)
            metadata["basemap_size_mode"] = "fixed_meters"
            metadata["basemap_tiles"] = tile_infos
            if tile_infos:
                metadata["basemap_tile_url"] = tile_infos[0]["url"]
                metadata["basemap_tile_source"] = tile_infos[0]["source"]
                metadata["basemap_tile_zoom"] = tile_infos[0]["zoom"]
                metadata["basemap_tile_x"] = tile_infos[0]["x"]
                metadata["basemap_tile_y"] = tile_infos[0]["y"]
                metadata["basemap_tile_file"] = tile_infos[0]["file"]
        except Exception as exc:
            basemap_error = str(exc)

        if ground_object is None and imported_mesh_objects:
            try:
                for stale_ground in list(bpy.data.objects):
                    if stale_ground.name.startswith("OSM_BaseMap"):
                        bpy.data.objects.remove(stale_ground, do_unlink=True)
                min_z = _world_bounds_xy(imported_mesh_objects)[4]
                bpy.ops.mesh.primitive_plane_add(size=1.0, location=(0.0, 0.0, min_z - 0.05))
                ground = bpy.context.active_object
                ground.name = "OSM_BaseMap"
                scale_x, scale_y = _plane_scale_for_unit_size(args.area_m, args.area_m)
                ground.scale = (scale_x, scale_y, 1.0)
                material = bpy.data.materials.new(name="OSM_BaseMap_Fallback_Mat")
                material.diffuse_color = (0.12, 0.16, 0.14, 1.0)
                ground.data.materials.append(material)
                ground_object = ground
                metadata["basemap_fit_mode"] = "solid_fixed_fallback"
                metadata["basemap_scale_mode"] = "fixed_meters"
                metadata["basemap_applied_size"] = [args.area_m, args.area_m]
                metadata["basemap_plane_scale"] = [scale_x, scale_y, 1.0]
            except Exception as exc:
                basemap_error = f"{basemap_error or ''}; solid fallback failed: {exc}"

        sionna_mesh_entries = []
        building_objects = []
        try:
            mesh_dir = out_dir / "mesh"
            mesh_dir.mkdir(parents=True, exist_ok=True)

            building_objects = _split_building_objects(imported_mesh_objects)

            if ground_object is not None:
                ground_path = mesh_dir / "ground.ply"
                ground_vertices, ground_faces = _export_ascii_ply(ground_object, ground_path)
                sionna_mesh_entries.append(
                    {
                        "id": "mesh-ground",
                        "filename": "mesh/ground.ply",
                        "material": "mat-itu_wet_ground",
                        "vertices": ground_vertices,
                        "faces": ground_faces,
                    }
                )

            for idx, building in enumerate(building_objects):
                building_path = mesh_dir / f"building_{idx}.ply"
                vertex_count, face_count = _export_ascii_ply(building, building_path)
                sionna_mesh_entries.append(
                    {
                        "id": f"mesh-building_{idx}",
                        "filename": f"mesh/building_{idx}.ply",
                        "material": "mat-itu_marble",
                        "vertices": vertex_count,
                        "faces": face_count,
                    }
                )

            if ground_object is None:
                sionna_export_error = "No ground object was available for Sionna export"
            elif not building_objects:
                sionna_export_error = "No building mesh objects were available for Sionna export"
            else:
                xml_path = out_dir / f"{scene_key}.xml"
                _write_sionna_xml(scene_key, xml_path, sionna_mesh_entries)
                metadata["xml_file"] = str(xml_path)

            metadata["mesh_dir"] = str(mesh_dir)
            metadata["building_count"] = len(building_objects)
            metadata["sionna_mesh_count"] = len(sionna_mesh_entries)
            metadata["sionna_meshes"] = sionna_mesh_entries
        except Exception as exc:
            sionna_export_error = str(exc)

        object_count_after = len(bpy.data.objects)
        mesh_count_after = _mesh_count()

        # Ensure exported GLB uses a broadly supported material graph.
        _normalize_materials_for_gltf_export()
        bpy.ops.wm.save_as_mainfile(filepath=str(blend_path))

        # Export to GLB format for web viewing
        try:
            glb_path = out_dir / f"{scene_key}.glb"
            bpy.ops.export_scene.gltf(
                filepath=str(glb_path),
                export_format='GLB',
                use_selection=False,
            )
            metadata["glb_file"] = str(glb_path)
        except Exception as glb_exc:
            # GLB export is optional, don't fail the whole task
            metadata["glb_export_error"] = str(glb_exc)

        metadata["status"] = "completed"
        metadata["blend_file"] = str(blend_path)
        metadata["blosm_enabled"] = blosm_enabled
        metadata["import_result"] = list(import_result) if import_result else None
        metadata["import_error"] = import_error
        metadata["objects_before"] = object_count_before
        metadata["objects_after"] = object_count_after
        metadata["objects_imported"] = max(0, object_count_after - object_count_before)
        metadata["meshes_before"] = mesh_count_before
        metadata["meshes_after"] = mesh_count_after
        metadata["meshes_imported"] = max(0, mesh_count_after - mesh_count_before)
        metadata["basemap_added"] = basemap_added
        if basemap_error:
            metadata["basemap_error"] = basemap_error
        if sionna_export_error:
            metadata["sionna_export_error"] = sionna_export_error
        if blosm_error:
            metadata["status"] = "failed"
            metadata["blosm_error"] = blosm_error
            metadata["note"] = "Blender executed, but blosm addon is unavailable or failed to enable."
        elif import_error:
            metadata["status"] = "failed"
            metadata["note"] = "Blosm enabled, but OSM import failed."
        elif sionna_export_error:
            metadata["status"] = "failed"
            metadata["note"] = "Sionna scene export failed."
        elif import_result and "FINISHED" in import_result:
            metadata["note"] = "Blosm enabled and OSM import finished."
        else:
            metadata["status"] = "failed"
            metadata["note"] = "Blosm enabled, but OSM import did not finish."

    except Exception as exc:
        metadata["status"] = "failed"
        metadata["error"] = str(exc)
        (out_dir / "generation_error.txt").write_text(str(exc), encoding="utf-8")
        (out_dir / "scene_metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
        raise

    (out_dir / "scene_metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()

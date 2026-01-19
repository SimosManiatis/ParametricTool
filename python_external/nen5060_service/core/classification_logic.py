
import math
import rhino3dm
import trimesh
import numpy as np

# Updated relative import
from .nen5060_tables import TABEL_17_4, TABEL_17_7

# ==============================================================================
# CONFIGURATION CONSTANTS
# ==============================================================================

VERTICAL_ANGLES = [5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55, 60, 65, 70, 75, 80]
HORIZONTAL_SPREAD = 60
HORIZONTAL_STEPS = 9
WINDOW_SAMPLE_POINTS = 5
MINIMAL_OBSTRUCTION_THRESHOLD = 20.0
MIN_RAY_DISTANCE = 0.05
MAX_CONTEXT_DISTANCE = 500.0
MAX_SHADING_DISTANCE = 50.0

# ==============================================================================
# GEOMETRY UTILITIES
# ==============================================================================

def rhino_mesh_to_trimesh(mesh):
    """
    Convert a rhino3dm.Mesh to a trimesh.Trimesh object.
    """
    if mesh is None:
        return None
        
    # Extract vertices
    vertices = []
    for i in range(len(mesh.Vertices)):
        pt = mesh.Vertices[i]
        vertices.append([pt.X, pt.Y, pt.Z])
    
    # Extract faces (triangles and quads)
    faces = []
    for i in range(len(mesh.Faces)):
        face = mesh.Faces[i]
        if face.IsQuad:
            # Split quad into two triangles: A-B-C and A-C-D
            faces.append([face.A, face.B, face.C])
            faces.append([face.A, face.C, face.D])
        elif face.IsTriangle:
            faces.append([face.A, face.B, face.C])
            
    if not vertices or not faces:
        return None
        
    return trimesh.Trimesh(vertices=vertices, faces=faces)

def get_mesh_center_and_normal(mesh):
    """
    Compute center and average normal of a rhino3dm.Mesh.
    """
    if mesh is None or len(mesh.Vertices) == 0:
        return None, None, None

    # Compute normals if missing
    if len(mesh.Normals) == 0:
        mesh.Normals.ComputeNormals()
        
    # Calculate weighted average normal
    total_area = 0.0
    weighted_normal = rhino3dm.Vector3d(0, 0, 0)
    
    # We can use trimesh for area properties as it's more robust
    tm = rhino_mesh_to_trimesh(mesh)
    if tm is None:
        return None, None, None
        
    center = rhino3dm.Point3d(tm.centroid[0], tm.centroid[1], tm.centroid[2])
    
    # Trimesh face normals are already computed
    for i, face_normal in enumerate(tm.face_normals):
        area = tm.area_faces[i]
        n_vec = rhino3dm.Vector3d(face_normal[0], face_normal[1], face_normal[2])
        weighted_normal += n_vec * area
        total_area += area
        
    if total_area > 0:
        weighted_normal /= total_area
        
    weighted_normal.Unitize()
    
    bbox = mesh.GetBoundingBox()
    
    return center, weighted_normal, bbox

def vector_to_compass_orientation(normal):
    """
    Convert normal vector to compass orientation string.
    """
    angle_rad = math.atan2(normal.X, normal.Y)
    angle_deg = math.degrees(angle_rad)
    
    if angle_deg < 0:
        angle_deg += 360
        
    if angle_deg >= 337.5 or angle_deg < 22.5:
        return "Noord"
    elif angle_deg < 67.5:
        return "Noord Oost"
    elif angle_deg < 112.5:
        return "Oost"
    elif angle_deg < 157.5:
        return "Zuid Oost"
    elif angle_deg < 202.5:
        return "Zuid"
    elif angle_deg < 247.5:
        return "Zuid West"
    elif angle_deg < 292.5:
        return "West"
    else:
        return "Noord West"

def get_window_sample_points(window_bbox, window_normal):
    """
    Generate sample points with weights on window surface.
    """
    min_pt = window_bbox.Min
    max_pt = window_bbox.Max
    
    center_x = (min_pt.X + max_pt.X) / 2
    center_y = (min_pt.Y + max_pt.Y) / 2
    
    up = rhino3dm.Vector3d(0, 0, 1)
    right = rhino3dm.Vector3d.CrossProduct(window_normal, up)
    if right.Length < 0.001:
        right = rhino3dm.Vector3d(1, 0, 0)
    right.Unitize()
    
    width = max(max_pt.X - min_pt.X, max_pt.Y - min_pt.Y)
    half_width = width * 0.35
    
    z_bottom = min_pt.Z + 0.1
    z_mid = (min_pt.Z + max_pt.Z) / 2
    z_top = max_pt.Z - 0.1
    
    def pt(x, y, z):
        return rhino3dm.Point3d(x, y, z)
        
    samples = [
        (pt(center_x - right.X * half_width, center_y - right.Y * half_width, z_bottom), 1.5),
        (pt(center_x, center_y, z_bottom), 2.0),
        (pt(center_x + right.X * half_width, center_y + right.Y * half_width, z_bottom), 1.5),
        (pt(center_x, center_y, z_mid), 1.0),
        (pt(center_x, center_y, z_top), 0.5),
    ]
    return samples

# ==============================================================================
# RAY CASTING LOGIC
# ==============================================================================

def create_ray_directions(window_normal):
    """
    Generate ray directions for sky sampling.
    """
    directions = []
    
    up = rhino3dm.Vector3d(0, 0, 1)
    forward = rhino3dm.Vector3d(window_normal.X, window_normal.Y, window_normal.Z)
    forward.Unitize()
    
    right = rhino3dm.Vector3d.CrossProduct(forward, up)
    if right.Length < 0.001:
        right = rhino3dm.Vector3d(0, 1, 0)
    right.Unitize()
    
    h_angles = []
    if HORIZONTAL_STEPS > 1:
        for i in range(HORIZONTAL_STEPS):
            h = -HORIZONTAL_SPREAD + (2 * HORIZONTAL_SPREAD * i / (HORIZONTAL_STEPS - 1))
            h_angles.append(h)
    else:
        h_angles = [0]
        
    for v_angle in VERTICAL_ANGLES:
        v_rad = math.radians(v_angle)
        for h_angle in h_angles:
            h_rad = math.radians(h_angle)
            
            h_dir = forward * math.cos(h_rad) + right * math.sin(h_rad)
            h_dir.Unitize()
            
            direction = h_dir * math.cos(v_rad) + up * math.sin(v_rad)
            direction.Unitize()
            
            directions.append((direction, v_angle, h_angle))
            
    return directions

def cast_rays_for_context(sample_points, ray_directions, context_trimesh, debug_info=None):
    """
    Cast rays against context mesh using trimesh.
    """
    if context_trimesh is None or len(context_trimesh.faces) == 0:
        return 0.0
        
    sample_results = []
    total_rays_cast = 0
    total_rays_blocked = 0
    
    # Prepare batch ray casting per sample point
    # Trimesh handles batch rays efficiently
    
    for sample_pt, weight in sample_points:
        origins = []
        vectors = []
        angles = []
        
        for direction, v_angle, _ in ray_directions:
            origins.append([sample_pt.X, sample_pt.Y, sample_pt.Z])
            vectors.append([direction.X, direction.Y, direction.Z])
            angles.append(v_angle)
            
        # Cast batch
        # based on availability of embree
        intersector = trimesh.ray.ray_pyembree.RayMeshIntersector(context_trimesh) if trimesh.ray.has_embree else trimesh.ray.ray_triangle.RayMeshIntersector(context_trimesh)
        
        index_tri, index_ray, locations = intersector.intersects_id(
            ray_origins=origins,
            ray_directions=vectors,
            multiple_hits=False,
            return_locations=True
        )
        
        if len(index_ray) == 0:
             sample_results.append((0.0, weight))
             continue

        # Calculate distances to filter MIN/MAX distance
        # locations are hit points
        hit_origins = np.array(origins)[index_ray]
        hit_vectors = locations - hit_origins
        distances = np.linalg.norm(hit_vectors, axis=1)
        
        # Filter valid hits
        valid_mask = (distances >= MIN_RAY_DISTANCE) & (distances < MAX_CONTEXT_DISTANCE)
        valid_indices = index_ray[valid_mask]
        
        total_rays_cast += len(origins)
        total_rays_blocked += len(valid_indices)
        
        sample_max_angle = 0.0
        if len(valid_indices) > 0:
             # Get angles for valid hits
             hit_angles = np.array(angles)[valid_indices]
             sample_max_angle = np.max(hit_angles)
             
        sample_results.append((sample_max_angle, weight))
        
    # Aggregate results
    if not sample_results:
        return 0.0
        
    total_weight = sum(w for _, w in sample_results)
    weighted_sum = sum(angle * weight for angle, weight in sample_results)
    
    if total_weight > 0:
        weighted_avg = weighted_sum / total_weight
        absolute_max = max(angle for angle, _ in sample_results)
        final_angle = weighted_avg * 0.7 + absolute_max * 0.3
    else:
        final_angle = 0.0
        
    return final_angle

def cast_rays_for_shading(window_center, window_normal, window_bbox, shading_trimesh, debug_info=None):
    """
    Cast rays against shading mesh.
    """
    if shading_trimesh is None:
        return 90.0, 0.0
        
    window_height = window_bbox.Max.Z - window_bbox.Min.Z
    ref_point = rhino3dm.Point3d(
        (window_bbox.Min.X + window_bbox.Max.X) / 2,
        (window_bbox.Min.Y + window_bbox.Max.Y) / 2,
        window_bbox.Min.Z + 0.1
    )
    
    up = rhino3dm.Vector3d(0, 0, 1)
    forward = rhino3dm.Vector3d(window_normal.X, window_normal.Y, window_normal.Z)
    forward.Unitize()
    
    test_angles = list(range(5, 86, 5))
    origins = []
    vectors = []
    
    for v_angle in test_angles:
        v_rad = math.radians(v_angle)
        direction = forward * math.cos(v_rad) + up * math.sin(v_rad)
        direction.Unitize()
        origins.append([ref_point.X, ref_point.Y, ref_point.Z])
        vectors.append([direction.X, direction.Y, direction.Z])
        
    intersector = trimesh.ray.ray_pyembree.RayMeshIntersector(shading_trimesh) if trimesh.ray.has_embree else trimesh.ray.ray_triangle.RayMeshIntersector(shading_trimesh)

    index_tri, index_ray, locations = intersector.intersects_id(
        ray_origins=origins,
        ray_directions=vectors,
        multiple_hits=False,
        return_locations=True
    )
    
    min_blocked_angle = 90.0
    hit_distance = 0.0
    
    if len(index_ray) > 0:
        hit_origins = np.array(origins)[index_ray]
        hit_vectors = locations - hit_origins
        distances = np.linalg.norm(hit_vectors, axis=1)
        
        # Iterate through hits to find min angle
        for i, idx in enumerate(index_ray):
            dist = distances[i]
            if dist >= MIN_RAY_DISTANCE and dist < MAX_SHADING_DISTANCE:
                angle = test_angles[idx]
                if angle < min_blocked_angle:
                    min_blocked_angle = angle
                    hit_distance = dist
                    
    if min_blocked_angle < 90.0:
        projection_depth = hit_distance * math.cos(math.radians(min_blocked_angle))
        ho_ratio = projection_depth / window_height if window_height > 0 else 0.0
    else:
        ho_ratio = 0.0
        
    return min_blocked_angle, ho_ratio

# ==============================================================================
# CLASSIFICATION + HELPERS
# ==============================================================================

def get_ho_category(ho_ratio):
    if ho_ratio < 0.5: return "<0.5"
    elif ho_ratio < 1.0: return "0.5-1.0"
    else: return ">=1.0"

def angle_to_ho_ratio_approximation(angle_degrees):
    if angle_degrees <= 0: return 0.0
    if angle_degrees >= 89: return 2.0
    return math.tan(math.radians(angle_degrees))

def lookup_fsh_factor(classification, orientation, month, ho_ratio):
    if orientation == "Zuid West":
        f1 = lookup_fsh_factor(classification, "Zuid", month, ho_ratio)
        f2 = lookup_fsh_factor(classification, "West", month, ho_ratio)
        return (f1 + f2) / 2.0
        
    if classification == "Minimale Belemmering":
        return TABEL_17_4.get(month, {}).get(orientation, 1.0)
    else:
        cat = get_ho_category(ho_ratio)
        return TABEL_17_7.get(month, {}).get(orientation, {}).get(cat, 1.0)

def classify_window_logic(window_mesh, shading_mesh, context_meshes, month, debug_mode=False):
    debug_lines = []
    
    # 1. Properties
    w_center, w_normal, w_bbox = get_mesh_center_and_normal(window_mesh)
    if w_center is None:
        return {"error": "Invalid window mesh"}
        
    orientation = vector_to_compass_orientation(w_normal)
    
    # 2. Ray setup
    ray_directions = create_ray_directions(w_normal)
    sample_points = get_window_sample_points(w_bbox, w_normal)
    
    # 3. Context Analysis
    # Combine context meshes into one trimesh
    context_trimeshes = []
    if context_meshes:
        for m in context_meshes:
            tm = rhino_mesh_to_trimesh(m)
            if tm: context_trimeshes.append(tm)
            
    combined_context = None
    if context_trimeshes:
        combined_context = trimesh.util.concatenate(context_trimeshes)
        
    ctx_angle = cast_rays_for_context(sample_points, ray_directions, combined_context)
    
    # 4. Shading Analysis
    shading_trimesh = rhino_mesh_to_trimesh(shading_mesh) if shading_mesh else None
    shd_angle, shd_ho = cast_rays_for_shading(w_center, w_normal, w_bbox, shading_trimesh)
    
    # 5. Decision
    ctx_blocked = ctx_angle
    shd_blocked = 90.0 - shd_angle
    
    ctx_sig = ctx_blocked > MINIMAL_OBSTRUCTION_THRESHOLD
    shd_sig = shd_blocked > MINIMAL_OBSTRUCTION_THRESHOLD and shading_trimesh is not None
    
    if not ctx_sig and not shd_sig:
        classification = "Minimale Belemmering"
        final_ho = 0.0
        dominant = "Neither"
    elif shd_sig and (not ctx_sig or shd_blocked >= ctx_blocked):
        classification = "Overstek"
        final_ho = shd_ho
        dominant = "Shading"
    else:
        classification = "Belemmering"
        final_ho = angle_to_ho_ratio_approximation(ctx_angle)
        dominant = "Context"
        
    # 6. Lookup
    fsh = lookup_fsh_factor(classification, orientation, month, final_ho)
    
    return {
        "classification": classification,
        "fsh_factor": round(fsh, 3),
        "orientation": orientation,
        "ho_ratio": round(final_ho, 3),
        "context_angle": round(ctx_angle, 1),
        "shading_angle": round(shd_angle, 1),
        "dominant_factor": dominant
    }

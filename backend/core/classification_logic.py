
import math
import rhino3dm
import trimesh
import numpy as np

# Updated relative import
from .nen5060_tables import (
    TABEL_17_4, TABEL_17_7, TABEL_17_8, 
    TABEL_17_5, TABEL_17_6, TABEL_17_9
)

# ==============================================================================
# CONFIGURATION CONSTANTS
# ==============================================================================

VERTICAL_ANGLES = [5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55, 60, 65, 70, 75, 80]
HORIZONTAL_SPREAD = 60
HORIZONTAL_STEPS = 9
WINDOW_SAMPLE_POINTS = 5
CONTEXT_THRESHOLD = 20.0    # Obstruction significant if > 20 deg
OVERHANG_THRESHOLD = 45.0   # Overhang significant if < 45 deg (from horizon)
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
        if i == 0:
            print(f"[DEBUG] Face Type: {type(face)}")
            print(f"[DEBUG] Face Data: {face}")
        
        # Handle object-based faces (some rhino3dm versions)
        if hasattr(face, "IsQuad"):
            if face.IsQuad:
                # Split quad into two triangles: A-B-C and A-C-D
                faces.append([face.A, face.B, face.C])
                faces.append([face.A, face.C, face.D])
            elif face.IsTriangle:
                faces.append([face.A, face.B, face.C])
        
        # Handle tuple-based faces (current portable python rhino3dm)
        # Format is (A, B, C, D)
        elif isinstance(face, tuple) or isinstance(face, list):
            if len(face) >= 4:
                # If C == D, it's a triangle
                if face[2] == face[3]:
                    faces.append([face[0], face[1], face[2]])
                else:
                    # Quad -> split into two triangles
                    faces.append([face[0], face[1], face[2]])
                    faces.append([face[0], face[2], face[3]])
            elif len(face) == 3:
                 faces.append([face[0], face[1], face[2]])
            
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
    # Store accumulated normal as list [x, y, z] to avoid Vector3d math issues
    acc_normal = [0.0, 0.0, 0.0]
    
    # We can use trimesh for area properties as it's more robust
    tm = rhino_mesh_to_trimesh(mesh)
    if tm is None:
        return None, None, None
        
    center = rhino3dm.Point3d(tm.centroid[0], tm.centroid[1], tm.centroid[2])
    
    # Trimesh face normals are already computed
    for i, face_normal in enumerate(tm.face_normals):
        area = tm.area_faces[i]
        # face_normal is a numpy array or list
        nx, ny, nz = face_normal[0], face_normal[1], face_normal[2]
        
        acc_normal[0] += nx * area
        acc_normal[1] += ny * area
        acc_normal[2] += nz * area
        
        total_area += area
        
    weighted_normal = rhino3dm.Vector3d(0, 0, 0)
    if total_area > 0:
        # Create final vector manually
        weighted_normal = rhino3dm.Vector3d(
            acc_normal[0] / total_area,
            acc_normal[1] / total_area,
            acc_normal[2] / total_area
        )
        
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
    # Check length using method call
    if right.Length() < 0.001:
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
    if right.Length() < 0.001:
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
            
            # h_dir = forward * cos(h) + right * sin(h)
            ch = math.cos(h_rad)
            sh = math.sin(h_rad)
            hx = forward.X * ch + right.X * sh
            hy = forward.Y * ch + right.Y * sh
            hz = forward.Z * ch + right.Z * sh
            
            # Normalize h_dir manually or use Vector3d constructor + Unitize
            h_dir = rhino3dm.Vector3d(hx, hy, hz)
            h_dir.Unitize()
            
            # direction = h_dir * cos(v) + up * sin(v)
            cv = math.cos(v_rad)
            sv = math.sin(v_rad)
            dx = h_dir.X * cv + up.X * sv
            dy = h_dir.Y * cv + up.Y * sv
            dz = h_dir.Z * cv + up.Z * sv
            
            direction = rhino3dm.Vector3d(dx, dy, dz)
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
    Cast rays against shading mesh. Finds the BOTTOM edge of the overhang (Max Zenith Angle).
    """
    if shading_trimesh is None or len(shading_trimesh.faces) == 0:
        return 0.0, 0.0 # Clear sky (0 deg blockage from zenith)
        
    window_height = window_bbox.Max.Z - window_bbox.Min.Z
    
    # Reference point at top of window ?? 
    # Standard says: "middle of receiving surface" for ho calculation (Fig 17.4)
    # BUT projection distance is horizontal.
    # Let's use Center for ray origin.
    ref_point = window_center
    
    # We also need top/bottom of window to handle "projected depth" relative to window height?
    # Actually ho = tan(alpha). We can just use the Angle directly.
    # ho_ratio = tan(alpha_elevation).
    
    up = rhino3dm.Vector3d(0, 0, 1)
    forward = rhino3dm.Vector3d(window_normal.X, window_normal.Y, window_normal.Z)
    forward.Unitize()
    
    # We test angles from Zenith (5) down to Horizon (85).
    # We want to find the LARGEST angle that is blocked. (The bottom edge of the overhang).
    test_angles = list(range(5, 86, 5)) 
    origins = []
    vectors = []
    
    for v_angle in test_angles:
        v_rad = math.radians(v_angle)
        # direction = forward * cos(v_from_horizon) ... wait. 
        # v_angle here is from Zenith? Or Horizon?
        # In `create_ray_directions` we treated VERTICAL_ANGLES (5..80) as elevation?
        # Let's check `create_ray_directions` logic (Lines 233).
        # direction = h_dir * cos(v) + up * sin(v). 
        # sin(0) = 0 -> h_dir. This means v=0 is Horizon.
        # sin(90) = 1 -> up. This means v=90 is Zenith.
        #
        # So `VERTICAL_ANGLES` [5..80] are ELEVATION angles (from Horizon).
        #
        # If we use the same logic here:
        # We want to find the LOWEST elevation that is blocked.
        # i.e. MINIMUM elevation angle.
        #
        pass

    # RE-IMPLEMENTING LOGIC FROM SCRATCH TO BE SURE
    # Scan from Zenith (90 deg elev) down to Horizon (0 deg elev).
    # Ray 0: Elevation 85
    # Ray 1: Elevation 80 ...
    
    check_elevations = list(range(85, 4, -5)) # 85, 80 ... 5
    
    for elev in check_elevations:
        v_rad = math.radians(elev)
        # Construct vector for this elevation, straight forward (no horizontal spread for shading?)
        # Standard implies checking profile. Straight forward is best for "Section" view.
        
        cv = math.cos(v_rad) # Horizontal component
        sv = math.sin(v_rad) # Vertical component
        
        dx = forward.X * cv + up.X * 0 # No up component in forward? Wait. forward is horizontal?
        # forward is Normal. If Normal is horizontal (vertical window).
        # We assume vertical window for this logic.
        
        vx = forward.X * cv
        vy = forward.Y * cv
        vz = forward.Z * cv + sv # Add vertical Z component
        
        # This math assumes forward.Z is 0 (Vertical window). 
        # If Window is tilted, this is complex. But let's assume vertical wall.
        
        direction = rhino3dm.Vector3d(vx, vy, vz)
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
    
    # We want to find the LOWEST elevation that hit.
    # index_ray maps back to `check_elevations`.
    # check_elevations is [85, 80 ... 5].
    # Low index = High Elevation.
    # High index = Low Elevation.
    # We want MAX index that hit.
    
    min_blocked_elevation = 90.0 # Default: Sky open
    
    if len(index_ray) > 0:
        # Find the ray with the LOWEST elevation (furthest down the list)
        max_idx = np.max(index_ray)
        min_blocked_elevation = check_elevations[max_idx]
        
    # Standard: αo = Elevation.
    # If calculate ho: ho = tan(alpha).
    
    shd_angle_from_zenith = 90.0 - min_blocked_elevation
    
    # Calculate ho ratio
    # If blocked at 45 deg -> ho = 1.0.
    # If blocked at 20 deg -> ho = 0.36.
    ho_ratio = math.tan(math.radians(min_blocked_elevation))
        
    # Return:
    # 1. Angle from Zenith (compatible with main logic expectation `shd_angle`)
    #    Main logic does: `shd_blocked = 90 - shd_angle`.
    #    So we should return `shd_angle_from_zenith`.
    # 2. ho_ratio
    
    return shd_angle_from_zenith, ho_ratio

# ==============================================================================
# CONTEXT FILTERING
# ==============================================================================

def filter_context_for_window(context_data, window_center, window_normal, window_bbox):
    """
    Filter context geometry based on visibility from window.
    context_data: List of (trimesh_mesh, rhino_bbox, original_index)
    """
    if not context_data:
        return []
        
    relevant = []
    window_bottom_z = window_bbox.Min.Z
    
    # Pre-calc expensive vector math if possible, but loop is fine for <1000 items
    
    for item in context_data:
        tm_mesh, bbox, idx = item
        
        # Center of bbox - Calculate manually to avoid Point3d issues
        cx = (bbox.Min.X + bbox.Max.X) / 2.0
        cy = (bbox.Min.Y + bbox.Max.Y) / 2.0
        cz = (bbox.Min.Z + bbox.Max.Z) / 2.0
        
        # Vector from window center to bbox center (X/Y only)
        to_geo_x = cx - window_center.X
        to_geo_y = cy - window_center.Y
        # (Z not used for dot product in user script: "Using only X and Y components")
        
        # Dot product with normal (X/Y)
        dot = to_geo_x * window_normal.X + to_geo_y * window_normal.Y
        
        # Tolerance: half diagonal of the bbox
        # Manual vector because Point3d - Point3d might fail in some rhino3dm versions
        diag_x = bbox.Max.X - bbox.Min.X
        diag_y = bbox.Max.Y - bbox.Min.Y
        diag_z = bbox.Max.Z - bbox.Min.Z
        
        diag_len = math.sqrt(diag_x*diag_x + diag_y*diag_y + diag_z*diag_z)
        half_diagonal = diag_len * 0.5
        
        if dot < -half_diagonal:
            continue
            
        # Horizontal distance check
        dist_sq = to_geo_x*to_geo_x + to_geo_y*to_geo_y
        if dist_sq > (MAX_CONTEXT_DISTANCE * MAX_CONTEXT_DISTANCE):
            continue
            
        # Vertical check: Must have top above window bottom
        if bbox.Max.Z < window_bottom_z:
            continue
            
        relevant.append(item)
        
    return relevant

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

def lookup_fsh_factor(classification, orientation, month, ho_ratio, calc_type="H"):
    # Handling for Zuid West is now native in tables, but fallback if missing?
    # Tables are updated, so direct lookup should work.
    
    # 1. Select Table Set based on Calc Type
    tables = {}
    if calc_type == "H": # Heating (Default)
        tables = {
            "Minimale Belemmering": TABEL_17_4,
            "Overstek": TABEL_17_8,
            "Belemmering": TABEL_17_7
        }
    elif calc_type == "C": # Cooling
        tables = {
            "Minimale Belemmering": TABEL_17_5,
            "Overstek": TABEL_17_9,
            "Belemmering": TABEL_17_5 # Fallback to 1.0 per standard logic for non-overhangs
        }
    elif calc_type == "P": # Solar/PV
        tables = {
            "Minimale Belemmering": TABEL_17_6,
            "Overstek": TABEL_17_6, # Not available -> 1.0
            "Belemmering": TABEL_17_6 # Not available -> 1.0
        }
    else:
        # Fallback to Heating
        tables = {
            "Minimale Belemmering": TABEL_17_4,
            "Overstek": TABEL_17_8,
            "Belemmering": TABEL_17_7
        }
        
    selected_table = tables.get(classification, tables["Belemmering"])
    
    # 2. Lookup
    if classification == "Minimale Belemmering":
        val = selected_table.get(month, {}).get(orientation, 1.0)
        return val
    else:
        # Overstek or Belemmering use ho categories
        cat = get_ho_category(ho_ratio)
        val = selected_table.get(month, {}).get(orientation, {}).get(cat, 1.0)
        return val

# ==============================================================================
# MAIN LOGIC
# ==============================================================================

def classify_window_logic(window_mesh, shading_mesh, context_data, month, window_index=0, debug_mode=True, calc_type="H"):
    """
    Analyze a single window using NEN 5060 logic.
    """
    
    # 1. Properties
    w_center, w_normal, w_bbox = get_mesh_center_and_normal(window_mesh)
    if w_center is None:
        return {
            "classification": "Error",
            "fsh_factor": 1.0, "orientation": "Unknown", "ho_ratio": 0.0,
            "context_angle": 0.0, "shading_angle": 90.0, "context_blocked": 0.0, "shading_blocked": 0.0,
            "dominant_factor": "Error", "debug_info": "ERROR: Invalid Window Mesh"
        }
        
    # window_height = w_bbox.Max.Z - w_bbox.Min.Z
    orientation = vector_to_compass_orientation(w_normal)
    
    # 2. Ray setup (Context)
    ray_directions = create_ray_directions(w_normal)
    sample_points = get_window_sample_points(w_bbox, w_normal)
    
    # 3. Context Analysis
    relevant_context = filter_context_for_window(context_data, w_center, w_normal, w_bbox)
    combined_context = None
    if relevant_context:
        meshes = [item[0] for item in relevant_context]
        if meshes:
             combined_context = trimesh.util.concatenate(meshes)
             
    ctx_angle = cast_rays_for_context(sample_points, ray_directions, combined_context)

    # 4. Shading Analysis
    shading_trimesh = rhino_mesh_to_trimesh(shading_mesh) if shading_mesh else None
    shd_angle_from_zenith, shd_ho = cast_rays_for_shading(w_center, w_normal, w_bbox, shading_trimesh)
    
    # 5. Decision
    # ctx_angle is "Angle from Zenith to TOP of obstruction" ? NO.
    # Based on cast_rays_for_context (0.0 default), ctx_angle is ELEVATION of obstruction.
    # ctx_blocked = Elevation of obstruction.
    ctx_blocked = ctx_angle 
    
    # shd_angle_from_zenith is "Angle from Zenith to BOTTOM of overhang".
    # shd_blocked = Elevation of overhang bottom.
    shd_blocked = 90.0 - shd_angle_from_zenith
    
    # Thresholds
    # Context: If Obstruction rises ABOVE 20 deg elevation -> Significant
    ctx_sig = ctx_blocked > CONTEXT_THRESHOLD
    
    # Shading: If Overhang dips BELOW 45 deg elevation -> Significant
    # But only if an overhang actually exists (shd_blocked < 90/89?)
    # If clear sky -> shd_blocked = 90. 90 !< 45. Minimal.
    has_overhang = shading_mesh is not None and shd_blocked < 89.0
    shd_sig = has_overhang and (shd_blocked < OVERHANG_THRESHOLD)
    
    classification = "Minimale Belemmering"
    final_ho = 0.0
    dominant = "Neither"

    if ctx_sig and shd_sig:
        # Both significant. Choose dominant.
        # Dominant is the one providing MORE shading.
        # Context: Higher angle = More shading.
        # Shading: Lower angle = More shading.
        # Hard to compare directly. NTA 17.3.7 suggests "Volledige Belemmering" if both present.
        # But we only support Table lookup logic for now.
        # Fallback: Compare "Blockage Impact".
        # Ctx Impact = ctx_blocked (e.g. 30 deg).
        # Shd Impact = 90 - shd_blocked (e.g. 90 - 30 = 60 deg blocked from top).
        # If Shading blocks 60 deg (down to 30), and Context blocks 30 deg (up to 30).
        # Shading is dominant.
        if (90 - shd_blocked) > ctx_blocked:
            classification = "Overstek"
            final_ho = shd_ho
            dominant = "Shading"
        else:
            classification = "Belemmering"
            final_ho = angle_to_ho_ratio_approximation(ctx_angle) # ho = tan(ctx_elevation)
            dominant = "Context"
            
    elif shd_sig:
        classification = "Overstek"
        final_ho = shd_ho
        dominant = "Shading"
    elif ctx_sig:
        classification = "Belemmering"
        final_ho = angle_to_ho_ratio_approximation(ctx_angle)
        dominant = "Context"
    else:
        classification = "Minimale Belemmering"
        final_ho = 0.0
        dominant = "Neither"
        
    # 6. Lookup
    fsh = lookup_fsh_factor(classification, orientation, month, final_ho, calc_type=calc_type)
    
    # Build COMPACT debug string
    if debug_mode:
        debug_str = (
            f"W{window_index}|{orientation}|"
            f"Ctx:{ctx_blocked:.0f}deg|Shd:{shd_blocked:.0f}deg|"
            f"{classification}|Fsh={fsh:.2f}"
        )
    else:
        debug_str = ""
    
    return {
        "classification": classification,
        "fsh_factor": round(fsh, 3),
        "orientation": orientation,
        "ho_ratio": round(final_ho, 3),
        "context_angle": round(ctx_angle, 1),
        "shading_angle": round(shd_angle_from_zenith, 1), # Return raw zenith angle for consistency with app logic if needed
        "context_blocked": round(ctx_blocked, 1),
        "shading_blocked": round(shd_blocked, 1),
        "dominant_factor": dominant,
        "debug_info": debug_str
    }


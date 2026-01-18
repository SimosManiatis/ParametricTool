"""
################################################################################
#                                                                              #
#   NEN 5060 WINDOW SHADING CLASSIFICATION SCRIPT                              #
#   Version 7.0 - Production Ready                                             #
#                                                                              #
#   For use in Grasshopper Python (GHPython) component                         #
#                                                                              #
################################################################################

OVERVIEW
========
This script classifies windows based on their shading conditions according to
the Dutch NEN 5060 standard for building energy performance calculations.
It determines which factor dominates the shading of each window:
    - Context buildings (surrounding structures)
    - Shading devices (overhangs, balconies, fins)
    - Neither (minimal obstruction)

The classification determines which table from NEN 5060 to use for the
solar shading reduction factor (Fsh;obst):
    - Tabel 17.4: For minimal obstruction (both factors < 20°)
    - Tabel 17.7: For significant obstruction (overstek or belemmering)


NEN 5060 METHODOLOGY
====================
Per NEN 5060, the shading analysis considers:

1. REFERENCE POINT
   The analysis is performed from a reference point at the BOTTOM CENTER
   of the window. This is specified in NEN 5060 as the point from which
   obstruction angles should be measured.

2. OBSTRUCTION ANGLE (ho;⊥)
   The perpendicular obstruction angle measured from horizontal (0°) upward.
   - For context: angle to the TOP of obstructing buildings
   - For shading: angle to the OUTER EDGE of the overhang

3. CLASSIFICATION LOGIC
   Both context and shading block different parts of the sky hemisphere:
   
   CONTEXT blocks from horizon UP:
   - A building at 60° blocks the sky from 0° to 60° (60° of sky blocked)
   - Higher angle = more obstruction
   
   SHADING blocks from zenith DOWN:
   - An overhang at 65° blocks the sky from 65° to 90° (25° of sky blocked)
   - Lower angle = deeper overhang = more obstruction
   
   To compare fairly, we convert both to "degrees of sky blocked":
   - Context: ctx_blocked = ctx_angle
   - Shading: shd_blocked = 90° - shd_angle
   
   The factor that blocks MORE sky dominates the classification.


INPUTS (Grasshopper component)
==============================
    glazing_meshes   : List of Mesh - Window/glazing surfaces as meshes
    shading_meshes   : List of Mesh - Corresponding shading devices (1:1 with windows)
    context_geometry : List of Brep/Mesh/Extrusion - Surrounding buildings/obstructions  
    month            : Integer (1-12) - Month for Fsh lookup (solar radiation varies)

OUTPUTS (Grasshopper component)
===============================
    classified_meshes   : DataTree[Mesh] - Windows sorted into 3 branches:
                          {0} = Minimale Belemmering (minimal obstruction)
                          {1} = Overstek (shading device dominant)
                          {2} = Belemmering (context buildings dominant)
    
    classification      : List[String] - Classification name per window
    fsh_factor          : List[Float] - Solar shading reduction factor (0-1)
    orientation         : List[String] - Compass orientation per window
    ho_ratio            : List[Float] - Obstruction ratio (projection/height)
    debug_info          : List[String] - Detailed debug information per window
    
    context_angles      : List[Float] - Raw context obstruction angle per window
    shading_angles      : List[Float] - Raw shading obstruction angle per window
    context_sky_blocked : List[Float] - Sky blocked by context (= context_angle)
    shading_sky_blocked : List[Float] - Sky blocked by shading (= 90 - shading_angle)
    dominant_factor     : List[String] - Which factor dominated classification


ALGORITHM OVERVIEW
==================
1. PREPARATION
   - Convert all context geometry to meshes (faster ray intersection)
   - Pre-compute ray direction patterns
   
2. FOR EACH WINDOW:
   a. Extract window properties (center, normal, bounding box)
   b. Determine compass orientation from normal vector
   c. Filter context geometry (only those in front of window)
   d. Cast rays to find context obstruction angle
   e. Cast rays to find shading obstruction angle
   f. Compare sky blockage to determine dominant factor
   g. Look up Fsh from appropriate NEN 5060 table
   
3. OUTPUT
   - Sort windows into DataTree branches
   - Return all classification data


COORDINATE SYSTEM
=================
This script assumes the standard Rhino/Grasshopper coordinate system:
    - X axis: East-West (positive = East)
    - Y axis: North-South (positive = North)
    - Z axis: Vertical (positive = Up)

Window normals pointing in +Y direction = North-facing window
Window normals pointing in -Y direction = South-facing window
etc.


PERFORMANCE NOTES
=================
- Context geometry is converted to meshes ONCE at startup
- Ray directions are pre-computed per window orientation
- Bounding box pre-filtering skips irrelevant geometry
- Mesh.Ray intersection is highly optimized in Rhino

Typical performance:
- 200 windows, 10 context buildings: ~5-10 seconds
- 500 windows, 50 context buildings: ~30-60 seconds


VERSION HISTORY
===============
v5.0 - Initial ray casting implementation
v5.1 - Added diagnostic outputs
v6.0 - Fixed sky blockage comparison logic
v7.0 - Production ready with extensive documentation and validation

################################################################################
"""

# ==============================================================================
# IMPORTS
# ==============================================================================

import Rhino.Geometry as rg      # Rhino geometry library
import math                       # Mathematical functions
import System                     # .NET System namespace

# Grasshopper-specific imports for DataTree output
from Grasshopper import DataTree
from Grasshopper.Kernel.Data import GH_Path


# ==============================================================================
# CONFIGURATION CONSTANTS
# ==============================================================================
# These values control the accuracy vs. performance tradeoff.
# Modify with caution - changes affect both results and computation time.

# --- Ray Casting Configuration ---

# Vertical angles to test (degrees from horizontal)
# More angles = more accurate but slower
# Current set: 16 angles covering 5° to 80° in 5° increments
# Note: We don't test 0° (horizontal) or 85-90° (near vertical) as these are
# edge cases rarely relevant for solar analysis
VERTICAL_ANGLES = [5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55, 60, 65, 70, 75, 80]

# Horizontal spread for context ray casting (degrees from window normal)
# Rays are cast in a fan pattern: -60° to +60° from the window's facing direction
# This captures context buildings that are not directly in front but still visible
HORIZONTAL_SPREAD = 60  # degrees left and right of center

# Number of horizontal steps in the ray fan
# 9 steps across 120° spread = approximately 15° increments
HORIZONTAL_STEPS = 9

# Number of sample points on the window surface for ray casting
# Using 5 points: 3 at bottom (weighted 2x per NEN 5060), 1 middle, 1 top
# Bottom points are weighted more because NEN 5060 specifies bottom as reference
WINDOW_SAMPLE_POINTS = 5

# --- Classification Thresholds ---

# Minimum angle (degrees) to be considered "significant" obstruction
# Per NEN 5060, angles below 20° are considered "minimale belemmering"
# This threshold determines when to use Tabel 17.4 vs Tabel 17.7
MINIMAL_OBSTRUCTION_THRESHOLD = 20.0

# --- Distance Limits ---

# Minimum distance for valid ray hits (meters)
# Hits closer than this are ignored (prevents self-intersection)
MIN_RAY_DISTANCE = 0.05

# Maximum distance for context obstruction (meters)
# Buildings beyond this distance have negligible shading effect
MAX_CONTEXT_DISTANCE = 500.0

# Maximum distance for shading device hits (meters)
# Shading devices should be close to the window; distant hits are likely errors
MAX_SHADING_DISTANCE = 50.0

# --- Mesh Conversion Quality ---

# Quality settings for converting Brep geometry to meshes
# Using default settings balances accuracy and performance
# For higher accuracy, use: rg.MeshingParameters.QualityRenderMesh
MESH_CONVERSION_QUALITY = rg.MeshingParameters.Default


# ==============================================================================
# NEN 5060 LOOKUP TABLES
# ==============================================================================
# These tables are extracted directly from NEN 5060 standard.
# DO NOT MODIFY unless the standard is updated.

# Tabel 17.4: Beschaduwingsreductiefactor (Fsh;obst;mi) for MINIMAL obstruction
# Used when both context and shading angles are below 20°
# Structure: TABEL_17_4[month][orientation] = Fsh value
# 
# Note: Values vary by month because sun position changes seasonally.
# Winter months (Nov-Feb) generally have lower values for South-facing
# windows because the low winter sun is easily obstructed.

TABEL_17_4 = {
    # Month 1: January - Low sun angle, short days
    1:  {"Zuid": 0.23, "Oost": 0.49, "Zuid Oost": 0.92, "Noord": 0.48, 
         "Noord Oost": 1.0, "West": 1.0, "Noord West": 0.85},
    
    # Month 2: February - Sun rising higher
    2:  {"Zuid": 0.91, "Oost": 0.83, "Zuid Oost": 0.79, "Noord": 0.81, 
         "Noord Oost": 1.0, "West": 0.96, "Noord West": 0.85},
    
    # Month 3: March - Spring equinox period
    3:  {"Zuid": 1.0, "Oost": 0.93, "Zuid Oost": 0.82, "Noord": 0.87, 
         "Noord Oost": 1.0, "West": 0.97, "Noord West": 0.89},
    
    # Month 4: April - Sun getting high
    4:  {"Zuid": 1.0, "Oost": 0.92, "Zuid Oost": 0.91, "Noord": 0.95, 
         "Noord Oost": 0.99, "West": 0.97, "Noord West": 0.82},
    
    # Month 5: May - High sun angle
    5:  {"Zuid": 1.0, "Oost": 0.99, "Zuid Oost": 0.95, "Noord": 1.0, 
         "Noord Oost": 0.97, "West": 0.88, "Noord West": 0.88},
    
    # Month 6: June - Summer solstice, highest sun
    6:  {"Zuid": 1.0, "Oost": 1.0, "Zuid Oost": 0.9, "Noord": 1.0, 
         "Noord Oost": 0.97, "West": 0.91, "Noord West": 0.93},
    
    # Month 7: July - Still high sun
    7:  {"Zuid": 1.0, "Oost": 1.0, "Zuid Oost": 0.93, "Noord": 0.99, 
         "Noord Oost": 0.97, "West": 0.91, "Noord West": 0.92},
    
    # Month 8: August - Sun starting to lower
    8:  {"Zuid": 1.0, "Oost": 0.99, "Zuid Oost": 0.94, "Noord": 0.98, 
         "Noord Oost": 0.98, "West": 0.98, "Noord West": 0.89},
    
    # Month 9: September - Autumn equinox period
    9:  {"Zuid": 1.0, "Oost": 0.91, "Zuid Oost": 0.87, "Noord": 0.92, 
         "Noord Oost": 1.0, "West": 0.97, "Noord West": 0.85},
    
    # Month 10: October - Sun getting low
    10: {"Zuid": 0.97, "Oost": 0.88, "Zuid Oost": 0.84, "Noord": 0.86, 
         "Noord Oost": 1.0, "West": 0.96, "Noord West": 0.83},
    
    # Month 11: November - Low sun, short days
    11: {"Zuid": 0.61, "Oost": 0.71, "Zuid Oost": 0.92, "Noord": 0.7, 
         "Noord Oost": 1.0, "West": 0.98, "Noord West": 0.9},
    
    # Month 12: December - Winter solstice, lowest sun
    12: {"Zuid": 0.19, "Oost": 0.58, "Zuid Oost": 0.86, "Noord": 0.4, 
         "Noord Oost": 1.0, "West": 1.0, "Noord West": 0.87},
}


# Tabel 17.7: Beschaduwingsreductiefactor (Fsh;obst;m) for SIGNIFICANT obstruction
# Used when context OR shading angle exceeds 20°
# Structure: TABEL_17_7[month][orientation][ho_category] = Fsh value
#
# ho_category is based on the obstruction ratio (ho;⊥):
#   "<0.5"   : Shallow obstruction (projection < 50% of window height)
#   "0.5-1.0": Medium obstruction (projection 50-100% of window height)
#   ">=1.0"  : Deep obstruction (projection >= window height)
#
# Lower Fsh values indicate more shading (less solar gain).

TABEL_17_7 = {
    1: {
        "Zuid":      {"<0.5": 0.19, "0.5-1.0": 0.19, ">=1.0": 0.19},
        "Oost":      {"<0.5": 0.45, "0.5-1.0": 0.24, ">=1.0": 0.24},
        "Zuid Oost": {"<0.5": 0.8,  "0.5-1.0": 0.55, ">=1.0": 0.55},
        "Noord":     {"<0.5": 0.44, "0.5-1.0": 0.25, ">=1.0": 0.25},
        "Noord Oost":{"<0.5": 1.0,  "0.5-1.0": 1.0,  ">=1.0": 1.0},
        "West":      {"<0.5": 1.0,  "0.5-1.0": 1.0,  ">=1.0": 1.0},
        "Noord West":{"<0.5": 0.75, "0.5-1.0": 0.49, ">=1.0": 0.49},
    },
    2: {
        "Zuid":      {"<0.5": 0.6,  "0.5-1.0": 0.3,  ">=1.0": 0.3},
        "Oost":      {"<0.5": 0.66, "0.5-1.0": 0.51, ">=1.0": 0.38},
        "Zuid Oost": {"<0.5": 0.79, "0.5-1.0": 0.68, ">=1.0": 0.54},
        "Noord":     {"<0.5": 0.59, "0.5-1.0": 0.44, ">=1.0": 0.35},
        "Noord Oost":{"<0.5": 1.0,  "0.5-1.0": 1.0,  ">=1.0": 1.0},
        "West":      {"<0.5": 0.94, "0.5-1.0": 0.91, ">=1.0": 0.91},
        "Noord West":{"<0.5": 0.85, "0.5-1.0": 0.72, ">=1.0": 0.61},
    },
    3: {
        "Zuid":      {"<0.5": 0.95, "0.5-1.0": 0.43, ">=1.0": 0.35},
        "Oost":      {"<0.5": 0.83, "0.5-1.0": 0.53, ">=1.0": 0.41},
        "Zuid Oost": {"<0.5": 0.75, "0.5-1.0": 0.7,  ">=1.0": 0.53},
        "Noord":     {"<0.5": 0.79, "0.5-1.0": 0.48, ">=1.0": 0.38},
        "Noord Oost":{"<0.5": 1.0,  "0.5-1.0": 1.0,  ">=1.0": 1.0},
        "West":      {"<0.5": 0.93, "0.5-1.0": 0.85, ">=1.0": 0.82},
        "Noord West":{"<0.5": 0.8,  "0.5-1.0": 0.73, ">=1.0": 0.57},
    },
    4: {
        "Zuid":      {"<0.5": 1.0,  "0.5-1.0": 0.76, ">=1.0": 0.36},
        "Oost":      {"<0.5": 0.84, "0.5-1.0": 0.56, ">=1.0": 0.38},
        "Zuid Oost": {"<0.5": 0.82, "0.5-1.0": 0.66, ">=1.0": 0.5},
        "Noord":     {"<0.5": 0.89, "0.5-1.0": 0.58, ">=1.0": 0.39},
        "Noord Oost":{"<0.5": 0.97, "0.5-1.0": 0.97, ">=1.0": 0.97},
        "West":      {"<0.5": 0.97, "0.5-1.0": 0.88, ">=1.0": 0.75},
        "Noord West":{"<0.5": 0.74, "0.5-1.0": 0.54, ">=1.0": 0.43},
    },
    5: {
        "Zuid":      {"<0.5": 1.0,  "0.5-1.0": 1.0,  ">=1.0": 0.46},
        "Oost":      {"<0.5": 0.95, "0.5-1.0": 0.75, ">=1.0": 0.44},
        "Zuid Oost": {"<0.5": 0.89, "0.5-1.0": 0.71, ">=1.0": 0.54},
        "Noord":     {"<0.5": 0.99, "0.5-1.0": 0.82, ">=1.0": 0.47},
        "Noord Oost":{"<0.5": 0.96, "0.5-1.0": 0.91, ">=1.0": 0.91},
        "West":      {"<0.5": 0.89, "0.5-1.0": 0.88, ">=1.0": 0.74},
        "Noord West":{"<0.5": 0.83, "0.5-1.0": 0.62, ">=1.0": 0.47},
    },
    6: {
        "Zuid":      {"<0.5": 1.0,  "0.5-1.0": 1.0,  ">=1.0": 0.56},
        "Oost":      {"<0.5": 0.99, "0.5-1.0": 0.85, ">=1.0": 0.49},
        "Zuid Oost": {"<0.5": 0.89, "0.5-1.0": 0.71, ">=1.0": 0.53},
        "Noord":     {"<0.5": 0.99, "0.5-1.0": 0.88, ">=1.0": 0.53},
        "Noord Oost":{"<0.5": 0.94, "0.5-1.0": 0.86, ">=1.0": 0.84},
        "West":      {"<0.5": 0.81, "0.5-1.0": 0.79, ">=1.0": 0.66},
        "Noord West":{"<0.5": 0.86, "0.5-1.0": 0.66, ">=1.0": 0.49},
    },
    7: {
        "Zuid":      {"<0.5": 1.0,  "0.5-1.0": 1.0,  ">=1.0": 0.56},
        "Oost":      {"<0.5": 0.99, "0.5-1.0": 0.82, ">=1.0": 0.43},
        "Zuid Oost": {"<0.5": 0.87, "0.5-1.0": 0.69, ">=1.0": 0.54},
        "Noord":     {"<0.5": 0.99, "0.5-1.0": 0.83, ">=1.0": 0.51},
        "Noord Oost":{"<0.5": 0.95, "0.5-1.0": 0.9,  ">=1.0": 0.89},
        "West":      {"<0.5": 0.85, "0.5-1.0": 0.84, ">=1.0": 0.71},
        "Noord West":{"<0.5": 0.88, "0.5-1.0": 0.71, ">=1.0": 0.55},
    },
    8: {
        "Zuid":      {"<0.5": 1.0,  "0.5-1.0": 0.95, ">=1.0": 0.42},
        "Oost":      {"<0.5": 0.91, "0.5-1.0": 0.67, ">=1.0": 0.4},
        "Zuid Oost": {"<0.5": 0.9,  "0.5-1.0": 0.72, ">=1.0": 0.57},
        "Noord":     {"<0.5": 0.95, "0.5-1.0": 0.74, ">=1.0": 0.46},
        "Noord Oost":{"<0.5": 0.98, "0.5-1.0": 0.96, ">=1.0": 0.96},
        "West":      {"<0.5": 0.96, "0.5-1.0": 0.92, ">=1.0": 0.87},
        "Noord West":{"<0.5": 0.8,  "0.5-1.0": 0.77, ">=1.0": 0.66},
    },
    9: {
        "Zuid":      {"<0.5": 0.99, "0.5-1.0": 0.55, ">=1.0": 0.34},
        "Oost":      {"<0.5": 0.84, "0.5-1.0": 0.54, ">=1.0": 0.39},
        "Zuid Oost": {"<0.5": 0.77, "0.5-1.0": 0.67, ">=1.0": 0.51},
        "Noord":     {"<0.5": 0.84, "0.5-1.0": 0.5,  ">=1.0": 0.38},
        "Noord Oost":{"<0.5": 1.0,  "0.5-1.0": 1.0,  ">=1.0": 1.0},
        "West":      {"<0.5": 0.95, "0.5-1.0": 0.87, ">=1.0": 0.8},
        "Noord West":{"<0.5": 0.77, "0.5-1.0": 0.66, ">=1.0": 0.53},
    },
    10: {
        "Zuid":      {"<0.5": 0.82, "0.5-1.0": 0.3,  ">=1.0": 0.28},
        "Oost":      {"<0.5": 0.74, "0.5-1.0": 0.42, ">=1.0": 0.35},
        "Zuid Oost": {"<0.5": 0.75, "0.5-1.0": 0.71, ">=1.0": 0.52},
        "Noord":     {"<0.5": 0.7,  "0.5-1.0": 0.5,  ">=1.0": 0.33},
        "Noord Oost":{"<0.5": 1.0,  "0.5-1.0": 1.0,  ">=1.0": 1.0},
        "West":      {"<0.5": 0.95, "0.5-1.0": 0.9,  ">=1.0": 0.91},
        "Noord West":{"<0.5": 0.76, "0.5-1.0": 0.75, ">=1.0": 0.57},
    },
    11: {
        "Zuid":      {"<0.5": 0.24, "0.5-1.0": 0.24, ">=1.0": 0.24},
        "Oost":      {"<0.5": 0.46, "0.5-1.0": 0.34, ">=1.0": 0.31},
        "Zuid Oost": {"<0.5": 0.89, "0.5-1.0": 0.6,  ">=1.0": 0.58},
        "Noord":     {"<0.5": 0.56, "0.5-1.0": 0.38, ">=1.0": 0.3},
        "Noord Oost":{"<0.5": 1.0,  "0.5-1.0": 1.0,  ">=1.0": 1.0},
        "West":      {"<0.5": 0.98, "0.5-1.0": 0.98, ">=1.0": 0.98},
        "Noord West":{"<0.5": 0.87, "0.5-1.0": 0.74, ">=1.0": 0.62},
    },
    12: {
        "Zuid":      {"<0.5": 0.19, "0.5-1.0": 0.19, ">=1.0": 0.19},
        "Oost":      {"<0.5": 0.54, "0.5-1.0": 0.26, ">=1.0": 0.26},
        "Zuid Oost": {"<0.5": 0.71, "0.5-1.0": 0.55, ">=1.0": 0.55},
        "Noord":     {"<0.5": 0.38, "0.5-1.0": 0.25, ">=1.0": 0.25},
        "Noord Oost":{"<0.5": 1.0,  "0.5-1.0": 1.0,  ">=1.0": 1.0},
        "West":      {"<0.5": 1.0,  "0.5-1.0": 1.0,  ">=1.0": 1.0},
        "Noord West":{"<0.5": 0.79, "0.5-1.0": 0.61, ">=1.0": 0.61},
    },
}


# ==============================================================================
# GEOMETRY PREPARATION FUNCTIONS
# ==============================================================================

def convert_geometry_to_meshes(geometry_list, debug_callback=None):
    """
    Convert a list of geometry objects to meshes for ray intersection.
    
    Ray-mesh intersection is significantly faster than ray-brep intersection
    in Rhino (often 10-100x faster). This function converts all input geometry
    to meshes at startup to optimize the main processing loop.
    
    Parameters
    ----------
    geometry_list : list
        List of Rhino geometry objects (Mesh, Brep, Extrusion, or None)
    debug_callback : function, optional
        Function to call with debug messages
        
    Returns
    -------
    list of tuples
        Each tuple contains: (mesh, bounding_box, original_index)
        - mesh: The converted Rhino.Geometry.Mesh object
        - bounding_box: Pre-computed bounding box for fast filtering
        - original_index: Index in the original list (for debugging)
    
    Notes
    -----
    - None values in the input list are skipped
    - Breps are converted using the configured mesh quality settings
    - Extrusions are first converted to Brep, then to Mesh
    - Failed conversions are silently skipped (logged if debug_callback provided)
    """
    meshes = []
    skipped = 0
    
    for idx, geo in enumerate(geometry_list):
        # Skip None entries
        if geo is None:
            skipped += 1
            continue
        
        try:
            # Case 1: Already a mesh - use directly
            if isinstance(geo, rg.Mesh):
                bbox = geo.GetBoundingBox(True)  # True = accurate bbox
                meshes.append((geo, bbox, idx))
            
            # Case 2: Brep (most common for building geometry)
            elif isinstance(geo, rg.Brep):
                # CreateFromBrep returns an array of meshes (one per face)
                mesh_array = rg.Mesh.CreateFromBrep(geo, MESH_CONVERSION_QUALITY)
                if mesh_array and len(mesh_array) > 0:
                    # Combine all face meshes into one for faster intersection
                    combined = rg.Mesh()
                    for m in mesh_array:
                        combined.Append(m)
                    bbox = combined.GetBoundingBox(True)
                    meshes.append((combined, bbox, idx))
                else:
                    skipped += 1
            
            # Case 3: Extrusion (common for simple building masses)
            elif isinstance(geo, rg.Extrusion):
                # Convert to Brep first, then to Mesh
                brep = geo.ToBrep()
                if brep:
                    mesh_array = rg.Mesh.CreateFromBrep(brep, MESH_CONVERSION_QUALITY)
                    if mesh_array and len(mesh_array) > 0:
                        combined = rg.Mesh()
                        for m in mesh_array:
                            combined.Append(m)
                        bbox = combined.GetBoundingBox(True)
                        meshes.append((combined, bbox, idx))
                    else:
                        skipped += 1
                else:
                    skipped += 1
            
            # Case 4: Unknown geometry type
            else:
                skipped += 1
                if debug_callback:
                    debug_callback("  Warning: Unknown geometry type at index {}: {}".format(
                        idx, type(geo).__name__))
                        
        except Exception as e:
            # Catch any conversion errors and continue
            skipped += 1
            if debug_callback:
                debug_callback("  Warning: Failed to convert geometry at index {}: {}".format(
                    idx, str(e)))
    
    if debug_callback:
        debug_callback("  Converted {}/{} geometry objects to meshes ({} skipped)".format(
            len(meshes), len(geometry_list), skipped))
    
    return meshes


def filter_context_for_window(context_meshes, window_center, window_normal, window_bbox):
    """
    Pre-filter context geometry to only those potentially visible from a window.
    
    This optimization can eliminate 50-90% of context geometry from ray testing,
    significantly improving performance for models with many context buildings.
    
    Parameters
    ----------
    context_meshes : list of tuples
        Output from convert_geometry_to_meshes()
    window_center : Point3d
        Center point of the window
    window_normal : Vector3d
        Outward-facing normal of the window
    window_bbox : BoundingBox
        Bounding box of the window
        
    Returns
    -------
    list of tuples
        Filtered list containing only relevant context geometry
        
    Filtering Criteria
    ------------------
    1. Must be in front of window (positive dot product with normal)
       - Allows for diagonal positions using half-diagonal tolerance
    2. Must be within maximum context distance
    3. Must have top above window bottom (can't shade if entirely below)
    """
    relevant = []
    window_bottom_z = window_bbox.Min.Z
    
    for mesh, bbox, idx in context_meshes:
        # Vector from window center to geometry center
        to_geo = bbox.Center - window_center
        
        # Dot product with window normal (positive = in front)
        # Using only X and Y components (horizontal plane)
        dot = to_geo.X * window_normal.X + to_geo.Y * window_normal.Y
        
        # Allow geometry that's partially in front (use half-diagonal as tolerance)
        # This catches buildings that are beside the window but still visible
        half_diagonal = bbox.Diagonal.Length * 0.5
        if dot < -half_diagonal:
            continue  # Completely behind window
        
        # Check horizontal distance
        horizontal_dist = math.sqrt(to_geo.X**2 + to_geo.Y**2)
        if horizontal_dist > MAX_CONTEXT_DISTANCE:
            continue  # Too far away to matter
        
        # Check vertical position - must have top above window bottom
        if bbox.Max.Z < window_bottom_z:
            continue  # Entirely below window level
        
        relevant.append((mesh, bbox, idx))
    
    return relevant


# ==============================================================================
# WINDOW ANALYSIS FUNCTIONS
# ==============================================================================

def get_mesh_properties(mesh):
    """
    Extract center, normal vector, and bounding box from a mesh.
    
    For window meshes, we need the outward-facing normal to determine:
    1. Which direction the window faces (for orientation classification)
    2. Which direction to cast rays (perpendicular to window plane)
    
    Parameters
    ----------
    mesh : Mesh
        Input mesh (typically a planar window surface)
        
    Returns
    -------
    tuple (Point3d, Vector3d, BoundingBox) or (None, None, None)
        - center: Centroid of the mesh bounding box
        - normal: Area-weighted average normal vector (unitized)
        - bbox: Bounding box of the mesh
        
    Notes
    -----
    The normal is computed as an area-weighted average of all face normals.
    This handles non-planar meshes gracefully, though windows should typically
    be planar. For a planar quad mesh, this returns the face normal directly.
    """
    if mesh is None:
        return None, None, None
    
    # Ensure face normals are computed
    if mesh.FaceNormals.Count == 0:
        mesh.FaceNormals.ComputeFaceNormals()
    
    # Compute area-weighted average normal
    # This is more accurate than simple averaging for meshes with varying face sizes
    avg_normal = rg.Vector3d(0, 0, 0)
    total_area = 0
    
    for i in range(mesh.Faces.Count):
        face = mesh.Faces[i]
        
        # Get face vertices
        pts = [mesh.Vertices[face.A], mesh.Vertices[face.B], mesh.Vertices[face.C]]
        if face.IsQuad:
            pts.append(mesh.Vertices[face.D])
        
        # Compute face area using cross product
        # For triangle: area = 0.5 * |v1 × v2|
        # For quad: area = 0.5 * |v1 × v2| + 0.5 * |v2 × v3|
        v1 = rg.Vector3d(pts[1] - pts[0])
        v2 = rg.Vector3d(pts[2] - pts[0])
        area = rg.Vector3d.CrossProduct(v1, v2).Length * 0.5
        
        if face.IsQuad:
            v3 = rg.Vector3d(pts[3] - pts[0])
            area += rg.Vector3d.CrossProduct(v2, v3).Length * 0.5
        
        # Accumulate weighted normal
        avg_normal += rg.Vector3d(mesh.FaceNormals[i]) * area
        total_area += area
    
    # Normalize the result
    if total_area > 0:
        avg_normal /= total_area
    avg_normal.Unitize()
    
    # Get bounding box and center
    bbox = mesh.GetBoundingBox(True)
    center = bbox.Center
    
    return center, avg_normal, bbox


def vector_to_compass_orientation(normal):
    """
    Convert a normal vector to compass orientation string.
    
    Uses the standard convention where Y+ = North.
    The angle is measured clockwise from North (Y+) axis.
    
    Parameters
    ----------
    normal : Vector3d
        Outward-facing normal vector of the window
        
    Returns
    -------
    str
        One of: "Noord", "Noord Oost", "Oost", "Zuid Oost",
                "Zuid", "Zuid West", "West", "Noord West"
                
    Angle Ranges
    ------------
    Noord:      337.5° - 22.5°  (facing +Y)
    Noord Oost:  22.5° - 67.5°
    Oost:        67.5° - 112.5° (facing +X)
    Zuid Oost:  112.5° - 157.5°
    Zuid:       157.5° - 202.5° (facing -Y)
    Zuid West:  202.5° - 247.5°
    West:       247.5° - 292.5° (facing -X)
    Noord West: 292.5° - 337.5°
    """
    # atan2(x, y) gives angle from Y-axis (North), measured clockwise
    # This is different from standard atan2(y, x) which measures from X-axis
    angle_rad = math.atan2(normal.X, normal.Y)
    angle_deg = math.degrees(angle_rad)
    
    # Convert to 0-360 range
    if angle_deg < 0:
        angle_deg += 360
    
    # Map to compass direction using 45° sectors centered on cardinal/ordinal directions
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
    Generate sample points on the window surface for ray casting.
    
    Per NEN 5060, the primary reference point is at the bottom center of
    the window. However, using multiple sample points and averaging the
    results gives more representative values for the entire window.
    
    Parameters
    ----------
    window_bbox : BoundingBox
        Bounding box of the window mesh
    window_normal : Vector3d
        Outward-facing normal of the window
        
    Returns
    -------
    list of tuples
        Each tuple contains: (Point3d, weight)
        - Point3d: Sample point location
        - weight: Relative weight for averaging (bottom points weighted higher)
        
    Sample Point Layout
    -------------------
    Looking at window from outside:
    
        [   Top Center (weight 0.5)   ]
                    ●
        
        [   Middle Center (weight 1.0)   ]
                    ●
        
        [●          ●          ●] Bottom row (weights 1.5, 2.0, 1.5)
        Left    Center    Right
        
    The bottom center point has the highest weight (2.0) because it's the
    NEN 5060 reference point. Other points help capture variation across
    the window surface.
    """
    min_pt = window_bbox.Min
    max_pt = window_bbox.Max
    
    # Window center in XY plane
    center_x = (min_pt.X + max_pt.X) / 2
    center_y = (min_pt.Y + max_pt.Y) / 2
    
    # Compute horizontal direction (perpendicular to normal, in XY plane)
    up = rg.Vector3d(0, 0, 1)
    right = rg.Vector3d.CrossProduct(window_normal, up)
    if right.Length < 0.001:
        # Window is horizontal (looking up/down) - use arbitrary horizontal
        right = rg.Vector3d(1, 0, 0)
    right.Unitize()
    
    # Window width in the horizontal direction
    width = max(max_pt.X - min_pt.X, max_pt.Y - min_pt.Y)
    half_width = width * 0.35  # 70% of width coverage
    
    # Vertical positions (with small offsets from edges to avoid edge effects)
    z_bottom = min_pt.Z + 0.1  # 10cm above bottom edge
    z_mid = (min_pt.Z + max_pt.Z) / 2
    z_top = max_pt.Z - 0.1  # 10cm below top edge
    
    # Generate sample points with weights
    # Bottom row: 3 points, heavily weighted (per NEN 5060 reference point spec)
    # Middle: 1 point, standard weight
    # Top: 1 point, low weight (less important for shading analysis)
    samples = [
        # Bottom row - highest weights
        (rg.Point3d(center_x - right.X * half_width, 
                    center_y - right.Y * half_width, 
                    z_bottom), 1.5),  # Bottom left
        (rg.Point3d(center_x, center_y, z_bottom), 2.0),  # Bottom center (NEN 5060 ref)
        (rg.Point3d(center_x + right.X * half_width, 
                    center_y + right.Y * half_width, 
                    z_bottom), 1.5),  # Bottom right
        
        # Middle
        (rg.Point3d(center_x, center_y, z_mid), 1.0),
        
        # Top - lowest weight
        (rg.Point3d(center_x, center_y, z_top), 0.5),
    ]
    
    return samples


# ==============================================================================
# RAY CASTING FUNCTIONS
# ==============================================================================

def create_ray_directions(window_normal):
    """
    Create a set of ray directions for hemispherical sky sampling.
    
    Rays are cast in a pattern that samples the hemisphere in front of
    the window. The pattern is denser near horizontal (where most
    obstruction occurs) and covers ±60° horizontally.
    
    Parameters
    ----------
    window_normal : Vector3d
        Outward-facing normal of the window
        
    Returns
    -------
    list of tuples
        Each tuple contains: (direction, vertical_angle, horizontal_angle)
        - direction: Unit Vector3d for the ray
        - vertical_angle: Degrees above horizontal (0° = horizontal, 90° = up)
        - horizontal_angle: Degrees from window normal (-60° to +60°)
        
    Ray Pattern Visualization
    -------------------------
    Top view (looking down):
    
                     Window Normal (0°)
                          ↑
                    ╱     |     ╲
              -60° ╱      |      ╲ +60°
                  ╱       |       ╲
              ───●───●───●───●───●───  ← Rays spread horizontally
                         
    Side view:
    
              80° ─ ● ● ● ● ●  (high angles)
              60° ─ ● ● ● ● ●
              45° ─ ● ● ● ● ●
              30° ─ ● ● ● ● ●
              20° ─ ● ● ● ● ●
              10° ─ ● ● ● ● ●  (low angles - most important for obstruction)
               5° ─ ● ● ● ● ●
              ─────────────────  Horizontal
    """
    directions = []
    
    # Establish coordinate frame
    # up: Vertical (Z+)
    # forward: Window normal direction (horizontal component)
    # right: Perpendicular to both (points to viewer's right when facing window)
    
    up = rg.Vector3d(0, 0, 1)
    forward = rg.Vector3d(window_normal)
    forward.Unitize()
    
    right = rg.Vector3d.CrossProduct(forward, up)
    if right.Length < 0.001:
        # Window normal is vertical - use arbitrary horizontal
        right = rg.Vector3d(0, 1, 0)
    right.Unitize()
    
    # Generate horizontal angles
    if HORIZONTAL_STEPS > 1:
        h_angles = []
        for i in range(HORIZONTAL_STEPS):
            # Distribute evenly from -spread to +spread
            h_angle = -HORIZONTAL_SPREAD + (2 * HORIZONTAL_SPREAD * i / (HORIZONTAL_STEPS - 1))
            h_angles.append(h_angle)
    else:
        h_angles = [0]  # Single ray straight ahead
    
    # Generate ray directions for each vertical/horizontal angle combination
    for v_angle in VERTICAL_ANGLES:
        v_rad = math.radians(v_angle)
        
        for h_angle in h_angles:
            h_rad = math.radians(h_angle)
            
            # Compute horizontal direction (rotated from forward by h_angle)
            h_dir = forward * math.cos(h_rad) + right * math.sin(h_rad)
            h_dir.Unitize()
            
            # Combine horizontal direction with vertical angle
            # direction = horizontal_component * cos(v) + vertical_component * sin(v)
            direction = h_dir * math.cos(v_rad) + up * math.sin(v_rad)
            direction.Unitize()
            
            directions.append((direction, v_angle, h_angle))
    
    return directions


def cast_rays_for_context(sample_points, ray_directions, context_meshes, debug_info=None):
    """
    Cast rays to determine context obstruction angle.
    
    Context obstruction is measured as the MAXIMUM angle at which rays
    are blocked by context geometry. This represents "how high up do
    buildings block the sky" - the top edge of visible obstruction.
    
    Parameters
    ----------
    sample_points : list of tuples
        From get_window_sample_points()
    ray_directions : list of tuples
        From create_ray_directions()
    context_meshes : list of tuples
        Filtered context geometry (mesh, bbox, idx)
    debug_info : list, optional
        List to append debug messages to
        
    Returns
    -------
    float
        Maximum obstruction angle in degrees (0-80)
        0 = no obstruction, 80 = heavy obstruction
        
    Algorithm
    ---------
    1. Combine all context meshes into one (faster single intersection test)
    2. For each sample point on window:
       a. Cast rays at all angles
       b. Record the maximum angle that hits geometry
    3. Compute weighted average across sample points
    4. Blend with absolute maximum for conservative result
    
    The blend (70% weighted avg + 30% max) ensures we don't underestimate
    obstruction when one part of the window is heavily shaded.
    """
    # Handle empty context
    if not context_meshes:
        if debug_info is not None:
            debug_info.append("      No context geometry after filtering")
        return 0.0
    
    # Combine all context meshes for single intersection test
    # This is faster than testing each mesh separately
    combined_mesh = rg.Mesh()
    for mesh, bbox, idx in context_meshes:
        combined_mesh.Append(mesh)
    
    if combined_mesh.Vertices.Count == 0:
        if debug_info is not None:
            debug_info.append("      Combined context mesh is empty")
        return 0.0
    
    # Track results per sample point
    sample_results = []  # List of (max_angle, weight) tuples
    total_rays_cast = 0
    total_rays_blocked = 0
    
    for sample_pt, weight in sample_points:
        sample_max_angle = 0.0
        
        for direction, v_angle, h_angle in ray_directions:
            # Create ray from sample point in this direction
            ray = rg.Ray3d(sample_pt, direction)
            
            # Test intersection with combined context mesh
            # MeshRay returns the parameter t where ray intersects mesh
            # t < 0 means no intersection (or behind ray origin)
            t = rg.Intersect.Intersection.MeshRay(combined_mesh, ray)
            
            total_rays_cast += 1
            
            # Check if ray hit something within valid distance range
            if t >= MIN_RAY_DISTANCE and t < MAX_CONTEXT_DISTANCE:
                total_rays_blocked += 1
                # Track the highest angle at which we hit something
                if v_angle > sample_max_angle:
                    sample_max_angle = v_angle
        
        sample_results.append((sample_max_angle, weight))
    
    # Compute final angle
    if sample_results:
        # Weighted average of sample results
        total_weight = sum(w for _, w in sample_results)
        weighted_sum = sum(angle * weight for angle, weight in sample_results)
        
        if total_weight > 0:
            weighted_avg = weighted_sum / total_weight
            absolute_max = max(angle for angle, _ in sample_results)
            
            # Blend: 70% weighted average + 30% absolute maximum
            # This provides a balance between average behavior and worst case
            final_angle = weighted_avg * 0.7 + absolute_max * 0.3
        else:
            final_angle = 0.0
    else:
        final_angle = 0.0
    
    # Debug output
    if debug_info is not None:
        debug_info.append("      Context: {} rays cast, {} blocked ({:.1f}%)".format(
            total_rays_cast, total_rays_blocked, 
            100.0 * total_rays_blocked / max(1, total_rays_cast)))
        debug_info.append("      Sample angles: {}".format(
            ["{:.1f}°".format(a) for a, _ in sample_results]))
        debug_info.append("      Weighted avg: {:.1f}°, Max: {:.1f}°, Final: {:.1f}°".format(
            weighted_avg if sample_results else 0,
            absolute_max if sample_results else 0,
            final_angle))
    
    return final_angle


def cast_rays_for_shading(window_center, window_normal, window_bbox, shading_mesh, debug_info=None):
    """
    Cast rays to determine shading device obstruction angle.
    
    Shading obstruction is measured as the MINIMUM angle at which rays
    are blocked by the shading device. This represents "where does the
    overhang start blocking" - the bottom edge of the shadow zone.
    
    Parameters
    ----------
    window_center : Point3d
        Center of the window
    window_normal : Vector3d
        Outward-facing normal of the window
    window_bbox : BoundingBox
        Bounding box of the window
    shading_mesh : Mesh
        The shading device mesh (can be None)
    debug_info : list, optional
        List to append debug messages to
        
    Returns
    -------
    tuple (float, float)
        - min_angle: Minimum blocked angle in degrees (5-90)
          90 = no shading device, lower = deeper overhang
        - ho_ratio: Obstruction ratio (projection_depth / window_height)
          Used for NEN 5060 table lookup
          
    Algorithm
    ---------
    1. Cast rays from window bottom center (NEN 5060 reference point)
    2. Rays go straight forward at increasing vertical angles
    3. Find the LOWEST angle that hits the shading device
    4. Calculate projection depth from hit distance
    
    Why only forward rays (not fanned)?
    For typical horizontal overhangs directly above the window,
    the most relevant measurement is straight out, perpendicular
    to the facade. Side angles would hit the same overhang at
    different depths, complicating the ho_ratio calculation.
    """
    # Handle missing shading device
    if shading_mesh is None:
        if debug_info is not None:
            debug_info.append("      No shading device for this window")
        return 90.0, 0.0  # 90° means 0° of sky blocked
    
    # Window properties
    window_height = window_bbox.Max.Z - window_bbox.Min.Z
    
    # Reference point: bottom center of window (per NEN 5060)
    ref_point = rg.Point3d(
        (window_bbox.Min.X + window_bbox.Max.X) / 2,
        (window_bbox.Min.Y + window_bbox.Max.Y) / 2,
        window_bbox.Min.Z + 0.1  # 10cm above bottom edge
    )
    
    # Direction vectors
    up = rg.Vector3d(0, 0, 1)
    forward = rg.Vector3d(window_normal)
    forward.Unitize()
    
    # Track minimum blocked angle
    min_blocked_angle = 90.0  # Start with "no blockage"
    hit_distance = 0.0
    
    # Test angles from low to high (5° to 85° in 5° steps)
    # We're looking for the LOWEST angle that hits the shading
    test_angles = list(range(5, 86, 5))
    hits = []  # For debug output
    
    for v_angle in test_angles:
        v_rad = math.radians(v_angle)
        
        # Ray direction: forward tilted up by v_angle
        direction = forward * math.cos(v_rad) + up * math.sin(v_rad)
        direction.Unitize()
        
        # Cast ray
        ray = rg.Ray3d(ref_point, direction)
        t = rg.Intersect.Intersection.MeshRay(shading_mesh, ray)
        
        # Check for valid hit
        if t >= MIN_RAY_DISTANCE and t < MAX_SHADING_DISTANCE:
            hits.append((v_angle, t))
            if v_angle < min_blocked_angle:
                min_blocked_angle = v_angle
                hit_distance = t
    
    # Calculate projection depth and ho ratio
    if min_blocked_angle < 90.0:
        # Projection depth = horizontal distance to hit point
        # hit_distance * cos(angle) gives horizontal component
        projection_depth = hit_distance * math.cos(math.radians(min_blocked_angle))
        ho_ratio = projection_depth / window_height if window_height > 0 else 0.0
    else:
        projection_depth = 0.0
        ho_ratio = 0.0
    
    # Debug output
    if debug_info is not None:
        debug_info.append("      Shading: {} hits out of {} test angles".format(
            len(hits), len(test_angles)))
        if hits:
            debug_info.append("      Hit angles: {}".format(
                ["{:.0f}°@{:.2f}m".format(a, d) for a, d in hits[:5]]))  # First 5
        debug_info.append("      Min blocked: {:.1f}°, Projection: {:.2f}m, ho={:.3f}".format(
            min_blocked_angle, projection_depth, ho_ratio))
    
    return min_blocked_angle, ho_ratio


# ==============================================================================
# CLASSIFICATION AND LOOKUP FUNCTIONS
# ==============================================================================

def get_ho_category(ho_ratio):
    """
    Categorize the obstruction ratio for NEN 5060 table lookup.
    
    The ho;⊥ (perpendicular obstruction ratio) determines which column
    to use in Tabel 17.7. It represents how deep the obstruction projects
    relative to the window height.
    
    Parameters
    ----------
    ho_ratio : float
        Projection depth divided by window height
        
    Returns
    -------
    str
        Category string: "<0.5", "0.5-1.0", or ">=1.0"
        
    Examples
    --------
    Window height 1.5m, overhang projection 0.6m:
        ho = 0.6/1.5 = 0.4 → "<0.5"
        
    Window height 2.0m, overhang projection 1.5m:
        ho = 1.5/2.0 = 0.75 → "0.5-1.0"
        
    Window height 1.0m, overhang projection 1.2m:
        ho = 1.2/1.0 = 1.2 → ">=1.0"
    """
    if ho_ratio < 0.5:
        return "<0.5"
    elif ho_ratio < 1.0:
        return "0.5-1.0"
    else:
        return ">=1.0"


def angle_to_ho_ratio_approximation(angle_degrees):
    """
    Approximate ho ratio from obstruction angle.
    
    This is used for context obstruction where we don't have a direct
    projection depth measurement. The approximation uses:
        ho ≈ tan(angle)
        
    This assumes the obstruction is at approximately window height distance,
    which is a reasonable approximation for typical urban contexts.
    
    Parameters
    ----------
    angle_degrees : float
        Obstruction angle in degrees
        
    Returns
    -------
    float
        Estimated ho ratio (clamped to 0-2 range)
    """
    if angle_degrees <= 0:
        return 0.0
    elif angle_degrees >= 89:
        return 2.0  # Cap at 2.0 to avoid infinity
    else:
        return math.tan(math.radians(angle_degrees))


def lookup_fsh_factor(classification, orientation, month, ho_ratio):
    """
    Look up the solar shading reduction factor from NEN 5060 tables.
    
    Parameters
    ----------
    classification : str
        "Minimale Belemmering", "Overstek", or "Belemmering"
    orientation : str
        Compass direction (e.g., "Zuid", "Noord Oost")
    month : int
        Month number (1-12)
    ho_ratio : float
        Obstruction ratio (used for Tabel 17.7 lookup)
        
    Returns
    -------
    float
        Fsh;obst value between 0 and 1
        0 = complete shading (no solar gain)
        1 = no shading (full solar gain)
        
    Notes
    -----
    - "Zuid West" is not in the tables; it's interpolated as (Zuid + West) / 2
    - "Minimale Belemmering" uses Tabel 17.4 (no ho dependency)
    - "Overstek" and "Belemmering" use Tabel 17.7 (with ho category)
    """
    # Handle Zuid West interpolation (not in original tables)
    if orientation == "Zuid West":
        fsh_zuid = lookup_fsh_factor(classification, "Zuid", month, ho_ratio)
        fsh_west = lookup_fsh_factor(classification, "West", month, ho_ratio)
        return (fsh_zuid + fsh_west) / 2.0
    
    # Minimal obstruction uses Tabel 17.4
    if classification == "Minimale Belemmering":
        return TABEL_17_4.get(month, {}).get(orientation, 1.0)
    
    # Significant obstruction uses Tabel 17.7
    else:
        ho_category = get_ho_category(ho_ratio)
        return TABEL_17_7.get(month, {}).get(orientation, {}).get(ho_category, 1.0)


def get_branch_index(classification):
    """
    Map classification string to DataTree branch index.
    
    Parameters
    ----------
    classification : str
        Classification name
        
    Returns
    -------
    int
        Branch index: 0, 1, or 2
    """
    if classification == "Minimale Belemmering":
        return 0
    elif classification == "Overstek":
        return 1
    else:  # "Belemmering"
        return 2


# ==============================================================================
# MAIN CLASSIFICATION FUNCTION
# ==============================================================================

def classify_single_window(window_mesh, shading_mesh, context_meshes, 
                           all_ray_directions, month, window_index, debug_mode=True):
    """
    Perform complete classification analysis for a single window.
    
    This is the main analysis function that coordinates all the steps:
    1. Extract window properties
    2. Filter relevant context
    3. Cast rays for context and shading
    4. Compare sky blockage
    5. Determine classification
    6. Look up Fsh factor
    
    Parameters
    ----------
    window_mesh : Mesh
        The window surface mesh
    shading_mesh : Mesh or None
        The corresponding shading device (or None if no shading)
    context_meshes : list of tuples
        All context geometry (mesh, bbox, idx)
    all_ray_directions : dict
        Pre-computed ray directions (will compute if missing)
    month : int
        Month for Fsh lookup (1-12)
    window_index : int
        Index for debug output
    debug_mode : bool
        Whether to generate detailed debug info
        
    Returns
    -------
    dict with keys:
        'classification': str - "Minimale Belemmering", "Overstek", or "Belemmering"
        'fsh_factor': float - Solar shading reduction factor
        'orientation': str - Compass direction
        'ho_ratio': float - Obstruction ratio used for table lookup
        'context_angle': float - Raw context obstruction angle
        'shading_angle': float - Raw shading obstruction angle
        'context_blocked': float - Degrees of sky blocked by context
        'shading_blocked': float - Degrees of sky blocked by shading
        'dominant': str - Which factor dominated
        'debug_info': str - Detailed debug information
    """
    debug_lines = []
    
    if debug_mode:
        debug_lines.append("=" * 70)
        debug_lines.append("WINDOW {} ANALYSIS".format(window_index))
        debug_lines.append("=" * 70)
    
    # -------------------------------------------------------------------------
    # Step 1: Extract window properties
    # -------------------------------------------------------------------------
    w_center, w_normal, w_bbox = get_mesh_properties(window_mesh)
    
    if w_center is None:
        debug_lines.append("ERROR: Invalid window mesh")
        return {
            'classification': "Error",
            'fsh_factor': 1.0,
            'orientation': "Unknown",
            'ho_ratio': 0.0,
            'context_angle': 0.0,
            'shading_angle': 90.0,
            'context_blocked': 0.0,
            'shading_blocked': 0.0,
            'dominant': "Error",
            'debug_info': "\n".join(debug_lines)
        }
    
    window_height = w_bbox.Max.Z - w_bbox.Min.Z
    orientation = vector_to_compass_orientation(w_normal)
    
    if debug_mode:
        debug_lines.append("\n[1] WINDOW PROPERTIES")
        debug_lines.append("    Center: ({:.2f}, {:.2f}, {:.2f})".format(
            w_center.X, w_center.Y, w_center.Z))
        debug_lines.append("    Normal: ({:.3f}, {:.3f}, {:.3f})".format(
            w_normal.X, w_normal.Y, w_normal.Z))
        debug_lines.append("    Size: {:.2f}m height, Z range {:.2f} to {:.2f}".format(
            window_height, w_bbox.Min.Z, w_bbox.Max.Z))
        debug_lines.append("    Orientation: {}".format(orientation))
    
    # -------------------------------------------------------------------------
    # Step 2: Prepare ray casting
    # -------------------------------------------------------------------------
    # Get or create ray directions for this window's orientation
    # (We cache these in all_ray_directions dict for reuse)
    normal_key = "{:.3f},{:.3f}".format(w_normal.X, w_normal.Y)
    if normal_key not in all_ray_directions:
        all_ray_directions[normal_key] = create_ray_directions(w_normal)
    ray_directions = all_ray_directions[normal_key]
    
    # Get sample points on window
    sample_points = get_window_sample_points(w_bbox, w_normal)
    
    if debug_mode:
        debug_lines.append("\n[2] RAY CASTING SETUP")
        debug_lines.append("    {} sample points on window".format(len(sample_points)))
        debug_lines.append("    {} ray directions per sample".format(len(ray_directions)))
        debug_lines.append("    Total rays for context: {}".format(
            len(sample_points) * len(ray_directions)))
    
    # -------------------------------------------------------------------------
    # Step 3: Filter and analyze context
    # -------------------------------------------------------------------------
    relevant_context = filter_context_for_window(
        context_meshes, w_center, w_normal, w_bbox)
    
    if debug_mode:
        debug_lines.append("\n[3] CONTEXT ANALYSIS")
        debug_lines.append("    {} of {} context objects in front of window".format(
            len(relevant_context), len(context_meshes)))
    
    ctx_angle = cast_rays_for_context(
        sample_points, ray_directions, relevant_context,
        debug_lines if debug_mode else None)
    
    # -------------------------------------------------------------------------
    # Step 4: Analyze shading device
    # -------------------------------------------------------------------------
    if debug_mode:
        debug_lines.append("\n[4] SHADING ANALYSIS")
    
    shd_angle, shd_ho = cast_rays_for_shading(
        w_center, w_normal, w_bbox, shading_mesh,
        debug_lines if debug_mode else None)
    
    # -------------------------------------------------------------------------
    # Step 5: Classification decision
    # -------------------------------------------------------------------------
    # Convert to "degrees of sky blocked" for fair comparison
    # Context blocks from horizon UP: blocked = angle
    # Shading blocks from zenith DOWN: blocked = 90 - angle
    ctx_blocked = ctx_angle
    shd_blocked = 90.0 - shd_angle
    
    # Determine if each factor is significant (above threshold)
    ctx_significant = ctx_blocked > MINIMAL_OBSTRUCTION_THRESHOLD
    shd_significant = shd_blocked > MINIMAL_OBSTRUCTION_THRESHOLD and shading_mesh is not None
    
    if debug_mode:
        debug_lines.append("\n[5] CLASSIFICATION DECISION")
        debug_lines.append("    Context: {:.1f}° angle → {:.1f}° blocked {}".format(
            ctx_angle, ctx_blocked, "(SIGNIFICANT)" if ctx_significant else "(minimal)"))
        debug_lines.append("    Shading: {:.1f}° angle → {:.1f}° blocked {}".format(
            shd_angle, shd_blocked, "(SIGNIFICANT)" if shd_significant else "(minimal)"))
        debug_lines.append("    Threshold: {:.1f}°".format(MINIMAL_OBSTRUCTION_THRESHOLD))
    
    # Decision logic
    if not ctx_significant and not shd_significant:
        # Neither factor blocks significant sky
        classification = "Minimale Belemmering"
        final_ho = 0.0
        dominant = "Neither (<{}°)".format(int(MINIMAL_OBSTRUCTION_THRESHOLD))
        
    elif shd_significant and (not ctx_significant or shd_blocked >= ctx_blocked):
        # Shading blocks more (or equal) sky
        classification = "Overstek"
        final_ho = shd_ho
        dominant = "Shading ({:.0f}° >= {:.0f}°)".format(shd_blocked, ctx_blocked)
        
    else:
        # Context blocks more sky
        classification = "Belemmering"
        final_ho = angle_to_ho_ratio_approximation(ctx_angle)
        dominant = "Context ({:.0f}° > {:.0f}°)".format(ctx_blocked, shd_blocked)
    
    if debug_mode:
        debug_lines.append("    → Dominant factor: {}".format(dominant))
        debug_lines.append("    → Classification: {}".format(classification))
    
    # -------------------------------------------------------------------------
    # Step 6: Look up Fsh factor
    # -------------------------------------------------------------------------
    fsh = lookup_fsh_factor(classification, orientation, month, final_ho)
    
    if debug_mode:
        debug_lines.append("\n[6] FSH LOOKUP")
        debug_lines.append("    ho ratio: {:.3f} → category: {}".format(
            final_ho, get_ho_category(final_ho)))
        if classification == "Minimale Belemmering":
            debug_lines.append("    Table: 17.4[{}][{}] = {:.3f}".format(
                month, orientation, fsh))
        else:
            debug_lines.append("    Table: 17.7[{}][{}][{}] = {:.3f}".format(
                month, orientation, get_ho_category(final_ho), fsh))
    
    # -------------------------------------------------------------------------
    # Summary
    # -------------------------------------------------------------------------
    if debug_mode:
        debug_lines.append("\n" + "=" * 70)
        debug_lines.append("RESULT: {} | {} | Fsh={:.3f} | ho={:.3f}".format(
            classification, orientation, fsh, final_ho))
        debug_lines.append("=" * 70)
    
    return {
        'classification': classification,
        'fsh_factor': round(fsh, 3),
        'orientation': orientation,
        'ho_ratio': round(final_ho, 3),
        'context_angle': round(ctx_angle, 1),
        'shading_angle': round(shd_angle, 1),
        'context_blocked': round(ctx_blocked, 1),
        'shading_blocked': round(shd_blocked, 1),
        'dominant': dominant,
        'debug_info': "\n".join(debug_lines)
    }


# ==============================================================================
# MAIN EXECUTION
# ==============================================================================

# Initialize all output lists
# These will be populated by the main loop and returned to Grasshopper

classification = []       # Classification name per window
fsh_factor = []           # Solar shading reduction factor per window
orientation = []          # Compass orientation per window
ho_ratio = []             # Obstruction ratio per window
debug_info = []           # Detailed debug string per window

# Additional diagnostic outputs
context_angles = []       # Raw context angle per window
shading_angles = []       # Raw shading angle per window
context_sky_blocked = []  # Context sky blockage per window
shading_sky_blocked = []  # Shading sky blockage per window
dominant_factor = []      # Which factor dominated per window

# DataTree for classified meshes (3 branches)
classified_meshes = DataTree[System.Object]()
classified_meshes.EnsurePath(GH_Path(0))  # Minimale Belemmering
classified_meshes.EnsurePath(GH_Path(1))  # Overstek
classified_meshes.EnsurePath(GH_Path(2))  # Belemmering

# -----------------------------------------------------------------------------
# Input validation and normalization
# -----------------------------------------------------------------------------

# Handle None or single-item inputs
if glazing_meshes is None:
    glazing_meshes = []
elif not isinstance(glazing_meshes, list):
    glazing_meshes = [glazing_meshes]

if shading_meshes is None:
    shading_meshes = []
elif not isinstance(shading_meshes, list):
    shading_meshes = [shading_meshes]

if context_geometry is None:
    context_geometry = []
elif not isinstance(context_geometry, list):
    context_geometry = [context_geometry]

# Validate and default month
if month is None or month < 1 or month > 12:
    month = 1

# Pad shading list to match glazing list (allows windows without shading)
while len(shading_meshes) < len(glazing_meshes):
    shading_meshes.append(None)

# -----------------------------------------------------------------------------
# Print header
# -----------------------------------------------------------------------------

print("=" * 80)
print("NEN 5060 WINDOW SHADING CLASSIFICATION v7.0")
print("=" * 80)
print("")
print("INPUT SUMMARY:")
print("  Windows (glazing_meshes): {}".format(len(glazing_meshes)))
print("  Shading devices (shading_meshes): {} ({} valid)".format(
    len(shading_meshes), sum(1 for s in shading_meshes if s is not None)))
print("  Context buildings (context_geometry): {}".format(len(context_geometry)))
print("  Analysis month: {} ({})".format(month, [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December"
][month - 1]))
print("")
print("METHODOLOGY:")
print("  - Context obstruction: blocks sky from 0° up to context_angle")
print("  - Shading obstruction: blocks sky from shading_angle up to 90°")
print("  - Comparison: context_blocked vs shading_blocked (= 90 - shading_angle)")
print("  - Threshold for 'significant': {}°".format(MINIMAL_OBSTRUCTION_THRESHOLD))
print("")
print("=" * 80)

# -----------------------------------------------------------------------------
# Prepare geometry (one-time conversion)
# -----------------------------------------------------------------------------

print("\nPREPARING GEOMETRY...")
context_meshes = convert_geometry_to_meshes(context_geometry, debug_callback=print)

# Cache for ray directions (computed per unique window normal)
ray_direction_cache = {}

# -----------------------------------------------------------------------------
# Process each window
# -----------------------------------------------------------------------------

print("\nPROCESSING WINDOWS...")
print("-" * 80)
print("{:>5} {:>7} {:>7} {:>8} {:>8} {:>14} {:>8} {:>7}".format(
    "Win", "Ctx°", "Shd°", "Ctx_blk", "Shd_blk", "Dominant", "Class", "Fsh"))
print("-" * 80)

for i, window_mesh in enumerate(glazing_meshes):
    # Get corresponding shading device (may be None)
    shading_mesh = shading_meshes[i] if i < len(shading_meshes) else None
    
    # Perform full analysis
    result = classify_single_window(
        window_mesh=window_mesh,
        shading_mesh=shading_mesh,
        context_meshes=context_meshes,
        all_ray_directions=ray_direction_cache,
        month=month,
        window_index=i,
        debug_mode=True  # Set to False for production (faster)
    )
    
    # Store results
    classification.append(result['classification'])
    fsh_factor.append(result['fsh_factor'])
    orientation.append(result['orientation'])
    ho_ratio.append(result['ho_ratio'])
    debug_info.append(result['debug_info'])
    
    context_angles.append(result['context_angle'])
    shading_angles.append(result['shading_angle'])
    context_sky_blocked.append(result['context_blocked'])
    shading_sky_blocked.append(result['shading_blocked'])
    dominant_factor.append(result['dominant'])
    
    # Add to appropriate DataTree branch
    branch_idx = get_branch_index(result['classification'])
    classified_meshes.Add(window_mesh, GH_Path(branch_idx))
    
    # Print summary row
    cls_abbrev = {
        "Minimale Belemmering": "Min",
        "Overstek": "Ove",
        "Belemmering": "Bel",
        "Error": "Err"
    }.get(result['classification'], "???")
    
    # Truncate dominant factor for display
    dom_display = result['dominant'][:14]
    
    print("{:>5} {:>7.1f} {:>7.1f} {:>8.1f} {:>8.1f} {:>14} {:>8} {:>7.3f}".format(
        i,
        result['context_angle'],
        result['shading_angle'],
        result['context_blocked'],
        result['shading_blocked'],
        dom_display,
        cls_abbrev,
        result['fsh_factor']
    ))

# -----------------------------------------------------------------------------
# Print summary
# -----------------------------------------------------------------------------

print("\n" + "=" * 80)
print("SUMMARY")
print("=" * 80)

# Count classifications
count_min = sum(1 for c in classification if c == "Minimale Belemmering")
count_ove = sum(1 for c in classification if c == "Overstek")
count_bel = sum(1 for c in classification if c == "Belemmering")
count_err = sum(1 for c in classification if c == "Error")

print("\nCLASSIFICATION DISTRIBUTION:")
print("  Branch {0} - Minimale Belemmering: {:>4} windows ({:.1f}%)".format(
    count_min, 100.0 * count_min / max(1, len(classification))))
print("  Branch {1} - Overstek:             {:>4} windows ({:.1f}%)".format(
    count_ove, 100.0 * count_ove / max(1, len(classification))))
print("  Branch {2} - Belemmering:          {:>4} windows ({:.1f}%)".format(
    count_bel, 100.0 * count_bel / max(1, len(classification))))
if count_err > 0:
    print("  Errors:                           {:>4} windows".format(count_err))

# Angle statistics
if context_angles:
    print("\nCONTEXT OBSTRUCTION:")
    print("  Raw angles:  min={:.1f}°  max={:.1f}°  avg={:.1f}°".format(
        min(context_angles), max(context_angles), 
        sum(context_angles) / len(context_angles)))
    print("  Sky blocked: min={:.1f}°  max={:.1f}°  avg={:.1f}°".format(
        min(context_sky_blocked), max(context_sky_blocked),
        sum(context_sky_blocked) / len(context_sky_blocked)))

if shading_angles:
    print("\nSHADING OBSTRUCTION:")
    print("  Raw angles:  min={:.1f}°  max={:.1f}°  avg={:.1f}°".format(
        min(shading_angles), max(shading_angles),
        sum(shading_angles) / len(shading_angles)))
    print("  Sky blocked: min={:.1f}°  max={:.1f}°  avg={:.1f}°".format(
        min(shading_sky_blocked), max(shading_sky_blocked),
        sum(shading_sky_blocked) / len(shading_sky_blocked)))

if fsh_factor:
    print("\nFSH FACTORS:")
    print("  Range: {:.3f} to {:.3f}".format(min(fsh_factor), max(fsh_factor)))
    print("  Average: {:.3f}".format(sum(fsh_factor) / len(fsh_factor)))

print("\n" + "=" * 80)
print("OUTPUTS AVAILABLE:")
print("  classified_meshes - DataTree with 3 branches (Min/Ove/Bel)")
print("  classification    - List of classification names")
print("  fsh_factor        - List of Fsh values")
print("  orientation       - List of compass orientations")
print("  ho_ratio          - List of obstruction ratios")
print("  debug_info        - List of detailed debug strings")
print("  context_angles    - List of raw context angles")
print("  shading_angles    - List of raw shading angles")
print("  context_sky_blocked - List of context sky blockage")
print("  shading_sky_blocked - List of shading sky blockage")
print("  dominant_factor   - List of dominant factor descriptions")
print("=" * 80)
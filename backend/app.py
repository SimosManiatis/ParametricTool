
print("[DEBUG] app.py starting import...")
import sys
import os

# Ensure the current directory is in sys.path so we can import 'core'
# This is required because the portable/embedded Python might not add it automatically
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from flask import Flask
import ghhops_server as hs
import rhino3dm
import json

# Updated import for new folder structure
# We also need rhino_mesh_to_trimesh for the app optimization
from core.classification_logic import classify_window_logic, rhino_mesh_to_trimesh
from core.table_formatter import format_table_header, format_table_row, format_table_summary
from ghhops_server.params import _GHParam, HopsParamAccess
import core.classification_logic
print(f"[DEBUG] Loaded logic from: {core.classification_logic.__file__}")

# MONKEYPATCH: Fix for Hops 'KeyError: {0}'
# Grasshopper often sends data with paths like '{0;0}' even when Hops expects '{0}'.
# This patch forces the server to use the first available branch if '{0}' is missing.
_original_from_input = _GHParam.from_input

def _patched_from_input(self, input_data):
    # Full replacement of from_input to handle flattened tree structures (e.g. {0;0} vs {0})
    # If TREE access, use original logic (it handles all paths)
    if self.access == HopsParamAccess.TREE:
        return _original_from_input(self, input_data)

    # For ITEM and LIST access, Hops expects data under "{0}".
    # We will accept data under ANY key if "{0}" is missing.
    inner_tree = input_data.get("InnerTree", {})
    branch_data = []
    
    if "{0}" in inner_tree:
        branch_data = inner_tree["{0}"]
    elif inner_tree:
        # Fallback: take the first available branch
        first_key = next(iter(inner_tree))
        branch_data = inner_tree[first_key]
    
    # Process the data
    data = []
    for item in branch_data:
        p_type = item["type"]
        p_val = item["data"]
        # Decode using the instance's coercer
        data.append(self._coerce_value(p_type, p_val))
        
    if self.access == HopsParamAccess.ITEM:
        if not data:
            if self.optional or self.default is not None:
                return self.default if self.default is not None else None
            return None 

        return data[0]
            
    return data

_GHParam.from_input = _patched_from_input

# ... app init ...
app = Flask(__name__)
hops = hs.Hops(app)

@app.before_request
def log_request_info():
    from flask import request
    if request.path == "/nen5060_classify":
        print(f"\n[DEBUG] Request received: {request.method} {request.path}")
        print(f"[DEBUG] Content-Length: {request.content_length}")
        if request.data:
            trunc = request.data[:500] 
            print(f"[DEBUG] Body Preview: {trunc}")

@hops.component(
    "/nen5060_classify",
    name="NEN 5060 Classify",
    description="Classify window shading according to NEN 5060 (Standalone)",
    inputs=[
        hs.HopsMesh("Window", "W", "Window Meshes", access=hs.HopsParamAccess.LIST),
        hs.HopsMesh("Shading", "S", "Shading Device Meshes", access=hs.HopsParamAccess.LIST, optional=True),
        hs.HopsMesh("Context", "C", "Context Meshes", access=hs.HopsParamAccess.LIST, optional=True),
        hs.HopsInteger("Month", "M", "Month (1-12)", default=1, access=hs.HopsParamAccess.ITEM)
    ],
    outputs=[
        hs.HopsString("Classification", "Class", "NEN 5060 Classification"),
        hs.HopsNumber("Fsh", "Fsh", "Shading Reduction Factor"),
        hs.HopsString("Orientation", "Ori", "Compass Orientation"),
        hs.HopsString("Debug Info", "Dbg", "Debug Information")
    ]
)
def nen5060_classify(window_meshes, shading_meshes, context_meshes, month):
    try:
        # Normalize inputs
        if window_meshes is None: window_meshes = []
        if shading_meshes is None: shading_meshes = []
        if context_meshes is None: context_meshes = []
        
        # NOTE: We switched input to HopsMesh. Grasshopper will mesh Breps automatically before sending.
        # This solves the standalone server's inability to mesh Breps.
        
        valid_context_data = [] # List of (trimesh, bbox, idx)
        
        for i, geom in enumerate(context_meshes):
            # geom should now be a Mesh
            if isinstance(geom, rhino3dm.Mesh):
                tm = rhino_mesh_to_trimesh(geom)
                if tm:
                    bbox = geom.GetBoundingBox()
                    valid_context_data.append((tm, bbox, i))
            else:
                # Fallback logging if something weird comes through
                print(f"[WARN] Context item {i} is not a Mesh: {type(geom)}")
        
        if len(valid_context_data) < len(context_meshes):
             print(f"[WARN] Some Context geometries could not be processed. Using {len(valid_context_data)}/{len(context_meshes)} valid context meshes.")

        results_class = []
        results_fsh = []
        results_ori = []
        results_dbg = []

        print(f"[DEBUG] Processing {len(window_meshes)} windows, {len(shading_meshes)} shading meshes, {len(valid_context_data)} context items.")
        
        # Iterate over all windows
        for i, win_mesh in enumerate(window_meshes):
            # Use corresponding shading mesh (1:1 mapping)
            # This matches the Internal GH Component logic
            current_shading = None
            if shading_meshes and i < len(shading_meshes):
                current_shading = shading_meshes[i]
            
            if i < 5:
                print(f"[DEBUG] Win {i}: Has Shading? {current_shading is not None}")
                if current_shading:
                    bb = current_shading.GetBoundingBox()
                    print(f"        Shading BBox: {bb.Min} to {bb.Max}")

            # Pass PRE-PROCESSED context data
            result = classify_window_logic(
                window_mesh=win_mesh,
                shading_mesh=current_shading, 
                context_data=valid_context_data, # NEW SIGNATURE
                month=int(month),
                window_index=i,
                debug_mode=True
            )
            
            # Legacy result check (if error handling changed)
            if "error" in result and "classification" not in result:
                results_class.append("Error")
                results_fsh.append(1.0)
                results_ori.append("Unknown")
                results_dbg.append(json.dumps(result.get("error", "Unknown Error")))
                continue

            results_class.append(result["classification"])
            results_fsh.append(result["fsh_factor"])
            results_ori.append(result["orientation"])
            # Debug info in result is the VERBOSE trace. Keep it somewhere?
            # User wants the TABLE report in Dbg.
            
            # We add result dict to temporary list for table generation
            results_dbg.append(result) 
        
        # --- GENERATE REPORT TABLE ---
        # --- GENERATE REPORT TABLE ---
        # 1. Header (returns list)
        full_report_lines = format_table_header(
            num_windows=len(window_meshes),
            num_shading=len(shading_meshes),
            num_context=len(valid_context_data), 
            month=int(month)
        )
        
        # 2. Rows
        for i, res in enumerate(results_dbg):
             # format_table_row returns a single string line
             full_report_lines.append(format_table_row(i, res))
             
        # 3. Summary (returns list)
        full_report_lines.extend(format_table_summary(results_dbg))
        
        # Return LIST OF STRINGS. 
        # Grasshopper Panel will display each item on a new line.
        # This solves the "\n" escaping issue and "wonky" wrapping.
        final_dbg_output = full_report_lines
        
        return results_class, results_fsh, results_ori, final_dbg_output
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return ["Error"], [1.0], ["Exception"], [str(e)]

def kill_zombie_processes():
    import subprocess
    import os
    import re
    
    current_pid = os.getpid()
    print(f"[STARTUP] Current PID: {current_pid}. Checking for zombies...")
    
    try:
        # Get list of python processes: PID
        # tasklist /FI "IMAGENAME eq python.exe" /FO CSV /NH
        output = subprocess.check_output('tasklist /FI "IMAGENAME eq python.exe" /FO CSV /NH', shell=True).decode('utf-8', errors='ignore')
        
        for line in output.splitlines():
            if not line.strip(): continue
            parts = line.split(',')
            try:
                # Format: "Image Name","PID","Session Name","Session#","Mem Usage"
                pid_str = parts[1].strip('"')
                pid = int(pid_str)
                
                if pid != current_pid and pid > 0:
                    print(f"[STARTUP] Killing zombie python (PID {pid})...")
                    subprocess.run(f"taskkill /F /PID {pid}", shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except ValueError:
                continue
                
        print("[STARTUP] Zombie cleanup complete.")

    except Exception as e:
        print(f"[STARTUP] Failed to kill zombies: {e}")

def clear_pycache():
    """Clear __pycache__ directories to ensure fresh code loading"""
    import shutil
    base_dir = os.path.dirname(os.path.abspath(__file__))
    
    for folder in ['__pycache__', 'core/__pycache__']:
        cache_path = os.path.join(base_dir, folder)
        if os.path.exists(cache_path):
            try:
                shutil.rmtree(cache_path)
                print(f"[STARTUP] Cleared {cache_path}")
            except Exception as e:
                print(f"[STARTUP] Could not clear {cache_path}: {e}")

if __name__ == "__main__":
    print("[STARTUP] Running startup cleanup...")
    
    # 1. Kill zombie Python processes (DISABLED - kills self due to venv wrapper)
    # kill_zombie_processes()
    
    # 2. Clear pycache to ensure fresh code
    clear_pycache()
    
    print("[STARTUP] Cleanup complete. Starting server...")
    print(app.url_map)
    
    # NOTE: debug=False to prevent Flask's auto-reloader which can cause caching issues
    # Set debug=True only during development when you need auto-reload
    app.run(debug=False, port=5000)

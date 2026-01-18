
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
from core.classification_logic import classify_window_logic

app = Flask(__name__)
hops = hs.Hops(app)

@hops.component(
    "/nen5060_classify",
    name="NEN 5060 Classify",
    description="Classify window shading according to NEN 5060 (Standalone)",
    inputs=[
        hs.HopsMesh("Window", "W", "Window Mesh"),
        hs.HopsMesh("Shading", "S", "Shading Device Mesh", optional=True),
        hs.HopsMesh("Context", "C", "Context Meshes", access=hs.HopsParamAccess.LIST, optional=True),
        hs.HopsInteger("Month", "M", "Month (1-12)", default=1)
    ],
    outputs=[
        hs.HopsString("Classification", "Class", "NEN 5060 Classification"),
        hs.HopsNumber("Fsh", "Fsh", "Shading Reduction Factor"),
        hs.HopsString("Orientation", "Ori", "Compass Orientation"),
        hs.HopsString("Debug Info", "Dbg", "Debug Information")
    ]
)
def nen5060_classify(window_mesh, shading_mesh, context_meshes, month):
    try:
        # Hops passes rhino3dm.Mesh objects directly
        
        # Handle context list (might be None or empty)
        if context_meshes is None:
            context_meshes = []
            
        result = classify_window_logic(
            window_mesh=window_mesh,
            shading_mesh=shading_mesh,
            context_meshes=context_meshes,
            month=int(month),
            debug_mode=True
        )
        
        if "error" in result:
            return "Error", 1.0, "Unknown", result["error"]
            
        # Format debug info as a JSON string for easy inspection
        debug_json = json.dumps(result, indent=2)
        
        return (
            result["classification"],
            result["fsh_factor"],
            result["orientation"],
            debug_json
        )
        
    except Exception as e:
        return "Error", 1.0, "Exception", str(e)

if __name__ == "__main__":
    app.run(debug=True)


import sys
import os
import rhino3dm
import json

# Add parent directory to path to allow importing 'core'
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.classification_logic import classify_window_logic

def create_window_mesh():
    mesh = rhino3dm.Mesh()
    mesh.Vertices.Add(-0.75, 0, 0)
    mesh.Vertices.Add(0.75, 0, 0)
    mesh.Vertices.Add(0.75, 0, 2)
    mesh.Vertices.Add(-0.75, 0, 2)
    mesh.Faces.AddFace(0, 1, 2, 3)
    mesh.Normals.ComputeNormals()
    return mesh

def create_shading_mesh():
    mesh = rhino3dm.Mesh()
    mesh.Vertices.Add(-1.0, 0.0, 2.0)
    mesh.Vertices.Add(1.0, 0.0, 2.0)
    mesh.Vertices.Add(1.0, -1.0, 2.0)
    mesh.Vertices.Add(-1.0, -1.0, 2.0)
    mesh.Faces.AddFace(0, 1, 2, 3)
    mesh.Normals.ComputeNormals()
    return mesh

def run_test():
    print("Creating synthetic geometry...")
    window = create_window_mesh()
    shading = create_shading_mesh()
    
    print("\nRunning classification (Month 6)...")
    result = classify_window_logic(
        window_mesh=window,
        shading_mesh=shading,
        context_meshes=[],
        month=6,
        debug_mode=True
    )
    
    print("\nRESULT:")
    print(json.dumps(result, indent=2))
    
    assert result["orientation"] == "Zuid", f"Expected Zuid, got {result['orientation']}"
    assert result["classification"] == "Overstek", f"Expected Overstek, got {result['classification']}"
    
    print("\n✅ Verification SUCCESS!")

if __name__ == "__main__":
    run_test()


import sys
import os
import rhino3dm
import json
import time
import requests
import statistics

# Add parent directory to path to allow importing 'core'
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.classification_logic import classify_window_logic

# ==============================================================================
# 0. GEOMETRY GENERATION
# ==============================================================================

def create_window_mesh(x_offset=0):
    mesh = rhino3dm.Mesh()
    mesh.Vertices.Add(-0.75 + x_offset, 0, 0)
    mesh.Vertices.Add(0.75 + x_offset, 0, 0)
    mesh.Vertices.Add(0.75 + x_offset, 0, 2)
    mesh.Vertices.Add(-0.75 + x_offset, 0, 2)
    mesh.Faces.AddFace(0, 1, 2, 3)
    mesh.Normals.ComputeNormals()
    return mesh

def create_shading_mesh(x_offset=0):
    mesh = rhino3dm.Mesh()
    mesh.Vertices.Add(-1.0 + x_offset, 0.0, 2.0)
    mesh.Vertices.Add(1.0 + x_offset, 0.0, 2.0)
    mesh.Vertices.Add(1.0 + x_offset, -1.0, 2.0)
    mesh.Vertices.Add(-1.0 + x_offset, -1.0, 2.0)
    mesh.Faces.AddFace(0, 1, 2, 3)
    mesh.Normals.ComputeNormals()
    return mesh

def mesh_to_hops_data(mesh):
    """Serialize geometry to the format Hops expects inside JSON"""
    return json.dumps(mesh.Encode())

# ==============================================================================
# 1. INTERNAL BENCHMARK (Pure Python Logic)
# ==============================================================================

def benchmark_internal(n_iterations=100):
    print(f"\n[INTERNAL] Benchmarking pure Python logic ({n_iterations} iterations)...")
    
    window = create_window_mesh()
    shading = create_shading_mesh()
    
    times = []
    
    for _ in range(n_iterations):
        start = time.perf_counter()
        classify_window_logic(
            window_mesh=window,
            shading_mesh=shading,
            context_meshes=[],
            month=6,
            debug_mode=False
        )
        end = time.perf_counter()
        times.append((end - start) * 1000) # ms
        
    avg_t = statistics.mean(times)
    median_t = statistics.median(times)
    max_t = max(times)
    
    print(f"  Avg: {avg_t:.2f}ms | Median: {median_t:.2f}ms | Max: {max_t:.2f}ms")
    return avg_t

# ==============================================================================
# 2. SERVER BENCHMARK (Simulating Hops Request)
# ==============================================================================

def benchmark_server_api(n_iterations=20):
    url = "http://127.0.0.1:5000/solve"
    print(f"\n[SERVER] Benchmarking API endpoint at {url} ({n_iterations} iterations)...")
    
    window = create_window_mesh()
    shading = create_shading_mesh()
    
    # Hops POST Payload Construction
    # This must match EXACTLY what Hops sends to avoid KeyError: '{0}'
    # Hops wraps inputs in "InnerTree" with path keys like "{0;0}" usually if drafted
    # or "{0}" if item access.
    # The error logs showed Hops sending {0} but the server failing on that key? 
    # Actually the logs showed `KeyError: '{0}'` inside `from_input`.
    # Let's try to mimic a standard Item access payload.
    
    # Payload format for a component with inputs: Window, Shading, Context, Month
    payload = {
        "pointer": "/nen5060_classify",
        "values": [
            {
                "ParamName": "Window",
                "InnerTree": {
                    "{0}": [{"type": "Rhino.Geometry.Mesh", "data": mesh_to_hops_data(window)}]
                }
            },
            {
                "ParamName": "Shading",
                "InnerTree": {
                    "{0}": [{"type": "Rhino.Geometry.Mesh", "data": mesh_to_hops_data(shading)}]
                }
            },
            {
                "ParamName": "Context",
                "InnerTree": {} # Empty list
            },
            {
                "ParamName": "Month",
                "InnerTree": {
                    "{0}": [{"type": "System.Int32", "data": "6"}]
                }
            }
        ]
    }
    
    times = []
    success_count = 0
    
    for i in range(n_iterations):
        try:
            start = time.perf_counter()
            resp = requests.post(url, json=payload)
            end = time.perf_counter()
            
            if resp.status_code == 200:
                times.append((end - start) * 1000)
                success_count += 1
            else:
                if i == 0:
                    print(f"  ❌ Request failed (Status {resp.status_code}): {resp.text[:200]}...")
        except Exception as e:
            if i == 0:
                print(f"  ❌ Connection failed: {e}")
            break
            
    if times:
        avg_t = statistics.mean(times)
        print(f"  ✅ Success: {success_count}/{n_iterations}")
        print(f"  Avg: {avg_t:.2f}ms | Min: {min(times):.2f}ms | Max: {max(times):.2f}ms")
    else:
        print("  ⚠️ No successful API calls recorded. Is the server running?")

if __name__ == "__main__":
    benchmark_internal(100)
    print("\nNote: Server benchmark requires the Flask app to be running separately.")
    try:
        benchmark_server_api(20)
    except Exception as e:
        print(f"Skipping server benchmark: {e}")


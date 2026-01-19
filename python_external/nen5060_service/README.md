# NEN 5060 Hops Service

A standalone Python service that performs NEN 5060 window shading classification using `trimesh` and exposes it to Grasshopper via `ghhops-server`.

## Overview

This service calculates:
*   **Classification**: "Minimale Belemmering", "Overstek", or "Belemmering".
*   **Fsh (SZN)**: The solar shading reduction factor according to NEN 5060 tables 17.4 and 17.7.
*   **Orientation**: Compass direction of the window.

It runs totally independent of Rhino's internal geometry engine, using `rhino3dm` (for file IO) and `trimesh` (for ray casting).

## 🚀 Installation

This project includes a **Portable Python** environment setup to ensure compatibility, as `rhino3dm` requires specific Python versions (3.9-3.12).

1.  **Open PowerShell** and navigate to this folder:
    ```powershell
    cd "path\to\nen5060_service"
    ```

2.  **Run the Setup Script**:
    This retrieves a portable Python 3.11 runtime and installs all dependencies locally.
    ```powershell
    powershell -ExecutionPolicy Bypass -File install_portable_python.ps1
    ```
    *Wait for the message "Setup Complete".*

## ⚡ Usage

### 1. Start the Server
Double-click `run_server.bat` OR run:
```powershell
.\run_server.bat
```
The server will start at `http://127.0.0.1:5000`.

### 2. Grasshopper Integration
1.  Place a **Hops** component in Grasshopper.
2.  Right-click the component > **Path** > Set to:
    `http://127.0.0.1:5000/nen5060_classify`
3.  Connect inputs:
    *   **Window**: (Mesh) The single window geometry.
    *   **Shading**: (Mesh, optional) The shading device / awning.
    *   **Context**: (List of Meshes, optional) Surroundings that block light.
    *   **Month**: (Integer) 1-12 (Used for Fsh lookup).

## Project Structure

```
nen5060_service/
├── app.py                      # Main Flask Hops server
├── run_server.bat              # Script to start server using portable python
├── install_portable_python.ps1 # Setup script
├── python_runtime/             # (Created after setup) The python environment
├── core/
│   ├── classification_logic.py # Ray casting engine
│   └── nen5060_tables.py       # NEN standards data
└── tests/
    └── verify_standalone.py    # Debugging script
```

## Troubleshooting

*   **"ModuleNotFoundError: No module named 'rhino3dm'"**:
    *   Ensure you are using `run_server.bat` and **NOT** your system python.
    *   Re-run `install_portable_python.ps1`.
*   **Hops Component Error**:
    *   Check the Grasshopper terminal for details.
    *   Ensure `Context` input is set to List Access if connecting multiple meshes.

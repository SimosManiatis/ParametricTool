# Overstek & Belemmering Classification Script

**Version:** 7.0 - Production Ready
**Standards:** NEN 5060 (Tabel 17.4, 17.7)

## Overview

This Python script (`Overstek_Belemmering_GH.py`) is designed to run inside a **Grasshopper GhPython component**. It performs a comprehensive solar shading analysis for windows to determine the correct **solar shading reduction factor (`Fsh;obst`)** according to the Dutch **NEN 5060** standard.

The script automatically classifies each window into one of three categories based on which obstruction dominates the sky view:
1.  **Minimale Belemmering (Minimal Obstruction)**: Neither context buildings nor shading devices significantly block the sun.
2.  **Overstek (Overhang)**: A shading device (balcony, awning, fin) is the dominant obstruction.
3.  **Belemmering (Context)**: Surrounding buildings or obstacles are the dominant obstruction.

## How It Works (Simplified)

Imagine standing at the bottom center of a window and looking out:
1.  **Context**: How much of the sky *from the horizon slightly upwards* is blocked by other buildings?
2.  **Shading**: How much of the sky *directly above* is blocked by an overhang?

The script compares these two blockages. The one that blocks **more** of the sky determines the classification. It then looks up the correct `Fsh` factor from the official NEN 5060 tables.

## Methodology & Logic

### 1. Classification Logic (NEN 5060)

The standard distinguishes between two types of reduction factors:
*   **Tabel 17.4 (`Fsh;obst;mi`)**: Used when obstruction is **minimal** (< 20°).
*   **Tabel 17.7 (`Fsh;obst;m`)**: Used when obstruction is **significant** (> 20°).

The standard works with obstruction angles (`ho`). However, context and shading work in opposite directions:
*   **Context** obstruction angle is measured from the **horizon (0°)** upwards. (Higher angle = More blocked).
*   **Shading** obstruction angle is measured from the **horizon (0°)** upwards to the *edge* of the overhang. (Lower angle = More blocked).

To compare them fairly, the script converts both to **"Degrees of Sky Blocked"**:
*   **Context Blocked** = `Context Angle`
*   **Shading Blocked** = `90° - Shading Angle`

**Decision Rule:**
*   If both blocked angles are < 20° → **Minimale Belemmering**.
*   If Shading blocks more sky than Context → **Overstek**.
*   Otherwise → **Belemmering**.

### 2. Ray Casting Algorithm

The script assumes nothing about the geometry and uses **Physics Ray Casting** to "see" the environment.

#### A. Window Analysis
*   **Orientation**: It calculates the compass direction (Noord, Zuid-Oost, etc.) from the window's normal vector.
*   **Sample Points**: It shoots rays from 5 points on the window surface (Weighted heavily towards the bottom center, per NEN 5060).

#### B. Context Analysis (The "Surroundings")
*   It casts rays in a **fan pattern** (±60° horizontal spread) to detect buildings.
*   It finds the **highest angle** that hits a context building.
*   *Optimization*: It pre-filters buildings behind the window to speed up calculation.

#### C. Shading Analysis (The "Overhangs")
*   It casts rays **straight up** and tilts them forward until they hit the shading device.
*   It finds the **lowest angle** that hits the shading device.
*   It calculates the **`ho` ratio** (Projection Depth / Window Height).

## Inputs & Outputs

### Inputs (Grasshopper Component)

| Name | Type | Description |
| :--- | :--- | :--- |
| **`glazing_meshes`** | List[Mesh] | The geometry of the windows to analyze. Must be valid meshes. |
| **`shading_meshes`** | List[Mesh] | The geometry of shading devices (awnings/balconies) corresponding 1-to-1 with the windows. (Use `null` item if a window has no shading). |
| **`context_geometry`** | List[Mesh/Brep] | All surrounding buildings or obstacles. Can be a huge list; the script optimizes automatically. |
| **`month`** | Integer | The month number (1-12) to calculate for. Solar position affects `Fsh` values. |

### Outputs

| Name | Type | Description |
| :--- | :--- | :--- |
| **`classified_meshes`** | DataTree | The windows sorted into branches: `{0}`=Minimal, `{1}`=Overstek, `{2}`=Belemmering. |
| **`classification`** | List[String] | Text result per window (e.g., "Overstek"). |
| **`fsh_factor`** | List[Float] | The final reduction factor (0.0 - 1.0). **This is the main result.** |
| **`dominant_factor`** | List[String] | Explanation of what caused the classification (e.g., "Shading (45° > 10°)"). |
| **`orientation`** | List[String] | Calculated compass direction (e.g., "Zuid-West"). |
| **`debug_info`** | List[String] | Detailed log for each window showing exactly how the decision was made. |
| **`ho_ratio`** | List[Float] | The obstruction ratio (`ho`) used for the table lookup. |

## Important Configuration Constants

At the top of the script (lines 150-200), there are constants you can tweak:

*   **`VERTICAL_ANGLES`**: Controls ray resolution (currently 5° steps).
*   **`HORIZONTAL_SPREAD`**: How wide to look for context (currently ±60°).
*   **`MAX_CONTEXT_DISTANCE`**: How far to look for buildings (currently 500m).

## Lookup Tables

The script contains the full **NEN 5060** tables hardcoded:
*   **`TABEL_17_4`**: For minimal obstruction.
*   **`TABEL_17_7`**: For significant obstruction (dependent on `ho` ratio).
*   *Note*: Logic is included to interpolate "Zuid-West", "Noord-West", etc., if they are missing from specific tables (averaging adjacent cardinal directions).

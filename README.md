# Parametric Analysis Tool - Central Hub

This repository serves as the central hub for the development and updates of the Parametric Analysis Tool, developed in-house for Traject (a Movares Company).

## Repository Structure

The repository is organized as follows:

- **`/grasshopper_releases`**: Contains Grasshopper files (`.gh`, `.ghx`) representing different release versions of the Parametric Tool.
- **`/python_internal`**: Contains source code for Python components designed to run internally within Grasshopper (GHPython).
- **`/python_external`**: Contains Python components and services (e.g., Flask apps) designed to run externally and stream data to Grasshopper (e.g., via Hops).
- **`/rhino_models`**: Contains Rhinoceros (`.3dm`) model files used in the project.
- **`/database`**: Contains Excel (`.xlsx`) and CSV (`.csv`) files serving as the project's database.

## Getting Started

Please check the specific sub-directories for detailed documentation on individual components.

- For the **NEN 5060 Service**, navigate to `python_external/nen5060_service/` to read the specific instructions.

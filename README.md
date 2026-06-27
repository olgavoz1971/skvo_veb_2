# skvo_veb_2

This repository contains a modernised revision of the IGEBC portal codebase. The application is a stateless Dash web application designed for astronomical data processing, visualisation, and lightcurve analysis (including TESS and Gaia data).

## Key Features

- **Page-by-Page Revision**: Re-implemented systematically to ensure clean separation between the frontend (UI, layouts, callbacks) and backend (scientific computations, Astropy, data processing).
- **AI-Assisted Development**: Developed and refactored with the assistance of AI agents, ensuring adherence to modern coding standards, robust error handling, and modular architecture.
- **Optimised Caching**: Utilises a thread-safe shared server-side caching engine (`flask_caching`) to store retrieved public astronomical data centrally, reducing external API load.
- **Virtual Observatory Integration**: Prioritises dedicated virtual observatory modules (such as `pyvo`) for querying astronomical services.

## Architecture

The project strictly separates concerns:
- `skvo_veb/pages/`: Frontend layout modules and presentation logic.
- `skvo_veb/utils/`: Pure scientific computations, numerical methods, and data query wrappers.
- `skvo_veb/assets/`: Custom CSS, styling, and static UI assets.
- `deployment/`: Configuration files for production environments.

## Getting Started

1. Set up a virtual environment:
   ```bash
   python -m venv .venv
   source .venv/bin/activate
   ```
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Run the application:
   ```bash
   python main.py
   ```

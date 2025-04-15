import os
from pathlib import Path
import sqlite3

import modal
import logging

from constants import DATA_DIR_IN_CONTAINER, DB_FILE

NFS = modal.NetworkFileSystem.from_name(
    "pdf-qa-nfs",
    create_if_missing=True,
)

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("modal_deploy")

PROJECT_ROOT_IN_CONTAINER = Path("/root/project")
project_root_local = Path(__file__).resolve().parent.parent
PYTHON_VERSION_FILENAME = ".python-version"


def _get_python_version():
    project_root_active = (
        PROJECT_ROOT_IN_CONTAINER
        if PROJECT_ROOT_IN_CONTAINER.exists()
        else project_root_local
    )
    return (project_root_active / PYTHON_VERSION_FILENAME).read_text().strip()


image = (
    modal.Image.debian_slim()
    .pip_install("uv")
    .add_local_file(
        local_path=str(project_root_local / "uv.lock"),
        remote_path=str(PROJECT_ROOT_IN_CONTAINER / "uv.lock"),
        copy=True,
    )
    .add_local_file(
        local_path=str(project_root_local / "pyproject.toml"),
        remote_path=str(PROJECT_ROOT_IN_CONTAINER / "pyproject.toml"),
        copy=True,
    )
    .add_local_file(
        local_path=str(project_root_local / PYTHON_VERSION_FILENAME),
        remote_path=str(PROJECT_ROOT_IN_CONTAINER / PYTHON_VERSION_FILENAME),
        copy=True,
    )
    .workdir(PROJECT_ROOT_IN_CONTAINER)
    .run_commands("uv sync --frozen --compile-bytecode")
    .env(
        {
            "PYTHONPATH": f".venv/lib/python{_get_python_version()}/site-packages:{os.environ.get('PYTHONPATH', '')}"
        }
    )
)

app = modal.App("pdf-qa-app-deployment", image=image)


try:
    from main import app as pdf_qa_fasthtml_app

    logger.info("Successfully imported FastHTML app from main.py")
except ImportError as e:
    logger.error(f"Failed to import app from main.py: {e}")
    pdf_qa_fasthtml_app = None


def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS interactions (
            id TEXT PRIMARY KEY,
            timestamp TEXT,
            pdf_name TEXT,
            query TEXT,
            response TEXT
        )
        """
    )
    conn.commit()
    conn.close()


@app.function(
    secrets=[modal.Secret.from_name("llm-secrets")],
    network_file_systems={str(DATA_DIR_IN_CONTAINER): NFS},
    # WARNING: Concurrency limit might be needed if SQLite access isn't thread-safe
    # or if UPLOADS dict causes issues. Start without, add if necessary.
    # concurrency_limit=1,
)
@modal.concurrent(1000)
@modal.asgi_app()
def serve_main_app():
    """
    Serves the imported FastHTML app from main.py.
    """
    logger.info("Serving the main PDF QA FastHTML app...")
    if pdf_qa_fasthtml_app is None:
        logger.error("Cannot serve: FastHTML app from main.py failed to import.")
        import fasthtml.common as fh

        error_app, error_rt = fh.fast_app()

        @error_rt("/")
        def error_route():
            return fh.H1("Error: Application failed to load.")

        return error_app

    logger.warning(
        "The underlying app in main.py uses a global dictionary (UPLOADS) for state."
    )
    logger.warning(
        "This WILL NOT work correctly with multiple Modal replicas and state will be lost."
    )
    logger.warning(
        "Consider using modal.Dict, NetworkFileSystem, or an external database for state."
    )
    DATA_DIR_IN_CONTAINER.mkdir(parents=True, exist_ok=True)
    init_db()
    return pdf_qa_fasthtml_app


@app.local_entrypoint()
def main():
    """Local development entry point confirmation."""
    logger.info("Deployment script for main.py app defined.")
    if pdf_qa_fasthtml_app:
        logger.info("FastHTML app from main.py imported successfully.")
        try:
            serve_func_name = serve_main_app.info.name
            print(f"To run locally: modal serve deploy.py::{serve_func_name}")
        except Exception:
            print("To run locally: modal serve deploy.py::serve_main_app")
    else:
        logger.error("Could not import FastHTML app from main.py.")


@app.function(
    image=image,
    network_file_systems={str(DATA_DIR_IN_CONTAINER): NFS},
)
@modal.asgi_app()
def serve_datasette():
    """Serves the Datasette UI for browsing the interactions database."""
    from datasette.app import Datasette

    db_path = Path(DATA_DIR_IN_CONTAINER) / DB_FILE

    if not db_path.exists():
        logger.error(f"Database file {db_path} not found in NFS for Datasette.")
        from fasthtml.common import fast_app, H1

        error_app, rt = fast_app()

        @rt("/")
        def error():
            return H1("Error: Database file not found.")

        return error_app

    logger.info(f"Starting Datasette for {db_path}")
    ds = Datasette(
        files=[db_path],
        settings={
            "sql_time_limit_ms": 5000  # Example setting: Limit query time
        },
    )
    return ds.app()

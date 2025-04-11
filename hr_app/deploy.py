# hr_app/deploy.py
import modal
import logging

# Configure basic logging for deployment script itself
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("modal_deploy")


# Define Modal Image with all dependencies from main.py
image = modal.Image.debian_slim().pip_install(
    "dotenv",
    "google-genai>=1.10.0",
    "pymupdf>=1.25.5",
    "python-fasthtml>=0.12.12",
)

# Define the Modal app container, referencing the image
app = modal.App("pdf-qa-app-deployment", image=image)


# --- Import the FastHTML app instance from main.py ---
# This assumes main.py is in the same directory or Python path
try:
    from main import app as pdf_qa_fasthtml_app

    logger.info("Successfully imported FastHTML app from main.py")
except ImportError as e:
    logger.error(f"Failed to import app from main.py: {e}")
    # Handle error - maybe raise, or define a fallback app
    pdf_qa_fasthtml_app = None


@app.function(
    allow_concurrent_inputs=1000,
    secrets=[modal.Secret.from_name("llm-secrets")],  # Add Google API key secret
    # WARNING: Concurrency limit might be needed if SQLite access isn't thread-safe
    # or if UPLOADS dict causes issues. Start without, add if necessary.
    # concurrency_limit=1,
    # Add Network File System if you want to persist SQLite DB or uploads
    # network_file_systems={"/data": modal.NetworkFileSystem.from_name("my-pdf-qa-nfs")}
)
@modal.asgi_app()
def serve_main_app():
    """
    Serves the imported FastHTML app from main.py.
    """
    logger.info("Serving the main PDF QA FastHTML app...")
    if pdf_qa_fasthtml_app is None:
        # Handle case where import failed
        logger.error("Cannot serve: FastHTML app from main.py failed to import.")
        # Optionally, return a simple error app here
        import fasthtml.common as fh

        error_app, error_rt = fh.fast_app()  # Get app and route decorator

        @error_rt("/")  # Use the route decorator associated with error_app
        def error_route():
            return fh.H1("Error: Application failed to load.")

        return error_app

    # --- Important Warnings for Modal Deployment ---
    logger.warning(
        "The underlying app in main.py uses a global dictionary (UPLOADS) for state."
    )
    logger.warning(
        "This WILL NOT work correctly with multiple Modal replicas and state will be lost."
    )
    logger.warning(
        "Consider using modal.Dict, NetworkFileSystem, or an external database for state."
    )
    logger.warning("The app also uses a local SQLite DB (pdf_qa_logs.db).")
    logger.warning(
        "This DB will be ephemeral unless a NetworkFileSystem is mounted at its location."
    )
    # --- End Warnings ---

    # Return the imported FastHTML app instance
    return pdf_qa_fasthtml_app


@app.local_entrypoint()
def main():
    """Local development entry point confirmation."""
    logger.info("Deployment script for main.py app defined.")
    if pdf_qa_fasthtml_app:
        logger.info("FastHTML app from main.py imported successfully.")
        try:
            # Get the registered name of the serving function
            serve_func_name = serve_main_app.info.name
            print(f"To run locally: modal serve deploy.py::{serve_func_name}")
        except Exception:
            print(f"To run locally: modal serve deploy.py::serve_main_app")
    else:
        logger.error("Could not import FastHTML app from main.py.")

from pathlib import Path

DATA_DIR_IN_CONTAINER = Path("/data")
DB_FILE = str(DATA_DIR_IN_CONTAINER / "pdf_qa_logs.db")

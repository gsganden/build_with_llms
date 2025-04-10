import asyncio
from datetime import datetime
from dotenv import load_dotenv
import sqlite3
import uuid

import fasthtml.common as fh
from google import genai
import fitz

load_dotenv("../.env")

app, rt = fh.fast_app()

DB_FILE = "pdf_qa_logs.db"


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


init_db()


def get_model_client():
    return genai.Client()


MODEL_CLIENT = get_model_client()

UPLOADS = {}


@rt("/")
def get():
    return fh.Titled(
        "Ask AI about a PDF",
        fh.Article(
            fh.H3("Step 1: Upload a PDF"),
            fh.Form(hx_post=upload_pdf, hx_target="#result")(
                fh.Input(type="file", name="pdf_file", accept="application/pdf"),
                fh.Button("Upload PDF", type="submit", cls="primary"),
            ),
            fh.Div(id="result"),
        ),
    )


@rt
async def upload_pdf(pdf_file: fh.UploadFile):
    if pdf_file.content_type != "application/pdf":
        return "Please upload a PDF file"

    pdf_id = str(uuid.uuid4())

    pdf_binary = await pdf_file.read()

    pdf_info = {
        "filename": pdf_file.filename,
        "size_bytes": len(pdf_binary),
        "content_type": pdf_file.content_type,
        "text": extract_text_from_pdf(pdf_binary),
    }
    UPLOADS[pdf_id] = pdf_info

    return fh.Article(
        fh.H3(f"PDF Uploaded: {pdf_info['filename']}"),
        fh.P(f"Size: {pdf_info['size_bytes']} bytes"),
        fh.Hr(),
        fh.H3("Ask questions about this PDF:"),
        fh.Form(hx_post=answer_question, hx_target="#answers")(
            fh.Hidden(value=pdf_id, name="pdf_id"),
            fh.Textarea(
                name="query",
                placeholder="Ask a question about the PDF...",
                rows=3,
                id="pdf-query",
            ),
            fh.Button("Submit Question", type="submit", cls="secondary"),
        ),
        fh.Div(id="answers"),
    )


def extract_text_from_pdf(pdf_bytes: bytes) -> str:
    pdf_doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    return "".join(
        pdf_doc.load_page(page_num).get_text("text")
        for page_num in range(pdf_doc.page_count)
    )


def log_interaction(pdf_name, query, response):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    interaction_id = str(uuid.uuid4())
    timestamp = datetime.now().isoformat()
    c.execute(
        "INSERT INTO interactions VALUES (?, ?, ?, ?, ?)",
        (interaction_id, timestamp, pdf_name, query, response),
    )
    conn.commit()
    conn.close()


@rt
async def answer_question(pdf_id: str, query: str):
    pdf_info = UPLOADS.get(pdf_id)

    if not pdf_info:
        return fh.Article(fh.P("PDF not found.", cls="error"))

    answer = await get_answer(query, pdf_info["text"])

    log_interaction(pdf_info["filename"], query, answer["text"])
    return fh.Article(
        fh.H4("Question:"),
        fh.P(query),
        fh.H4("Answer:"),
        fh.P(answer["text"]),
    )


async def get_answer(query, pdf_text):
    try:
        response = await asyncio.to_thread(
            MODEL_CLIENT.models.generate_content,
            model="gemini-2.0-flash",
            contents=create_prompt(query, pdf_text),
        )
        return {
            "success": True,
            "text": response.text,
        }
    except Exception as e:
        return {"success": False, "text": str(e)}


def create_prompt(query, pdf_text):
    return f"""
    The following is content from a PDF document: 
    {pdf_text}

    User's question about this document: {query}

    Please provide a clear and concise answer based only on the document content.
    """


fh.serve(reload=True)

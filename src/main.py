import asyncio
from datetime import datetime
import sqlite3
import uuid

import fasthtml.common as fh
from google import genai
import fitz

from constants import DB_FILE

app, rt = fh.fast_app()


def get_model_client():
    return genai.Client()


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
    if not pdf_file or pdf_file.content_type != "application/pdf":
        return fh.P("Please upload a valid PDF file", role="alert")

    pdf_binary = await pdf_file.read()
    pdf_text = extract_text_from_pdf(pdf_binary)

    return fh.Article(
        fh.H3(f"PDF Uploaded: {pdf_file.filename}"),
        fh.P(f"Size: {len(pdf_binary)} bytes"),
        fh.Hr(),
        fh.H3("Ask questions about this PDF:"),
        fh.Form(hx_post=answer_question, hx_target="#answers")(
            fh.Hidden(value=pdf_text, name="pdf_text"),
            fh.Hidden(value=pdf_file.filename, name="pdf_filename"),
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
async def answer_question(pdf_text: str, pdf_filename: str, query: str):
    answer = await get_answer(query, pdf_text)

    log_interaction(pdf_filename, query, answer["text"])
    return fh.Article(
        fh.H4("Question:"),
        fh.P(query),
        fh.H4("Answer:"),
        fh.P(answer["text"]),
    )


async def get_answer(query, pdf_text):
    try:
        response = await asyncio.to_thread(
            get_model_client().models.generate_content,
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


if __name__ == "__main__":
    fh.serve(reload=True)

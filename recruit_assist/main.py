import asyncio
from datetime import datetime
import hashlib
import logging
import sqlite3
import urllib
import uuid

import fasthtml.common as fh
from google import genai
import fitz

from recruit_assist.constants import DB_FILE

# Supports streaming model responses
SSE_HDR = fh.Script(src="https://unpkg.com/htmx-ext-sse@2.2.2/sse.js")

app, rt = fh.fast_app(hdrs=(SSE_HDR,))

STYLE = fh.Style("""
    .htmx-indicator{
        opacity:0;
        transition: opacity 200ms ease-in;
    }
    .htmx-request .htmx-indicator{
        opacity:1
    }
    .htmx-request.htmx-indicator{
        opacity:1
    }
""")

logger = logging.getLogger(__name__)


def get_model_client():
    return genai.Client()


@rt("/")
def get():
    return fh.Titled(
        "Ask AI about a PDF",
        fh.Article(
            fh.H3("Upload a PDF"),
            fh.Form(hx_post=upload_pdf, hx_target="#result")(
                fh.Input(type="file", name="pdf_file", accept="application/pdf"),
                fh.Button("Upload PDF", type="submit", cls="primary"),
                fh.Span("Uploading...", id="upload-indicator", cls="htmx-indicator"),
            ),
            fh.Div(id="result"),
        ),
    )


@rt
async def upload_pdf(pdf_file: fh.UploadFile):
    if not pdf_file or pdf_file.content_type != "application/pdf":
        return fh.P("Please upload a valid PDF file", role="alert")

    pdf_binary = await pdf_file.read()

    pdf_hash = hashlib.sha256(pdf_binary).digest()
    pdf_id = str(uuid.UUID(bytes=pdf_hash[:16]))
    logger.info("Generated PDF ID %s", pdf_id)

    try:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()

        c.execute("SELECT 1 FROM pdfs WHERE id = ?", (pdf_id,))
        exists = c.fetchone()

        if exists:
            logger.info("Cache hit: Found existing text for PDF ID %s in DB", pdf_id)
        else:
            logger.info("Cache miss: Extracting text for new PDF ID %s", pdf_id)
            c.execute(
                "INSERT INTO pdfs (id, filename, text) VALUES (?, ?, ?)",
                (pdf_id, pdf_file.filename, extract_text_from_pdf(pdf_binary)),
            )
            conn.commit()
            logger.info("Stored newly extracted PDF text with ID %s in DB", pdf_id)
    except sqlite3.Error as e:
        logger.error("SQLite error during PDF upload/check for ID %s: %s", pdf_id, e)
        conn.rollback()
        return fh.P("Error processing PDF", role="alert")
    finally:
        if conn:
            conn.close()

    return fh.Article(
        fh.H3(f"PDF Uploaded: {pdf_file.filename}"),
        fh.P(f"Size: {len(pdf_binary)} bytes"),
        fh.Hr(),
        fh.H3("Ask questions about this PDF:"),
        fh.Form(hx_post=answer_question, hx_target="#answers")(
            fh.Hidden(value=pdf_id, name="pdf_id"),
            fh.Hidden(value=pdf_file.filename, name="pdf_filename"),
            fh.Textarea(
                name="query",
                placeholder="Ask a question about the PDF...",
                rows=3,
                id="pdf-query",
            ),
            fh.Button("Submit Question", type="submit", cls="secondary"),
            fh.Span("Thinking...", id="question-indicator", cls="htmx-indicator"),
        ),
        fh.Div(id="answers"),
    )


def extract_text_from_pdf(pdf_bytes: bytes) -> str:
    pdf_doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    return "".join(
        pdf_doc.load_page(page_num).get_text("text")
        for page_num in range(pdf_doc.page_count)
    )


@rt
async def answer_question(pdf_id: str, pdf_filename: str, query: str):
    encoded_query = urllib.parse.quote(query)
    encoded_pdf_id = urllib.parse.quote(pdf_id)
    encoded_pdf_filename = urllib.parse.quote(pdf_filename)

    sse_url = f"/answer-stream?query={encoded_query}&pdf_id={encoded_pdf_id}&pdf_filename={encoded_pdf_filename}"

    return fh.Div(
        fh.H4("Question:"),
        fh.P(query),
        fh.H4("Answer:"),
        fh.Div(
            id="answer-content",
            hx_ext="sse",
            sse_connect=sse_url,
            sse_swap="message",
            sse_close="close",
            hx_swap="beforeend",
        ),
    )


@rt("/answer-stream")
async def answer_stream(query: str, pdf_id: str, pdf_filename: str):
    accumulated_response_for_log = ""

    async def event_generator():
        nonlocal accumulated_response_for_log
        pdf_text = None
        conn = None
        try:
            conn = sqlite3.connect(DB_FILE)
            c = conn.cursor()
            c.execute("SELECT text FROM pdfs WHERE id = ?", (pdf_id,))
            result = c.fetchone()

            if result:
                pdf_text = result[0]
                logger.info("Retrieved PDF text from DB for ID: %s", pdf_id)
            else:
                logger.error("PDF text not found in DB for ID: %s", pdf_id)
                yield fh.sse_error(
                    "Error: Could not find PDF text associated with this session in the database."
                )
                return
        except sqlite3.Error as e:
            logger.error("SQLite error retrieving text for ID %s: %s", pdf_id, e)
            yield fh.sse_error(f"Error retrieving PDF text from database")
            return  # Exit generation on DB error
        finally:
            if conn is not None:
                conn.close()

        if pdf_text is not None:
            try:
                async for chunk in get_answer(query, pdf_text):
                    if chunk:
                        accumulated_response_for_log += chunk
                        yield fh.sse_message(chunk)
                        await asyncio.sleep(0.01)
                    else:
                        logger.warning("Received empty chunk, skipping.")
            finally:
                if accumulated_response_for_log:
                    if not accumulated_response_for_log.startswith(
                        "Error during LLM generation:"
                    ) and not accumulated_response_for_log.startswith("Error:"):
                        log_interaction(pdf_id, query, accumulated_response_for_log)
                yield "event: close\ndata: \n\n"
        else:
            yield "event: close\ndata: \n\n"

    return fh.EventStream(event_generator())


async def get_answer(query, pdf_text):
    logger.info("Inside get_answer")
    try:
        model_client = get_model_client()
        response_stream = model_client.models.generate_content_stream(
            model="gemini-2.0-flash",
            contents=create_prompt(query, pdf_text),
        )
        logger.info("Got response_stream object")
        for chunk in response_stream:
            logger.info(f"Processing chunk in get_answer: {hasattr(chunk, 'text')}")
            if hasattr(chunk, "text") and chunk.text:
                yield chunk.text
            else:
                logger.warning("Chunk received without text or empty text.")

    except Exception as e:
        logger.error("!!! Error during LLM call in get_answer: %s", e, exc_info=True)
        yield "Error during LLM generation"


def create_prompt(query, pdf_text):
    return f"""
    The following is content from a PDF document: 
    {pdf_text}

    User's question about this document: {query}

    Please provide a clear and concise answer based only on the document content.
    """


def log_interaction(pdf_id, query, response):
    try:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        interaction_id = str(uuid.uuid4())
        timestamp = datetime.now().isoformat()
        c.execute(
            "INSERT INTO interactions VALUES (?, ?, ?, ?, ?)",
            (interaction_id, timestamp, pdf_id, query, response),
        )
        conn.commit()
    except sqlite3.Error as e:
        logger.error("SQLite error logging interaction for PDF ID %s: %s", pdf_id, e)
        if conn:
            conn.rollback()  # Rollback on error
    finally:
        if conn:
            conn.close()

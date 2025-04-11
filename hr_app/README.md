# HR App

My own WIP implementation of the HR app developed in the course.

## Significant Modifications

- Replaced `llama-index` with custom code for greater transparency and control.
- Replaced `gradio` with `fasthtml` for more flexibility.

## Commands

Deploy the app on the Modal platform:

```bash
modal deploy deploy.py
```

Run the app locally via the `modal` library:

```bash
modal serve deploy.py
```

Run the app directly:

```bash
python main.py
```

View local logs:

```bash
datasette pdf_qa_logs.db
```

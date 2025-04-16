# Recruiter Assistant

Recruiter assistant app, developed in [Building LLM Applications for Data Scientists and Software Engineers](https://maven.com/hugo-stefan/building-llm-apps-ds-and-swe-from-first-principles), cohort 2 (April 7 - May 3, 2025). Published with permission from the course instructors.

## Setup

```bash
uv sync
```

[Get a Gemini API key](https://aistudio.google.com/apikey) and assign its value to a `GOOGLE_API_KEY` environment variable and a Modal secret.

## Commands

Run the app locally via the `modal` library:

```bash
modal serve src/deploy.py
```

Deploy the app on the Modal platform:

```bash
modal deploy src/deploy.py
```

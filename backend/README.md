# GCC/CPC Compliance POC

Python **FastAPI** backend with rule/OCR-first PDF extraction, validation, traffic-light rating, reviewer UI (Jinja2), and audit logging.

## Quick start

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate   # Windows
pip install -r requirements.txt
# Optional: install Tesseract for OCR fallback when PDFs have no text layer
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

- **UI:** http://localhost:8000/review  
- **API docs:** http://localhost:8000/docs  
- **Default login:** `reviewer@poc.local` / `Reviewer123!`

## Configuration

| Env / `.env` | Description |
|--------------|-------------|
| `DATABASE_URL` | Default `sqlite+aiosqlite:///./poc_compliance.db` |
| `SECRET_KEY` | JWT signing secret |
| `CONFIDENCE_THRESHOLD` | Traffic-light threshold (default `0.75`) |
| `OCR_ENABLED` | `true`/`false` — OCR fallback if PDF text is sparse |
| `DOCUMENT_PROCESSOR` | `bedrock` (default) or `rule` |
| `AWS_REGION` | Bedrock runtime region (default `us-east-1`) |
| `BEDROCK_MODEL_ID` | Bedrock model id for extraction/text mapping |

Lab/CPSC lookup fixtures: [data/lab_accreditation.json](data/lab_accreditation.json).

Extraction mode flow:
1. OCR-first raw page text extraction from PDF
2. Send raw OCR payload to Bedrock for field mapping
3. Continue validation/rating pipeline

If Bedrock credentials/model access are not available, mapping automatically falls back to rule-based parsing and records the fallback reason in extraction justifications.

## Project layout

- `app/main.py` — app entry, seed user, routers
- `app/extraction/` — PDF text/OCR + heuristic field extractors
- `app/validation/` — pairing rules + citation checks + lab lookup hook
- `app/rating/` — green / yellow / red logic
- `app/services/` — storage, pipeline, audit
- `app/templates/` — reviewer pages
- `tests/` — pytest

## API highlights

- `POST /api/auth/token` — OAuth2 form (`username` = email, `password`)
- `POST /api/submissions` — multipart: `certificate`, `test_report`, optional `title`, `certificate_kind`
- `GET /api/submissions` — list (Bearer or `access_token` cookie from UI)
- `PATCH /api/submissions/{id}/extractions/{extraction_id}` — JSON body `{ "value_json": ... }`
- `GET /api/documents/{id}/file` — download original PDF

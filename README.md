# 🪞 Mirror Agent — YouCam (Perfect Corp) Hackathon Backend

Your mirror, but smarter. Upload a selfie, tell it what's coming up
("big interview tomorrow"), and it returns:

1. **Skin analysis** — shine / dryness / redness / dark-circles severity scores
2. **Plain-language read** — what those numbers actually mean for you today
3. **Focus areas** — the 2–3 things worth acting on tonight/tomorrow
4. **Styling intent** — an outfit direction chosen for the occasion
5. **Virtual try-on** — the garment rendered onto your photo (YouCam apparel VTO)
6. **Mirror briefing** — a markdown brief tying it all together

Skin analysis + try-on run on the **Perfect Corp YouCam API**; interpretation,
focus, and styling run on **Google Gemini** (REST, JSON mode).

---

## ⚠️ Honest status note

**The live YouCam API path has NOT been tested against the real service yet —
the operator's `YOUCAM_API_KEY` has not arrived.** Everything YouCam-facing is
implemented against the documented s2s v2.0 endpoints
([skin analysis](https://docs.perfectcorp.com/reference/ai_skin_analysis),
[apparel VTO](https://docs.perfectcorp.com/reference/ai_clothes)) and covered by
unit tests with **mocked HTTP**. Until the key lands, the app runs in
**demo mode**: canned skin scores, rule-based (or Gemini) advice, and a
PIL-generated placeholder try-on render — enough to build and demo the full
frontend experience today.

When the key arrives: `cp .env.example .env`, paste the key, restart, and the
same UI hits the live API. No code changes. If any live step then fails, the
agent degrades that step to demo and records the reason in the trace.

## Quick start

```bash
cd youcam-mirror-agent
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# no key needed — starts in demo mode
uvicorn app:app --reload --port 8000
# open http://127.0.0.1:8000
```

Or use the existing Hermes venv (already has all deps):

```bash
/Users/wendell/.hermes/hermes-agent/venv/bin/python -m uvicorn app:app --port 8000
```

### CLI demo (no server)

```bash
python mirror_agent.py "big interview tomorrow"     # prints a briefing to stdout
```

## Configuration

Keys are read **lazily** (env first, then `.env` in the project dir — never
committed). Nothing is required to run:

| Variable | Effect when missing |
|---|---|
| `YOUCAM_API_KEY` | Skin + VTO use canned demo data; response `mode: "demo"` |
| `GEMINI_API_KEY` | Interpretation/styling fall back to a deterministic rule-based advisor |

`GEMINI_API_KEY` also auto-resolves from
`/Users/wendell/zero-cash-revenue-engine/.env` if present (existing hackathon
stack, read-only).

## API

### `POST /briefing` (multipart)

| Field | Type | Notes |
|---|---|---|
| `photo` | file | selfie, jpg/png, <10MB, front-facing |
| `context` | form text | free-text occasion, e.g. "big interview tomorrow" |
| `garment_id` | form text | optional: `professional-blazer` / `full-body-smart` / `casual-upper` |

Returns JSON:

```jsonc
{
  "mode": "demo | live",
  "briefing_md": "# Mirror Briefing — ...",   // markdown
  "skin": { "overall": {...}, "concerns": { "shine": {...}, "dryness": {...},
             "redness": {...}, "dark_circles": {...} }, "extras": {...} },
  "interpretation": { "interpretation": "...", },
  "focus_areas": [ { "concern": "shine", "score": 62, "why": "...", "quick_fix": "..." } ],
  "styling": { "intent_name": "...", "description": "...", "garment_category": "..." },
  "vto": { "mode": "...", "result_url": "https://..." /* or demo_image data URL */ },
  "garment": { ... }, "trace": [ ...step-by-step execution trace... ]
}
```

### `GET /`

One-page demo UI: selfie upload, context input, garment picker, and a
side-by-side view of skin report bars + try-on render + the rendered briefing.

### `GET /healthz`

`{"status": "ok", "mode": "demo|live", "youcam_key_present": bool, "gemini_key_present": bool}`

## How it works

```
selfie + context
      │
      ▼
[1] YouCam skin analysis ── File API upload → task/skin-analysis → poll → reduce
      │                        (oiliness→shine, 100−moisture→dryness, redness,
      │                         dark_circle_v2→dark_circles; 0–100 severity)
      ▼
[2] Gemini interpretation ── numbers → plain-language read (JSON mode)
      ▼
[3] focus areas ──────────── top ≤3 concerns + quick fixes
      ▼
[4] Gemini styling intent ── occasion + focus → outfit direction
      ▼
[5] YouCam apparel VTO ──── task/cloth-v4 (user photo × garment ref) → render URL
      ▼
[6] mirror briefing ─────── deterministic markdown composition
```

Degradation matrix (every cell still returns a briefing):

| Missing / broken | Result |
|---|---|
| `YOUCAM_API_KEY` | demo skin + demo VTO placeholder (`mode: "demo"`) |
| YouCam live error mid-run | that step falls back to demo, reason kept in `trace` |
| `GEMINI_API_KEY` | rule-based interpretation + occasion-matched styling |
| Gemini call fails | same rule-based fallback, logged |

## Tests

31 unit tests, all HTTP mocked, no keys required:

```bash
/Users/wendell/.hermes/hermes-agent/venv/bin/python -m pytest tests/ -v
```

Covers: lazy key handling, File-API upload flow, skin pipeline (poll-success /
poll-error / HTTP errors / non-JSON / missing task_id), VTO (URL ref, uploaded
ref, arg validation), score reduction + clipping + dryness inversion, demo-mode
degradation, live pipeline with mocked YouCam+Gemini, per-step VTO-only
degradation, briefing composition, and the FastAPI endpoints end-to-end.

## Layout

```
youcam_client.py   Perfect Corp client: skin analysis + apparel VTO (lazy key)
mirror_agent.py    Gemini-orchestrated loop + rule-based fallbacks + briefing
app.py             FastAPI: POST /briefing, GET / (demo UI), GET /healthz
tests/             unit tests (mocked HTTP)
.env.example       copy to .env when the operator's key arrives
```

## References

- YouCam API docs: <https://docs.perfectcorp.com/develop/introduction>
- AI Skin Analysis: <https://docs.perfectcorp.com/reference/ai_skin_analysis>
- AI Clothes VTO: <https://docs.perfectcorp.com/reference/ai_clothes>
- API keys: <https://yce.makeupar.com/api-console/en/api-keys/>

*Built for the YouCam hackathon. Not affiliated with Perfect Corp.*

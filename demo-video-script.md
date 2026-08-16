# Mirror Agent — Demo Video Script (v2)

**Video:** `/tmp/mirror-agent-demo-v2.mp4` · **Runtime:** 2:29 · **Format:** 1920×1080, 30fps
**Style:** calm, confident, friendly — like showing a friend something you built. ~140 words/min.
**Rendered by:** `mirror_agent_video_v2.py` (screenshots captured live from the deployed app on Cloud Run).

> **Recording note:** Record each section into its own take, then cut to the timecodes below.
> Numbers read from the real demo run shown on screen (same selfie, same scores every run in demo mode).

---

## Timed narration

### [0:00–0:13] Hook — the problem
*(concept slide: "Every morning is a guess")*

> Every morning, millions of us walk up to a mirror and guess. Is my skin okay? Will this outfit land for the interview? We check, we second-guess, and we're already late. The mirror never answers back.

### [0:13–0:25] The product
*(live screenshot: landing page)*

> Meet Mirror Agent. It's a getting-ready briefing that takes twenty seconds of input and gives you a plan before you leave the mirror. It's live right now on Cloud Run — this is the actual app.

### [0:25–0:37] Step 1 — input
*(screenshot: form filled with selfie + "big interview tomorrow")*

> Step one: one selfie, and one sentence about your day — here, "big interview tomorrow." That's everything the user does. The agent decides everything else, chaining two YouCam APIs and Gemini behind a single button.

### [0:37–0:49] Step 2 — Skin AI
*(screenshot: skin report card — shine 62, dark circles 55, dryness 38, redness 29)*

> First, YouCam Skin AI reads the face objectively: shine sixty-two, dark circles fifty-five, dryness thirty-eight. No vibes — scored, consistent, and each concern comes with a quick fix you can actually do tonight.

### [0:49–1:01] Step 3 — the agent interprets
*(screenshot: full briefing, "Executive Polish")*

> Then Gemini turns those numbers into a plan *for this occasion*. Interview tomorrow? Executive Polish: a structured blazer, navy or charcoal, and a morning-of checklist that starts with dabbing powder on the T-zone. Focus areas, styling intent, colors — decided, not templated.

### [1:01–1:13] Step 4 — Apparel VTO
*(screenshot: try-on column, selfie vs. render)*

> The styling intent drives YouCam Apparel VTO, so you see the look on your own photo before you commit. No more outfit roulette in front of the closet.

### [1:13–1:27] The payoff — context is everything
*(screenshot: beach-day briefing, "Seaside Casual Chic")*

> And here's the proof it's really an agent. Same face, same skin scores — but change one word to "beach day," and the entire briefing rewrites itself: Seaside Casual Chic, SPF-first fixes, pastel color notes. A template can't do that. Context can.

### [1:27–1:39] The whole briefing
*(screenshot: full results page, two-column layout)*

> Here's the whole thing on one page: skin report, focus areas, styling intent, try-on, and the morning-of checklist. Generated end-to-end in about four seconds.

### [1:39–1:52] Under the hood
*(concept slide: "Not a wrapper — a decision loop")*

> Under the hood it's a decision loop, not a wrapper. Skin analysis feeds interpretation; interpretation drives styling; styling drives try-on; and every step lands in the briefing. It degrades gracefully — no YouCam key, it runs in demo mode. Zero keys to try it.

### [1:52–2:05] Try it
*(concept slide: "Try it now")*

> The demo is live on Cloud Run, the repo is open source, and one environment variable — YouCam API key — flips the entire pipeline to live YouCam renders.

### [2:05–2:16] Close
*(concept slide: "Walk out confident.")*

> Mirror Agent: walk out confident. Built with YouCam Skin AI, Apparel VTO, and Gemini at the YouCam hackathon. Thanks for watching.

---

## On-screen ↔ narration alignment

| Time | Slide | Screenshot | Key line |
|---|---|---|---|
| 0:00 | Every morning is a guess | — | "The mirror never answers back." |
| 0:13 | Live on Cloud Run | `01-landing.png` | "This is the actual app." |
| 0:25 | 20 seconds of input | `02-form-filled.png` | "One selfie, one sentence." |
| 0:37 | Skin AI | `04-skin-report.png` | "Scored, consistent, quick fixes." |
| 0:49 | The agent thinks | `06-briefing.png` | "Executive Polish — decided, not templated." |
| 1:01 | Apparel VTO | `05-vto.png` | "See the look before you commit." |
| 1:13 | Same face, different day | `07-briefing-beach.png` | "A template can't do that. Context can." |
| 1:27 | The whole briefing | `03-results-full.png` | "One page, ~4 seconds." |
| 1:39 | Decision loop | — | "Not a wrapper." |
| 1:52 | Try it now | — | "One env var to live mode." |
| 2:05 | Walk out confident. | — | "Walk out confident." |

## Voiceover tips
- Read **"Seaside Casual Chic"** and **"Executive Polish"** as product names — slight pause before each.
- The [1:13] beat is the money moment — slow down, let the beach screenshot sit.
- Target 140 wpm; if a take runs long, trim adjectives, never the numbers (62 / 55 / 38 / 29 / 74).

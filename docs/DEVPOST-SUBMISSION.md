# Devpost Submission — YouCam API Hackathon

**Challenge:** youcam-api.devpost.com (challenge id 30518) — registered
**Deadline:** Monday 1:00 PM PDT

---

## Title

**Mirror Agent — Your 20-Second Getting-Ready Briefing**

---

## Description (~280 words — paste into Devpost)

Every morning, millions of us walk up to a mirror and guess. Is my skin okay? Will this outfit land for the interview? Mirror Agent takes twenty seconds of input — one selfie and one sentence about your day — and returns a complete getting-ready briefing before you leave the mirror.

Under the hood it's a decision loop, not a wrapper. First, the **YouCam Skin AI API** reads the face objectively: shine, dark circles, dryness, and redness come back as consistent scores instead of vibes, and each concern carries a quick fix you can actually do tonight. Then **Gemini** turns those numbers into a plan for *this specific occasion* — focus areas, styling intent, color direction, and a morning-of checklist. That styling intent then drives the **YouCam Apparel VTO API**, so you see the recommended look rendered on your own photo before you commit — no more outfit roulette in front of the closet.

The proof it's really an agent: same face, same skin scores — change one word from "big interview tomorrow" to "beach day" and the entire briefing rewrites itself. Executive Polish with a structured charcoal blazer becomes Seaside Casual Chic with SPF-first fixes and pastel color notes. A template can't do that; context can.

The whole pipeline — analysis, interpretation, styling, try-on — lands on one page in about four seconds. It's live on Cloud Run right now, and it degrades gracefully: with no API key it runs in demo mode so anyone can try it with zero setup. One environment variable flips the entire pipeline to live YouCam renders.

Built with YouCam Skin AI, YouCam Apparel VTO, and Gemini. Walk out confident.

**Try it live:** https://mirror-agent-1087493193698.us-west1.run.app

---

## Video URL

https://youtu.be/puJPuU0hurc

---

## Repo URL

https://github.com/jtabsbm/mirror-agent

---

## Screenshots (raw.githubusercontent URLs)

1. Landing page (live app): https://raw.githubusercontent.com/jtabsbm/mirror-agent/main/docs/screenshots/01-landing.png
2. 20-second input (selfie + one sentence): https://raw.githubusercontent.com/jtabsbm/mirror-agent/main/docs/screenshots/02-form-filled.png
3. YouCam Skin AI report (scored concerns + quick fixes): https://raw.githubusercontent.com/jtabsbm/mirror-agent/main/docs/screenshots/04-skin-report.png
4. YouCam Apparel VTO try-on (selfie vs. render): https://raw.githubusercontent.com/jtabsbm/mirror-agent/main/docs/screenshots/05-vto.png
5. Same face, different day — beach briefing rewrites itself: https://raw.githubusercontent.com/jtabsbm/mirror-agent/main/docs/screenshots/07-briefing-beach.png

*(Spares, also in the repo: `03-results-full.png` full one-page briefing, `06-briefing.png` Executive Polish briefing.)*

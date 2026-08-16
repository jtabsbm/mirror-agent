"""
mirror_agent.py — the Gemini-orchestrated "Mirror Agent" loop.

Input : a selfie (bytes) + free-text user context (e.g. "big interview tomorrow")
Output: a "mirror briefing" (markdown) + structured intermediates the demo UI
        renders side-by-side (skin report, VTO render, focus areas).

Pipeline:
    1. skin analysis        (YouCam API  -> concerns JSON)
    2. interpretation       (Gemini      -> plain-language read of the numbers)
    3. focus areas          (Gemini      -> top 2-3 concerns worth acting on)
    4. styling intent       (Gemini      -> outfit direction for the occasion)
    5. VTO render           (YouCam API  -> garment composited onto the selfie)
    6. mirror briefing      (code        -> deterministic markdown composition)

Graceful degradation (the hackathon-critical property):
    * No YOUCAM_API_KEY  -> steps 1 & 5 use canned demo data (DEMO_SKIN_ANALYSIS
      + a PIL-generated placeholder "render"), so the frontend can be built and
      demoed before the key arrives. Every response is tagged mode="demo".
    * No GEMINI_API_KEY (or Gemini errors) -> steps 2-4 fall back to a
      deterministic rule-based advisor. Briefing always renders.
    * Live YouCam errors mid-run -> the run degrades to demo for that step and
      records the failure in the trace instead of crashing.

Gemini is called via the REST API directly (same pattern as
zero-cash-revenue-engine/hackathon/gemini_lead_agent.py) — no SDK dependency.
"""

from __future__ import annotations

import base64
import io
import json
import os
import re
import urllib.request
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

import youcam_client
from youcam_client import (
    DEMO_SKIN_ANALYSIS,
    DEMO_VTO_RESULT,
    YouCamClient,
    YouCamError,
    YouCamKeyMissing,
)

HERE = Path(__file__).resolve().parent

# Extra fallback location for GEMINI_API_KEY (existing hackathon stack).
ZERO_CASH_ENV = Path("/Users/wendell/zero-cash-revenue-engine/.env")

GEMINI_MODELS = [
    "gemini-3.5-flash",
    "gemini-3.5-flash-lite",
    "gemini-3-flash-preview",
    "gemini-flash-latest",
]


# ---------------------------------------------------------------------------
# Gemini helper (REST, JSON mode) — mirrors gemini_lead_agent.py
# ---------------------------------------------------------------------------

def _resolve_gemini_key() -> Optional[str]:
    if os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"):
        return os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    # local .env then the existing hackathon stack's .env (read-only)
    for path in (HERE / ".env", Path.cwd() / ".env", ZERO_CASH_ENV):
        try:
            if not path.is_file():
                continue
            for line in path.read_text().splitlines():
                line = line.strip()
                if line.startswith("GEMINI_API_KEY=") or line.startswith("GOOGLE_API_KEY="):
                    value = line.partition("=")[2].strip().strip('"').strip("'")
                    if value:
                        return value
        except OSError:
            continue
    return None


class GeminiAdvisor:
    """Answers structured JSON questions; falls back silently on any failure."""

    def __init__(self, api_key: Optional[str] = None):
        self._key = api_key or _resolve_gemini_key()
        self.model: Optional[str] = None
        self.available = bool(self._key)

    def _call(self, system: str, prompt: str, timeout: int = 45) -> Optional[dict]:
        if not self._key:
            return None
        models = [self.model] if self.model else GEMINI_MODELS
        body = {
            "system_instruction": {"parts": [{"text": system}]},
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"responseMimeType": "application/json", "temperature": 0.4},
        }
        last_err = None
        for model in models:
            url = (
                "https://generativelanguage.googleapis.com/v1beta/models/"
                f"{model}:generateContent?key={self._key}"
            )
            req = urllib.request.Request(
                url, data=json.dumps(body).encode(),
                headers={"Content-Type": "application/json"},
            )
            try:
                with urllib.request.urlopen(req, timeout=timeout) as r:
                    data = json.loads(r.read().decode())
                text = data["candidates"][0]["content"]["parts"][0]["text"]
                parsed = json.loads(text)
                if isinstance(parsed, dict):
                    self.model = model
                    return parsed
            except Exception as e:  # noqa: BLE001 — any failure -> fallback
                last_err = e
                continue
        if last_err:
            print(f"[mirror-agent] Gemini unavailable ({str(last_err)[:100]}) — using rule-based fallback")
        return None


# ---------------------------------------------------------------------------
# Rule-based fallback advisor (no Gemini required)
# ---------------------------------------------------------------------------

OCCASION_RULES = [
    (re.compile(r"interview|hiring|recruiter|job|career|presentation|pitch|investor", re.I), {
        "intent_name": "Polished Professional",
        "description": "A structured navy blazer over a crisp light shirt — reads as competent and calm on camera and in the room.",
        "garment_category": "upper_body",
        "color_notes": "Navy + white; keep jewellery minimal and matte.",
        "quick_wins": ["Blot T-zone, then a thin veil of translucent powder", "Cool compress or eye drops for dark circles", "Concealer only where needed — less reads better in person"],
    }),
    (re.compile(r"date|dinner|romantic|anniversary", re.I), {
        "intent_name": "Warm Evening",
        "description": "Soft textures and a warm accent piece — relaxed but intentional.",
        "garment_category": "upper_body",
        "color_notes": "Earth tones or deep jewel tones; skip stiff collars.",
        "quick_wins": ["Hydrate cheeks so skin reads dewy, not dry", "Dab concealer on dark circles", "Set only the T-zone"],
    }),
    (re.compile(r"party|birthday|celebration|wedding|night out|club", re.I), {
        "intent_name": "Camera-Ready Bold",
        "description": "A statement piece with clean lines — photographs well under mixed lighting.",
        "garment_category": "upper_body",
        "color_notes": "One bold hue; let the garment carry the look.",
        "quick_wins": ["Prime the T-zone — flash picks up shine", "Brighten under-eyes one shade", "Blush for photos"],
    }),
    (re.compile(r"meeting|standup|client|zoom|video call|call", re.I), {
        "intent_name": "Clean On-Camera",
        "description": "A plain, well-fitted top in a solid mid-tone — webcams flatten patterns, so keep it simple.",
        "garment_category": "upper_body",
        "color_notes": "Mid-tone solids (slate, forest, burgundy) flatter on webcam.",
        "quick_wins": ["Light from the front, not behind", "Powder the forehead before joining", "Look at the lens for eye contact"],
    }),
]

DEFAULT_INTENT = {
    "intent_name": "Everyday Polish",
    "description": "A clean, well-fitted layer that lifts the whole look without effort.",
    "garment_category": "upper_body",
    "color_notes": "Neutral base, one accent.",
    "quick_wins": ["Morning moisturiser before anything else", "Blot shine midday", "Sleep beats any serum"],
}


def _rule_interpretation(skin: Dict[str, Any], context: str) -> Dict[str, Any]:
    concerns = skin.get("concerns") or {}
    scored = [
        (name, info.get("score") or 0)
        for name, info in concerns.items()
        if isinstance(info, dict)
    ]
    scored.sort(key=lambda x: x[1], reverse=True)
    top = scored[:3]

    phrases = {
        "shine": "your T-zone is running oily, so shine will show up in photos and under bright office lights",
        "dryness": "your cheeks are on the dry side, which makeup can grab onto and make look patchy",
        "redness": "there's mild redness concentrated around the nose and cheeks",
        "dark_circles": "your under-eyes read tired — dark circles are the most noticeable concern right now",
    }
    sentences = []
    for name, score in top:
        if score >= 40 and name in phrases:
            sentences.append(phrases[name])
    if not sentences:
        sentences.append("your skin is in solid shape — nothing needs urgent attention")
    overall = (skin.get("overall") or {}).get("ui_score")
    if overall is not None:
        sentences.insert(0, f"Overall your skin scores {overall}/100.")

    return {
        "interpretation": " ".join(sentences).strip(),
        "focus_areas": [
            {"concern": name, "score": score,
             "why": phrases.get(name, f"{name} scored {score}/100"),
             "quick_fix": _quick_fix(name)}
            for name, score in top
        ],
    }


def _quick_fix(concern: str) -> str:
    return {
        "shine": "Blot, don't wipe, then a light translucent powder on the T-zone.",
        "dryness": "Hydrating moisturiser now and again in the morning; exfoliate gently tonight.",
        "redness": "Cool rinse, fragrance-free moisturiser, and skip actives tonight.",
        "dark_circles": "Cool compress for 2 minutes, then a peach-toned concealer tapped in (don't rub).",
    }.get(concern, "A consistent cleanse–moisturise routine tonight.")


def _rule_styling(context: str) -> Dict[str, Any]:
    for pattern, intent in OCCASION_RULES:
        if pattern.search(context or ""):
            return intent
    return DEFAULT_INTENT


# ---------------------------------------------------------------------------
# Garment catalog — Perfect Corp doc sample assets (public URLs).
# Swappable for curated product shots once the live key arrives.
# ---------------------------------------------------------------------------

GARMENT_CATALOG: List[Dict[str, str]] = [
    {
        "id": "professional-blazer",
        "label": "Professional blazer look",
        "category": "upper_body",
        "url": "https://plugins-media.makeupar.com/strapi/assets/clothes_03_cccd5d4803.jpeg",
    },
    {
        "id": "full-body-smart",
        "label": "Full-body smart outfit",
        "category": "full_body",
        "url": "https://plugins-media.makeupar.com/strapi/assets/clothes_reference_full_body_01_5a000d999f.png",
    },
    {
        "id": "casual-upper",
        "label": "Casual upper-body layer",
        "category": "upper_body",
        "url": "https://plugins-media.makeupar.com/strapi/assets/clothes_03_cccd5d4803.jpeg",
    },
]


def pick_garment(intent: Dict[str, Any]) -> Dict[str, str]:
    """Choose the catalog garment matching the styling intent's category."""
    category = intent.get("garment_category") or "upper_body"
    for g in GARMENT_CATALOG:
        if g["category"] == category:
            return g
    return GARMENT_CATALOG[0]


# ---------------------------------------------------------------------------
# Demo VTO placeholder (PIL) — gives the UI something honest to render
# ---------------------------------------------------------------------------

def demo_vto_image(selfie_bytes: Optional[bytes], garment_label: str) -> Optional[str]:
    """Composite a clearly-labelled DEMO overlay on the selfie -> data URL."""
    try:
        from PIL import Image, ImageDraw

        img = Image.open(io.BytesIO(selfie_bytes or b"")).convert("RGB")
    except Exception:
        try:
            img = Image.new("RGB", (480, 640), (24, 28, 38))
        except Exception:
            return None
    img.thumbnail((640, 640))
    w, h = img.size
    draw = ImageDraw.Draw(img, "RGBA")

    # translucent navy "garment" band over the lower part of the frame
    band_top = int(h * 0.62)
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    odraw = ImageDraw.Draw(overlay)
    odraw.rectangle([0, band_top, w, h], fill=(28, 44, 82, 130))
    img = Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")
    draw = ImageDraw.Draw(img)

    banner = f"DEMO RENDER · {garment_label[:48]}"
    draw.rectangle([0, h - 34, w, h], fill=(12, 14, 20, 255))
    draw.text((10, h - 26), banner, fill=(240, 240, 240))

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


# ---------------------------------------------------------------------------
# Briefing composition (deterministic markdown)
# ---------------------------------------------------------------------------

def compose_briefing(
    context: str,
    skin: Dict[str, Any],
    interpretation: Dict[str, Any],
    styling: Dict[str, Any],
    vto: Dict[str, Any],
    mode: str,
    gemini_model: Optional[str],
) -> str:
    concerns = skin.get("concerns") or {}
    focus = interpretation.get("focus_areas") or []
    overall = (skin.get("overall") or {}).get("ui_score")
    intent_name = styling.get("intent_name", "Everyday Polish")

    def bar(score) -> str:
        if not isinstance(score, (int, float)):
            return "—"
        filled = int(round(score / 10))
        return "█" * filled + "░" * (10 - filled) + f" {int(score)}/100"

    lines: List[str] = []
    badge = "🪞 LIVE" if mode == "live" else "🎬 DEMO MODE"
    lines.append(f"# Mirror Briefing — {intent_name}")
    lines.append("")
    lines.append(f"> **Occasion:** {context or 'your day ahead'}  ")
    lines.append(f"> **Mode:** {badge} · **Advisor:** {gemini_model or 'rule-based fallback'}"
                 + (f" · **Overall skin:** {overall}/100" if overall is not None else ""))
    lines.append("")
    lines.append("## The read")
    lines.append(interpretation.get("interpretation") or "")
    lines.append("")

    if focus:
        lines.append("## Focus areas")
        for f in focus[:3]:
            lines.append(f"- **{f.get('concern', '?').replace('_', ' ').title()}** ({f.get('score', '?')}/100) — {f.get('why', '')}")
            if f.get("quick_fix"):
                lines.append(f"  - *Quick fix:* {f['quick_fix']}")
        lines.append("")

    lines.append("## Skin numbers")
    lines.append("| Concern | Severity | Score |")
    lines.append("|---|---|---|")
    for name in ("shine", "dryness", "redness", "dark_circles"):
        info = concerns.get(name) or {}
        label = (info.get("label") or "not measured").replace("_", " ")
        lines.append(f"| {name.replace('_', ' ').title()} | {label} | {bar(info.get('score'))} |")
    lines.append("")

    lines.append("## Styling intent")
    lines.append(f"**{intent_name}** — {styling.get('description', '')}")
    if styling.get("color_notes"):
        lines.append("")
        lines.append(f"*Color notes:* {styling['color_notes']}")
    lines.append("")

    lines.append("## Try-on")
    if vto.get("result_url"):
        lines.append(f"Rendered with YouCam apparel VTO: {vto['result_url']}")
    else:
        lines.append(
            "_Demo mode — the garment is visualised as a placeholder overlay. "
            "Set `YOUCAM_API_KEY` in `.env` to render a real AI try-on._"
        )
    lines.append("")

    wins = styling.get("quick_wins") or []
    if wins:
        lines.append("## Morning-of checklist")
        for i, w in enumerate(wins, 1):
            lines.append(f"{i}. {w}")
        lines.append("")

    if mode == "demo":
        lines.append("---")
        lines.append("*This briefing was generated in demo mode with canned skin data. "
                     "Numbers are illustrative until `YOUCAM_API_KEY` is configured.*")
    return "\n".join(lines).strip() + "\n"


# ---------------------------------------------------------------------------
# The agent
# ---------------------------------------------------------------------------

@dataclass
class BriefingResult:
    mode: str                                   # "live" | "demo"
    briefing_md: str
    skin: Dict[str, Any]
    interpretation: Dict[str, Any]
    focus_areas: List[Dict[str, Any]]
    styling: Dict[str, Any]
    vto: Dict[str, Any]
    garment: Dict[str, Any]
    gemini_model: Optional[str] = None
    trace: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        return d


class MirrorAgent:
    """Orchestrates YouCam + Gemini into a mirror briefing. Never raises for
    missing keys — always returns a (possibly demo-mode) BriefingResult."""

    def __init__(
        self,
        youcam: Optional[YouCamClient] = None,
        gemini: Optional[GeminiAdvisor] = None,
    ):
        self.youcam = youcam or YouCamClient(poll_interval=2.0)
        self.gemini = gemini or GeminiAdvisor()

    # -- step 1: skin analysis ------------------------------------------------

    def _step_skin(self, selfie_bytes: bytes, trace: List[Dict[str, Any]]) -> Dict[str, Any]:
        try:
            skin = self.youcam.analyze_skin(selfie_bytes)
            trace.append({"step": "skin_analysis", "status": "live", "task_id": skin.get("task_id")})
            return skin
        except YouCamKeyMissing:
            trace.append({"step": "skin_analysis", "status": "demo", "reason": "YOUCAM_API_KEY not set"})
            return json.loads(json.dumps(DEMO_SKIN_ANALYSIS))  # deep copy
        except (YouCamError, Exception) as e:  # noqa: BLE001 — degrade, don't crash
            trace.append({"step": "skin_analysis", "status": "demo", "reason": f"live error: {str(e)[:160]}"})
            return json.loads(json.dumps(DEMO_SKIN_ANALYSIS))

    # -- steps 2+3: interpretation + focus areas (one Gemini call) --------------

    INTERP_SYSTEM = (
        "You are the Mirror Agent: a warm, concise image-and-style coach. "
        "You receive skin-analysis concern severities (0-100, higher = MORE of the "
        "concern: shine, dryness, redness, dark_circles) and the user's occasion. "
        "Reply ONLY with JSON: "
        '{"interpretation": "2-4 plain-language sentences, no numbers, kind but honest", '
        '"focus_areas": [{"concern": "one of shine|dryness|redness|dark_circles", '
        '"score": <int>, "why": "<=12 words", "quick_fix": "one actionable tip doable tonight or tomorrow morning"}]} '
        "Pick at most 3 focus areas, highest severity first. Never invent medical claims."
    )

    def _step_interpret(self, skin: Dict[str, Any], context: str, trace: List[Dict[str, Any]]) -> Dict[str, Any]:
        prompt = (
            f"User context: {context or 'general day ahead'}\n\n"
            f"Skin analysis JSON:\n{json.dumps(skin.get('concerns', {}), indent=2)}\n\n"
            f"Overall: {json.dumps(skin.get('overall', {}))}"
        )
        out = self.gemini._call(self.INTERP_SYSTEM, prompt)
        if out and out.get("interpretation") and isinstance(out.get("focus_areas"), list):
            trace.append({"step": "interpretation", "status": "gemini", "model": self.gemini.model})
            return out
        trace.append({"step": "interpretation", "status": "rule-based"})
        return _rule_interpretation(skin, context)

    # -- step 4: styling intent --------------------------------------------------

    STYLE_SYSTEM = (
        "You are the Mirror Agent's stylist. Given the user's occasion and their "
        "skin focus areas, choose one styling intent for an apparel virtual try-on. "
        "Reply ONLY with JSON: "
        '{"intent_name": "<=3 words", '
        '"description": "1-2 sentences on the outfit direction and why it suits the occasion", '
        '"garment_category": "upper_body|full_body", '
        '"color_notes": "one sentence", '
        '"quick_wins": ["3 short morning-of prep steps"]}. '
        "Be specific to the occasion; never recommend medical treatment."
    )

    def _step_styling(self, context: str, focus: List[Dict[str, Any]], trace: List[Dict[str, Any]]) -> Dict[str, Any]:
        prompt = (
            f"User context: {context or 'general day ahead'}\n"
            f"Focus areas: {json.dumps(focus[:3])}"
        )
        out = self.gemini._call(self.STYLE_SYSTEM, prompt)
        if out and out.get("intent_name"):
            trace.append({"step": "styling_intent", "status": "gemini", "model": self.gemini.model})
            base = _rule_styling(context)
            base.update({k: v for k, v in out.items() if v})
            return base
        trace.append({"step": "styling_intent", "status": "rule-based"})
        return _rule_styling(context)

    # -- step 5: VTO ---------------------------------------------------------------

    def _step_vto(
        self,
        selfie_bytes: bytes,
        styling: Dict[str, Any],
        garment: Dict[str, str],
        skin_mode: str,
        trace: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        if skin_mode == "live":
            try:
                vto = self.youcam.render_apparel_vto(
                    selfie_bytes,
                    garment_url=garment["url"],
                    garment_category=garment["category"],
                )
                vto["garment"] = garment["label"]
                trace.append({"step": "vto", "status": "live", "task_id": vto.get("task_id")})
                return vto
            except (YouCamError, Exception) as e:  # noqa: BLE001
                trace.append({"step": "vto", "status": "demo", "reason": f"live error: {str(e)[:160]}"})
        else:
            trace.append({"step": "vto", "status": "demo", "reason": "no API key (demo mode)"})

        demo = json.loads(json.dumps(DEMO_VTO_RESULT))
        demo["garment"] = garment["label"]
        demo["demo_image"] = demo_vto_image(selfie_bytes, garment["label"])
        return demo

    # -- full loop -------------------------------------------------------------------

    def run(
        self,
        selfie_bytes: bytes,
        context: str = "",
        garment: Optional[Dict[str, str]] = None,
    ) -> BriefingResult:
        trace: List[Dict[str, Any]] = []

        # 1. skin analysis
        skin = self._step_skin(selfie_bytes, trace)
        mode = "live" if skin.get("mode") == "live" else "demo"

        # 2+3. plain-language interpretation + focus areas
        interpretation = self._step_interpret(skin, context, trace)

        # 4. styling intent
        styling = self._step_styling(context, interpretation.get("focus_areas") or [], trace)

        # 5. VTO render (or demo placeholder)
        chosen_garment = garment or pick_garment(styling)
        vto = self._step_vto(selfie_bytes, styling, chosen_garment, mode, trace)

        # 6. compose the mirror briefing
        briefing_md = compose_briefing(
            context, skin, interpretation, styling, vto, mode, self.gemini.model
        )
        trace.append({"step": "briefing", "status": "composed", "mode": mode})

        return BriefingResult(
            mode=mode,
            briefing_md=briefing_md,
            skin=skin,
            interpretation=interpretation,
            focus_areas=interpretation.get("focus_areas") or [],
            styling=styling,
            vto=vto,
            garment=chosen_garment,
            gemini_model=self.gemini.model if mode == "live" or self.gemini.model else None,
            trace=trace,
        )


# ---------------------------------------------------------------------------
# CLI demo: python mirror_agent.py ["big interview tomorrow"]
# ---------------------------------------------------------------------------

def _cli() -> None:
    import sys

    context = " ".join(sys.argv[1:]) or "big interview tomorrow"
    # tiny synthetic selfie so the demo runs without a real photo
    try:
        from PIL import Image

        buf = io.BytesIO()
        Image.new("RGB", (480, 640), (120, 100, 90)).save(buf, format="JPEG")
        selfie = buf.getvalue()
    except Exception:
        selfie = b""

    agent = MirrorAgent()
    result = agent.run(selfie, context)
    print(result.briefing_md)
    print("─" * 60)
    print("trace:", json.dumps(result.trace, indent=2))


if __name__ == "__main__":
    _cli()

#!/usr/bin/env python3
"""mirror_agent_video.py — renders the Mirror Agent demo video (1-3 min spec).

Slide-based like render_video_slides.py (ffmpeg, no browser): 8 slides at
~14s each ≈ 1:52, with narration lines printed as a script alongside.
Output: /tmp/mirror-agent-demo.mp4
"""
import subprocess
import sys
from pathlib import Path

OUT = Path("/tmp/mirror-agent-demo.mp4")
W, H = 1280, 720
DARK = "0b1020"
ACCENT = "9fe870"
TEXT = "f0f4ff"
MUTED = "96a0c2"

SLIDES = [
    ("Mirror Agent", "Your getting-ready briefing — before you leave the mirror",
     "Upload one selfie. Tell it what tomorrow is. Get a plan."),
    ("The problem", "The mirror moment is a guess",
     "Is my skin okay? Does this work for an interview? Guesswork, every morning."),
    ("How it works", "One agent, two APIs, one briefing",
     "Skin AI analysis -> Gemini interpretation -> styling intent -> Apparel VTO -> briefing"),
    ("Step 1 — Skin AI", "Objective skin reading, plain language",
     "shine / dryness / redness / dark circles scored 0-100, then explained like a friend would"),
    ("Step 2 — The agent", "Gemini decides what actually matters",
     "'Interview tomorrow' prioritizes differently than 'beach day'. Context-aware, not a template."),
    ("Step 3 — Apparel VTO", "See the look before you commit",
     "The agent picks the styling intent; VTO renders it on your photo. No more outfit roulette."),
    ("The briefing", "Everything in one place",
     "Skin report + focus areas + side-by-side try-on + what to do about it. 20 seconds, done."),
    ("Built agentic", "Not a wrapper — a decision loop",
     "Skin analysis feeds interpretation, interpretation drives styling, styling drives VTO. The APIs chain through an agent. Demo mode runs with zero keys; live mode is a single env var away."),
]


def slide_png(i, title, sub, body):
    """Render with PIL (this ffmpeg build lacks drawtext/freetype)."""
    from PIL import Image, ImageDraw, ImageFont
    f = f"/tmp/mirror-slide-{i}.png"
    img = Image.new("RGB", (W, H), (0x0B, 0x10, 0x20))
    d = ImageDraw.Draw(img)
    font_title = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 52)
    font_sub = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 30)
    font_body = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 24)
    d.text((80, 190), title, font=font_title, fill=(0x9F, 0xE8, 0x70))
    d.text((80, 290), sub, font=font_sub, fill=(0xF0, 0xF4, 0xFF))
    # simple word-wrap for body
    words, line, y = body.split(), "", 380
    for w_ in words:
        if d.textlength(line + w_, font=font_body) > W - 160:
            d.text((80, y), line, font=font_body, fill=(0x96, 0xA0, 0xC2)); y += 34; line = w_ + " "
        else:
            line += w_ + " "
    d.text((80, y), line, font=font_body, fill=(0x96, 0xA0, 0xC2))
    img.save(f)
    return f


def main():
    files = [slide_png(i, *s) for i, s in enumerate(SLIDES)]
    dur = 14
    concat = Path("/tmp/mirror-concat.txt")
    concat.write_text("".join(f"file '{f}'\nduration {dur}\n" for f in files) + f"file '{files[-1]}'\n")
    r = subprocess.run([
        "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat),
        "-vf", "fade=t=in:st=0:d=0.5,fade=t=out:st=110:d=2",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", "30", str(OUT)
    ], capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stderr[-500:]); sys.exit(1)
    print(f"OK {OUT} ({OUT.stat().st_size//1024} KB, ~{len(SLIDES)*dur}s)")
    print("\nNARRATION SCRIPT (for the voiced version):")
    for i, (t, s, b) in enumerate(SLIDES):
        print(f"[{i*dur}s] {t}: {b}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""mirror_agent_video_v2.py — renders the Mirror Agent demo video v2 (~2:30).

Real app screenshots (dedicated headless Chrome on the live Cloud Run URL)
composited with caption/title slides via PIL, concatenated with ffmpeg.

Narrative arc:
  1. Hook / problem           (concept)      ~15s
  2. Product intro            (real UI)      ~15s
  3. Step-by-step flow        (real UI x4)   ~60s
  4. Context switch payoff    (real UI x2)   ~30s
  5. Tech + close             (concept x2)   ~30s

Output: /tmp/mirror-agent-demo-v2.mp4
"""
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT = Path("/tmp/mirror-agent-demo-v2.mp4")
W, H = 1920, 1080
BG = (11, 16, 32)
PANEL = (22, 27, 38)
LINE = (42, 51, 72)
ACCENT = (0x9F, 0xE8, 0x70)
ACCENT2 = (0x9D, 0x7C, 0xFF)
TEXT = (0xF0, 0xF4, 0xFF)
MUTED = (0x96, 0xA0, 0xC2)

FONT = "/System/Library/Fonts/Helvetica.ttc"
SHOTS = Path("/tmp/mirror-shots")


def font(sz):
    try:
        return ImageFont.truetype(FONT, sz)
    except Exception:
        return ImageFont.load_default()


def wrap(d, text, f, maxw):
    words, lines, line = text.split(), [], ""
    for w_ in words:
        if d.textlength(line + w_, font=f) > maxw and line:
            lines.append(line.strip())
            line = w_ + " "
        else:
            line += w_ + " "
    if line.strip():
        lines.append(line.strip())
    return lines


def new_slide():
    img = Image.new("RGB", (W, H), BG)
    return img, ImageDraw.Draw(img)


def progress_bar(d, frac):
    d.rectangle([0, H - 8, W, H], fill=LINE)
    d.rectangle([0, H - 8, int(W * frac), H], fill=ACCENT)


def eyebrow(d, text, y=70):
    d.text((90, y), text.upper(), font=font(26), fill=ACCENT)


# ---------------------------------------------------------------- concept ---
def concept_slide(idx, total, eyebrow_t, title, body, note=None):
    img, d = new_slide()
    eyebrow(d, eyebrow_t)
    d.text((90, 150), title, font=font(64), fill=TEXT)
    y = 290
    for ln in wrap(d, body, font(34), W - 200):
        d.text((90, y), ln, font=font(34), fill=MUTED)
        y += 52
    if note:
        y += 30
        d.rectangle([90, y, 96, y + 96], fill=ACCENT2)
        yy = y
        for ln in wrap(d, note, font(28), W - 260):
            d.text((120, yy), ln, font=font(28), fill=(0xC9, 0xD2, 0xEA))
            yy += 44
    progress_bar(d, (idx + 1) / total)
    return img


# ------------------------------------------------------------- app slides ---
def fit_shot(path, box_w, box_h):
    """Fit screenshot into box, keep aspect, add frame."""
    im = Image.open(path).convert("RGB")
    # crop very tall full-page shots to the top portion (results grid)
    if im.height > 2.2 * im.width:
        im = im.crop((0, 0, im.width, int(im.width * 1.9)))
    r = min(box_w / im.width, box_h / im.height)
    nw, nh = int(im.width * r), int(im.height * r)
    im = im.resize((nw, nh), Image.Resampling.LANCZOS)
    frame = Image.new("RGB", (nw + 12, nh + 12), (0, 0, 0))
    frame.paste(im, (6, 6))
    return frame


def app_slide(idx, total, eyebrow_t, title, caption, shot_path, zoom=None):
    """Screenshot left, caption right (zoom='full': split tall page into 2 columns)."""
    img, d = new_slide()
    eyebrow(d, eyebrow_t)
    d.text((90, 150), title, font=font(56), fill=TEXT)

    if zoom == "full":
        # tall full-page shot -> two vertical halves side by side
        im = Image.open(shot_path).convert("RGB")
        if im.height > 2.2 * im.width:
            im = im.crop((0, 0, im.width, int(im.width * 1.9)))
        mid = im.height // 2
        halves = [im.crop((0, 0, im.width, mid)), im.crop((0, mid, im.width, im.height))]
        box_h = 660
        placed = []
        for h_ in halves:
            r = box_h / h_.height
            nw = int(h_.width * r)
            placed.append(h_.resize((nw, int(box_h)), Image.Resampling.LANCZOS))
        total_w = sum(p.width for p in placed) + 60
        x = (W - total_w) // 2
        for p in placed:
            framed = Image.new("RGB", (p.width + 12, p.height + 12), (0, 0, 0))
            framed.paste(p, (6, 6))
            img.paste(framed, (x, 240))
            x += framed.width + 60
        cap_y = 240 + 660 + 24 + 40
        for ln in wrap(d, caption, font(30), W - 220):
            d.text((110, cap_y), ln, font=font(30), fill=MUTED)
            cap_y += 46
    else:
        # screenshot left ~62%
        box_w, box_h = int(W * 0.60) - 90, H - 420
        shot = fit_shot(shot_path, box_w, box_h)
        img.paste(shot, (90, 320))
        # caption panel right
        x0 = 90 + shot.width + 50
        d.rounded_rectangle([x0, 320, W - 90, H - 80], radius=18, fill=PANEL, outline=LINE, width=2)
        y = 360
        for ln in wrap(d, caption, font(30), W - x0 - 130):
            d.text((x0 + 40, y), ln, font=font(30), fill=MUTED)
            y += 48
        d.rectangle([x0, y + 14, x0 + 64, y + 20], fill=ACCENT2)
    progress_bar(d, (idx + 1) / total)
    return img


def hero_slide(idx, total):
    """Slide 2 style: brand hero with real landing screenshot."""
    img, d = new_slide()
    eyebrow(d, "The product")
    d.text((90, 140), "Mirror Agent — live on Cloud Run", font=font(58), fill=TEXT)
    shot = fit_shot(SHOTS / "01-landing.png", W - 180, 640)
    img.paste(shot, ((W - shot.width) // 2, 260))
    d.text((90, 260 + shot.height + 36), "One page: a selfie, your occasion, one briefing.",
           font=font(30), fill=MUTED)
    d.text((90, 260 + shot.height + 80), "mirror-agent-1087493193698.us-west1.run.app",
           font=font(26), fill=ACCENT)
    progress_bar(d, (idx + 1) / total)
    return img


# ------------------------------------------------------------------ plan ---
# (kind, duration, builder)
TOTAL = 13
PLAN = [
    ("concept", 13, dict(eyebrow_t="The mirror moment", title="Every morning is a guess",
        body="Is my skin okay? Does this outfit work for an interview? You check the mirror, you guess, you're already late.",
        note=None)),
    ("hero", 12, None),
    ("app", 12, dict(eyebrow_t="Step 1 — 20 seconds of input", title="Tell the mirror what's coming up",
        caption="Upload one selfie. Say what tomorrow is — \"big interview\". The agent decides everything else. YouCam Skin AI + Apparel VTO behind one button.",
        shot="02-form-filled.png")),
    ("app", 12, dict(eyebrow_t="Step 2 — Skin AI", title="An objective skin read, in plain language",
        caption="Shine 62 · Dark circles 55 · Dryness 38 · Redness 29 — the same face, scored consistently, no marketing gloss. Each concern comes with a quick fix you can do tonight.",
        shot="04-skin-report.png")),
    ("app", 12, dict(eyebrow_t="Step 3 — The agent thinks", title="Gemini turns numbers into a plan",
        caption="The agent reads the scores against YOUR occasion: interview → \"Executive Polish\". It picks focus areas, a styling intent, colors, and a morning-of checklist. Different context, different plan.",
        shot="06-briefing.png")),
    ("app", 12, dict(eyebrow_t="Step 4 — Apparel VTO", title="See the look before you commit",
        caption="The styling intent drives a try-on render on your own photo — no outfit roulette in front of the closet. Live mode swaps in real YouCam VTO renders; demo mode shows the placeholder overlay.",
        shot="05-vto.png")),
    ("app", 14, dict(eyebrow_t="The payoff — context is everything", title="Same face, different day",
        caption="Change one word — \"beach day with friends\" — and the entire briefing changes: Seaside Casual Chic, SPF-first fixes, pastel color notes. A template can't do this; an agent can.",
        shot="07-briefing-beach.png")),
    ("app", 12, dict(eyebrow_t="The briefing, in full", title="Everything in one scroll",
        caption="Skin report + focus areas + styling intent + try-on + checklist. Generated end-to-end in ~4 seconds.",
        shot="03-results-full.png", zoom="full")),
    ("concept", 13, dict(eyebrow_t="Under the hood", title="Not a wrapper — a decision loop",
        body="YouCam Skin AI scores the face. Gemini interprets scores in context. Interpretation drives the styling intent. The intent drives Apparel VTO. Each API feeds the next — through one agent.",
        note="Skin analysis → interpretation → styling → try-on → briefing. Degrades gracefully: no YouCam key = demo mode, no Gemini key = heuristic briefing. Zero keys to run.")),
    ("concept", 13, dict(eyebrow_t="Built for the deadline, ready for Monday", title="Try it now",
        body="Live demo on Cloud Run, open-source repo, one env var (YOUCAM_API_KEY) flips the whole pipeline to live YouCam APIs.",
        note="github.com/jtabsbm/mirror-agent · mirror-agent-1087493193698.us-west1.run.app")),
    ("concept", 11, dict(eyebrow_t="Mirror Agent", title="Walk out confident.",
        body="Built with YouCam Skin AI + Apparel VTO and Gemini at the YouCam (Perfect Corp) hackathon.", note=None)),
]


def build_frames():
    frames = []
    for i, (kind, dur, cfg) in enumerate(PLAN):
        if kind == "concept":
            img = concept_slide(i, TOTAL, **cfg)
        elif kind == "hero":
            img = hero_slide(i, TOTAL)
        else:
            img = app_slide(i, TOTAL, shot_path=SHOTS / cfg.pop("shot"), zoom=cfg.pop("zoom", None), **cfg)
        f = f"/tmp/v2-slide-{i:02d}.png"
        img.save(f)
        frames.append((f, dur))
        print("frame", i, kind, dur, "s")
    return frames


def main():
    frames = build_frames()
    total = sum(d for _, d in frames)
    concat = Path("/tmp/v2-concat.txt")
    concat.write_text("".join(f"file '{f}'\nduration {d}\n" for f, d in frames) + f"file '{frames[-1][0]}'\n")
    fade_out = total - 1.5
    r = subprocess.run([
        "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat),
        "-vf", f"fade=t=in:st=0:d=0.6,fade=t=out:st={fade_out}:d=1.5",
        "-c:v", "libx264", "-preset", "medium", "-pix_fmt", "yuv420p", "-r", "30",
        str(OUT),
    ], capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stderr[-800:])
        sys.exit(1)
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(OUT)],
        capture_output=True, text=True)
    print(f"OK {OUT} ({OUT.stat().st_size // (1024*1024)} MB) duration={probe.stdout.strip()}s")
    t = 0
    print("\nTIMELINE")
    for i, (f, d) in enumerate(frames):
        print(f"  {t:3d}s +{d}s  {Path(f).name}")
        t += d


if __name__ == "__main__":
    main()

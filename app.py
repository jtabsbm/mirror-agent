"""
app.py — FastAPI backend for the Mirror Agent demo.

Endpoints:
    GET  /            one-page demo UI (selfie upload + context -> briefing)
    POST /briefing    multipart: photo (file) + context (form) -> JSON result
    GET  /healthz     liveness + mode report

Run:
    uvicorn app:app --reload --port 8000
"""

from __future__ import annotations

import base64
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse

import mirror_agent
from mirror_agent import MirrorAgent

app = FastAPI(title="Mirror Agent", version="0.1.0")

HERE = Path(__file__).resolve().parent
MAX_PHOTO_BYTES = 10 * 1024 * 1024  # YouCam limit is 10MB


def _agent() -> MirrorAgent:
    # Constructed per-request: env/.env may be filled in while the server runs.
    return MirrorAgent()


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------

@app.get("/healthz")
def healthz() -> dict:
    import youcam_client

    youcam_client.load_dotenv_quietly()
    youcam_key = bool(__import__("os").environ.get("YOUCAM_API_KEY"))
    gemini_key = bool(mirror_agent._resolve_gemini_key())
    return {
        "status": "ok",
        "mode": "live" if youcam_key else "demo",
        "youcam_key_present": youcam_key,
        "gemini_key_present": gemini_key,
    }


@app.post("/briefing")
async def briefing(
    photo: UploadFile = File(..., description="Selfie (jpg/png, <10MB)"),
    context: str = Form(""),
    garment_id: str = Form(""),
) -> JSONResponse:
    raw = await photo.read()
    if not raw:
        raise HTTPException(status_code=400, detail="photo file is empty")
    if len(raw) > MAX_PHOTO_BYTES:
        raise HTTPException(status_code=413, detail="photo exceeds 10MB limit")

    garment = None
    if garment_id:
        garment = next((g for g in mirror_agent.GARMENT_CATALOG if g["id"] == garment_id), None)

    try:
        result = _agent().run(raw, context=context or "", garment=garment)
    except Exception as e:  # noqa: BLE001 — surface a clean 500, keep trace
        raise HTTPException(status_code=500, detail=f"agent failed: {e}") from e

    payload = result.to_dict()
    # inline the original selfie so the UI can show the before/after pair
    selfie_data_url = "data:image/jpeg;base64," + base64.b64encode(raw).decode()
    payload["selfie_data_url"] = selfie_data_url
    return JSONResponse(payload)


# ---------------------------------------------------------------------------
# Demo UI (single page, no build step)
# ---------------------------------------------------------------------------

PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Mirror Agent — YouCam Hackathon Demo</title>
<style>
  :root {
    --bg: #0e1117; --panel: #161b26; --panel2: #1c2333; --line: #2a3348;
    --text: #e8ecf5; --muted: #9aa4bd; --accent: #7c9cff; --accent2: #9d7cff;
    --ok: #4ade80; --warn: #fbbf24;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0; background: var(--bg); color: var(--text);
    font-family: ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif;
    line-height: 1.5;
  }
  header { padding: 20px 28px; border-bottom: 1px solid var(--line);
           display: flex; align-items: baseline; gap: 14px; flex-wrap: wrap; }
  header h1 { margin: 0; font-size: 1.25rem; }
  header .mode { font-size: .78rem; padding: 3px 10px; border-radius: 99px;
                 border: 1px solid var(--line); color: var(--muted); }
  header .mode.live { color: var(--ok); border-color: var(--ok); }
  main { max-width: 1180px; margin: 0 auto; padding: 24px 20px 60px; }
  .intro { color: var(--muted); font-size: .92rem; max-width: 760px; }
  form { display: grid; gap: 14px; background: var(--panel); border: 1px solid var(--line);
         border-radius: 14px; padding: 18px; margin: 18px 0; }
  .row { display: flex; gap: 14px; flex-wrap: wrap; }
  .row > * { flex: 1 1 240px; }
  label { font-size: .82rem; color: var(--muted); display: block; margin-bottom: 6px; }
  input[type=text], select {
    width: 100%; padding: 10px 12px; border-radius: 9px; border: 1px solid var(--line);
    background: var(--panel2); color: var(--text); font-size: .95rem;
  }
  .file-wrap { display:flex; gap:12px; align-items:center; }
  #photo { display:none; }
  .btn {
    display: inline-flex; align-items: center; gap: 8px; cursor: pointer;
    background: linear-gradient(120deg, var(--accent), var(--accent2)); color: #0b0e15;
    font-weight: 600; border: 0; border-radius: 9px; padding: 10px 18px; font-size: .95rem;
  }
  .btn.secondary { background: var(--panel2); color: var(--text); border: 1px solid var(--line); }
  .btn:disabled { opacity: .55; cursor: wait; }
  #preview { height: 64px; border-radius: 8px; border: 1px solid var(--line); }
  .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 18px; margin-top: 18px; }
  @media (max-width: 900px) { .grid { grid-template-columns: 1fr; } }
  .card { background: var(--panel); border: 1px solid var(--line); border-radius: 14px;
          padding: 18px; min-width: 0; }
  .card h3 { margin: 0 0 12px; font-size: 1rem; color: var(--muted); font-weight: 600;
             text-transform: uppercase; letter-spacing: .06em; }
  img.result { width: 100%; border-radius: 10px; border: 1px solid var(--line); display:block; }
  .concern { display: grid; grid-template-columns: 96px 1fr 74px; gap: 10px; align-items: center;
             padding: 8px 0; border-bottom: 1px dashed var(--line); font-size: .92rem; }
  .concern:last-child { border-bottom: 0; }
  .track { height: 8px; border-radius: 99px; background: var(--panel2); overflow: hidden; }
  .fill { height: 100%; border-radius: 99px; background: linear-gradient(90deg, var(--accent), var(--accent2)); }
  .score { text-align: right; color: var(--muted); font-variant-numeric: tabular-nums; }
  .briefing { grid-column: 1 / -1; }
  .briefing .md { background: var(--panel2); border-radius: 10px; padding: 18px; overflow-x: auto; }
  .briefing h1 { font-size: 1.3rem; margin: 0 0 6px; }
  .briefing h2 { font-size: 1.02rem; margin: 18px 0 8px; color: var(--accent); }
  .briefing table { border-collapse: collapse; width: 100%; font-size: .9rem; }
  .briefing th, .briefing td { text-align: left; padding: 6px 10px; border-bottom: 1px solid var(--line); }
  .briefing blockquote { margin: 0 0 8px; padding: 8px 12px; border-left: 3px solid var(--accent);
                         background: var(--panel); border-radius: 0 8px 8px 0; color: var(--muted); }
  .briefing code { background: var(--panel); padding: 1px 6px; border-radius: 5px; font-size: .85em; }
  .status { margin-top: 10px; font-size: .85rem; color: var(--muted); min-height: 1.2em; }
  .status.err { color: #f87171; }
  .focus-item { padding: 8px 0; border-bottom: 1px dashed var(--line); }
  .focus-item:last-child { border-bottom: 0; }
  .tag { font-size: .72rem; background: var(--panel2); border: 1px solid var(--line);
         padding: 2px 8px; border-radius: 99px; color: var(--muted); margin-left: 8px; }
  footer { text-align: center; color: var(--muted); font-size: .8rem; padding: 24px; }
</style>
</head>
<body>
<header>
  <h1>🪞 Mirror Agent</h1>
  <span class="mode" id="modeBadge">checking…</span>
  <span style="color:var(--muted);font-size:.85rem">YouCam skin analysis + apparel VTO · Gemini briefing</span>
</header>
<main>
  <p class="intro">
    Upload a selfie, tell the mirror what's coming up, and get a plain-language skin read,
    a styling direction, an AI try-on render, and a morning-of checklist.
  </p>

  <form id="frm">
    <div class="row">
      <div>
        <label for="photo">Selfie (jpg/png, &lt;10MB)</label>
        <div class="file-wrap">
          <label class="btn secondary" for="photo">Choose photo</label>
          <input type="file" id="photo" name="photo" accept="image/jpeg,image/png" required>
          <img id="preview" src="" alt="" style="display:none">
        </div>
      </div>
      <div>
        <label for="context">What's the occasion?</label>
        <input type="text" id="context" name="context" maxlength="300"
               placeholder="e.g. big interview tomorrow" value="big interview tomorrow">
      </div>
      <div>
        <label for="garment">Garment (optional)</label>
        <select id="garment" name="garment">
          <option value="">Auto — let the agent pick</option>
        </select>
      </div>
    </div>
    <div>
      <button class="btn" type="submit" id="go">🪞 Get my mirror briefing</button>
      <span class="status" id="status"></span>
    </div>
  </form>

  <section class="grid" id="results" style="display:none">
    <div class="card">
      <h3>Skin report</h3>
      <div id="skinReport"></div>
      <div id="focusAreas" style="margin-top:14px"></div>
    </div>
    <div class="card">
      <h3>Virtual try-on</h3>
      <div id="vto"></div>
    </div>
    <div class="card briefing">
      <h3>Mirror briefing</h3>
      <div class="md" id="briefingMd"></div>
    </div>
  </section>
</main>
<footer>Mirror Agent · YouCam (Perfect Corp) hackathon build · demo mode until YOUCAM_API_KEY is set</footer>

<script>
let GARMENTS = [];

async function refreshMode() {
  const badge = document.getElementById('modeBadge');
  try {
    const r = await fetch('/healthz');
    const j = await r.json();
    badge.textContent = j.mode === 'live' ? 'LIVE · YouCam key present' : 'DEMO MODE · no YouCam key yet';
    badge.classList.toggle('live', j.mode === 'live');
  } catch (e) {
    badge.textContent = 'offline';
  }
}

function fillGarments() {
  const sel = document.getElementById('garment');
  GARMENTS.forEach(g => {
    const o = document.createElement('option');
    o.value = g.id; o.textContent = g.label;
    sel.appendChild(o);
  });
}

// Garment catalog is embedded at render time so no extra fetch is needed.
GARMENTS = window.GARMENT_CATALOG || [];
fillGarments();
refreshMode();

document.getElementById('photo').addEventListener('change', ev => {
  const f = ev.target.files[0];
  const img = document.getElementById('preview');
  if (f) { img.src = URL.createObjectURL(f); img.style.display = 'block'; }
});

function esc(s) {
  return String(s ?? '').replace(/[&<>"']/g, c => ({
    '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'
  }[c]));
}

function renderSkin(skin) {
  const order = ['shine','dryness','redness','dark_circles'];
  const rows = order.map(name => {
    const c = (skin.concerns || {})[name] || {};
    const score = c.score ?? 0;
    return `<div class="concern">
      <div>${esc(name.replace('_',' ').toUpperCase())}</div>
      <div class="track"><div class="fill" style="width:${score}%"></div></div>
      <div class="score">${score}/100<br><span style="font-size:.7rem">${esc(c.label || '')}</span></div>
    </div>`;
  }).join('');
  let head = '';
  if (skin.overall && skin.overall.ui_score != null) {
    head = `<div style="margin-bottom:12px;color:var(--muted);font-size:.9rem">
      Overall skin score: <b style="color:var(--text)">${skin.overall.ui_score}/100</b>
      ${skin.skin_type ? ' · ' + esc(skin.skin_type) : ''}</div>`;
  }
  document.getElementById('skinReport').innerHTML = head + rows;
}

function renderFocus(focus) {
  if (!focus || !focus.length) { document.getElementById('focusAreas').innerHTML = ''; return; }
  const items = focus.slice(0,3).map(f => `
    <div class="focus-item">
      <b>${esc((f.concern||'').replace('_',' ').toUpperCase())}</b>
      <span class="tag">${f.score ?? '?'}/100</span>
      <div style="color:var(--muted);font-size:.9rem">${esc(f.why || '')}</div>
      ${f.quick_fix ? `<div style="font-size:.88rem;margin-top:4px">→ ${esc(f.quick_fix)}</div>` : ''}
    </div>`).join('');
  document.getElementById('focusAreas').innerHTML =
    `<h3 style="margin-top:16px">Focus areas</h3>` + items;
}

function renderVTO(vto, selfieUrl) {
  const el = document.getElementById('vto');
  const cols = [];
  if (selfieUrl) cols.push(`<figure style="margin:0">
    <img class="result" src="${selfieUrl}" alt="your selfie">
    <figcaption style="color:var(--muted);font-size:.8rem;margin-top:6px;text-align:center">your selfie</figcaption>
  </figure>`);
  const rendered = vto.result_url || vto.demo_image;
  if (rendered) cols.push(`<figure style="margin:0">
    <img class="result" src="${rendered}" alt="try-on render">
    <figcaption style="color:var(--muted);font-size:.8rem;margin-top:6px;text-align:center">
      ${vto.mode === 'live' ? 'YouCam VTO render' : 'demo placeholder render'}</figcaption>
  </figure>`);
  let note = '';
  if (!rendered) note = `<p style="color:var(--muted);font-size:.9rem">${esc(vto.note || 'No render available.')}</p>`;
  const garment = vto.garment ? `<p style="font-size:.9rem">Garment: <b>${esc(vto.garment)}</b></p>` : '';
  el.innerHTML = `<div style="display:grid;grid-template-columns:1fr 1fr;gap:12px">${cols.join('')}</div>`
               + garment + note;
}

// minimal markdown -> html for the briefing (headings, bold, italics, lists, tables, quotes)
function md2html(md) {
  const lines = md.split('\\n');
  let html = '', inList = false, inTable = false, inQuote = false;
  const closeList = () => { if (inList) { html += '</ul>'; inList = false; } };
  const closeTable = () => { if (inTable) { html += '</table>'; inTable = false; } };
  const closeQuote = () => { if (inQuote) { html += '</blockquote>'; inQuote = false; } };
  const inline = s => esc(s)
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/\\*\\*(.+?)\\*\\*/g, '<b>$1</b>')
    .replace(/(^|\\s)\\*(.+?)\\*(\\s|$)/g, '$1<i>$2</i>$3');
  for (const raw of lines) {
    const line = raw.trimEnd();
    if (/^\\|/.test(line)) {
      if (/^\\|[\\s:-]+\\|/.test(line.replace(/[^\\|:-]/g,''))) continue; // separator row
      const cells = line.split('|').slice(1, -1).map(c => inline(c.trim()));
      if (!inTable) { closeList(); closeQuote(); html += '<table>'; inTable = true; }
      html += '<tr>' + cells.map(c => `<td>${c}</td>`).join('') + '</tr>';
      continue;
    }
    closeTable();
    if (/^###\\s/.test(line)) { closeList(); closeQuote(); html += `<h3>${inline(line.slice(4))}</h3>`; }
    else if (/^##\\s/.test(line)) { closeList(); closeQuote(); html += `<h2>${inline(line.slice(3))}</h2>`; }
    else if (/^#\\s/.test(line)) { closeList(); closeQuote(); html += `<h1>${inline(line.slice(2))}</h1>`; }
    else if (/^>\\s?/.test(line)) { closeList(); if (!inQuote) { html += '<blockquote>'; inQuote = true; } html += inline(line.replace(/^>\\s?/, '')) + '<br>'; }
    else if (/^[-*]\\s/.test(line)) { closeQuote(); if (!inList) { html += '<ul style="padding-left:20px;margin:6px 0">'; inList = true; } html += `<li>${inline(line.slice(2))}</li>`; }
    else if (/^\\d+\\.\\s/.test(line)) { closeQuote(); if (!inList) { html += '<ul style="padding-left:20px;margin:6px 0">'; inList = true; } html += `<li>${inline(line.replace(/^\\d+\\.\\s/, ''))}</li>`; }
    else if (line.trim() === '') { closeList(); closeQuote(); }
    else if (/^---+$/.test(line)) { closeList(); closeQuote(); html += '<hr style="border:0;border-top:1px solid var(--line);margin:14px 0">'; }
    else { closeList(); closeQuote(); html += `<p style="margin:8px 0">${inline(line)}</p>`; }
  }
  closeList(); closeTable(); closeQuote();
  return html;
}

document.getElementById('frm').addEventListener('submit', async ev => {
  ev.preventDefault();
  const btn = document.getElementById('go');
  const status = document.getElementById('status');
  const fd = new FormData();
  const photo = document.getElementById('photo').files[0];
  if (!photo) { status.textContent = 'Pick a selfie first.'; status.className = 'status err'; return; }
  fd.append('photo', photo);
  fd.append('context', document.getElementById('context').value);
  fd.append('garment_id', document.getElementById('garment').value);
  btn.disabled = true;
  status.className = 'status';
  status.textContent = 'Analyzing skin, choosing a look, rendering try-on… (up to ~30s in live mode)';
  try {
    const r = await fetch('/briefing', { method: 'POST', body: fd });
    if (!r.ok) {
      let detail = r.statusText;
      try { detail = (await r.json()).detail || detail; } catch (e) {}
      throw new Error(detail);
    }
    const j = await r.json();
    document.getElementById('results').style.display = 'grid';
    renderSkin(j.skin);
    renderFocus(j.focus_areas);
    renderVTO(j.vto, j.selfie_data_url);
    document.getElementById('briefingMd').innerHTML = md2html(j.briefing_md);
    status.textContent = j.mode === 'live'
      ? '✅ Live YouCam analysis complete.'
      : '🎬 Served in DEMO MODE (canned skin data + placeholder render) — set YOUCAM_API_KEY for live results.';
  } catch (e) {
    status.textContent = 'Error: ' + e.message;
    status.className = 'status err';
  } finally {
    btn.disabled = false;
  }
});
</script>
</body>
</html>"""


@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    import json as _json

    catalog = _json.dumps(mirror_agent.GARMENT_CATALOG)
    html = PAGE.replace("window.GARMENT_CATALOG || []", catalog)
    return HTMLResponse(html)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app:app", host="127.0.0.1", port=8000, reload=False)

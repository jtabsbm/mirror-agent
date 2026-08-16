"""
youcam_client.py — Perfect Corp YouCam API client for the Mirror Agent.

Implements two capabilities against the documented YouCam s2s v2.0 REST API:

  1. Skin analysis  — upload a selfie via the File API, create a skin-analysis
     task, poll to completion, and reduce the raw `output` list into a flat,
     friendly concerns dict: {shine, dryness, redness, dark_circles, ...}.
     Endpoint: POST /s2s/v2.0/task/skin-analysis  (+ GET .../<task_id>)

  2. Apparel virtual try-on (VTO) — render a garment on the user photo.
     Endpoint: POST /s2s/v2.0/task/cloth-v4  (+ GET .../<task_id>)

Shared workflow (per docs.perfectcorp.com):
    Step A  POST /s2s/v2.0/file            -> file_id + pre-signed PUT url
    Step B  PUT  <pre-signed url>          -> actual bytes
    Step C  POST /s2s/v2.0/task/<kind>     -> task_id
    Step D  GET  /s2s/v2.0/task/<kind>/<id> -> poll until task_status in
            {success, error}

The API key is read LAZILY (on first use, from env or .env) so the module can
be imported and unit-tested without any key present. When the key is absent,
public methods raise YouCamKeyMissing — callers (mirror_agent) catch that and
fall back to demo mode with canned data.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional

import requests

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DEFAULT_BASE_URL = "https://yce-api-01.makeupar.com"

ENV_FILE_CANDIDATES = (
    Path(__file__).resolve().parent / ".env",
    Path.cwd() / ".env",
)

# SD skin concerns we request (HD variants exist but cannot be mixed with SD).
SKIN_ACTIONS_SD = [
    "oiliness",        # shine
    "moisture",        # hydration (dryness = 100 - moisture at agent layer)
    "redness",
    "dark_circle_v2",  # dark circles
    "acne",
    "eye_bag",
    "texture",
]

# Mapping from YouCam concern keys -> Mirror Agent concern names.
CONCERN_ALIASES = {
    "oiliness": "shine",
    "moisture": "hydration",
    "redness": "redness",
    "dark_circle_v2": "dark_circles",
    "dark_circle": "dark_circles",
    "hd_dark_circle": "dark_circles",
    "acne": "acne",
    "hd_acne": "acne",
    "eye_bag": "eye_bags",
    "hd_eye_bag": "eye_bags",
    "texture": "texture",
    "hd_texture": "texture",
}

_CONCERN_LABELS = {
    "shine": "shine",
    "hydration": "hydration",
    "redness": "redness",
    "dark_circles": "dark circles",
    "acne": "acne",
    "eye_bags": "eye bags",
    "texture": "texture",
}


class YouCamError(RuntimeError):
    """Base error for YouCam client failures."""


class YouCamKeyMissing(YouCamError):
    """Raised when YOUCAM_API_KEY is not configured (demo mode should be used)."""


class YouCamTaskError(YouCamError):
    """Raised when a YouCam async task ends in task_status=error or HTTP error."""

    def __init__(self, message: str, error_code: Optional[str] = None, payload: Any = None):
        super().__init__(message)
        self.error_code = error_code
        self.payload = payload


# ---------------------------------------------------------------------------
# Demo-mode canned data (used when no API key is present)
# ---------------------------------------------------------------------------

DEMO_SKIN_ANALYSIS: Dict[str, Any] = {
    "mode": "demo",
    "overall": {"ui_score": 74, "raw_score": 71.4},
    "concerns": {
        "shine": {"score": 62, "raw_score": 58.9, "label": "moderate shine in the T-zone"},
        "dryness": {"score": 38, "raw_score": 41.2, "label": "mild dryness on the cheeks"},
        "redness": {"score": 29, "raw_score": 27.5, "label": "slight redness around the nose"},
        "dark_circles": {"score": 55, "raw_score": 52.7, "label": "noticeable dark circles"},
    },
    "extras": {
        "acne": {"score": 18, "raw_score": 15.0, "label": "clear"},
        "eye_bags": {"score": 33, "raw_score": 31.0, "label": "mild"},
        "texture": {"score": 68, "raw_score": 65.1, "label": "fairly smooth"},
    },
    "skin_type": "Combination",
    "task_id": "demo-task-skin",
    "mask_urls": [],
}

DEMO_VTO_RESULT: Dict[str, Any] = {
    "mode": "demo",
    "status": "success",
    "result_url": None,  # demo mode: frontend shows a placeholder panel
    "garment": "navy blazer + crisp white shirt (demo)",
    "note": "Demo mode — VTO not rendered. Set YOUCAM_API_KEY to enable live try-on.",
    "task_id": "demo-task-vto",
}


def load_dotenv_quietly() -> None:
    """Tiny .env loader (no python-dotenv dependency). Idempotent."""
    for path in ENV_FILE_CANDIDATES:
        try:
            if not path.is_file():
                continue
            for line in path.read_text().splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key, value = key.strip(), value.strip().strip('"').strip("'")
                if key and key not in os.environ:
                    os.environ[key] = value
        except OSError:
            continue


def _get_api_key() -> Optional[str]:
    """Read the YouCam API key lazily from env / .env."""
    load_dotenv_quietly()
    return os.environ.get("YOUCAM_API_KEY") or None


# ---------------------------------------------------------------------------
# Response reduction (skin analysis)
# ---------------------------------------------------------------------------

def _clip(value: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, float(value)))


def _severity(score: float) -> str:
    if score >= 70:
        return "high"
    if score >= 40:
        return "moderate"
    return "low"


def reduce_skin_analysis(task_data: Dict[str, Any], task_id: str = "") -> Dict[str, Any]:
    """
    Reduce a successful skin-analysis task payload (data.results.output list of
    {type, ui_score, raw_score, mask_urls}) into the Mirror Agent concerns dict:

        {
          "mode": "live",
          "overall": {"ui_score": int, "raw_score": float},
          "concerns": {"shine": ..., "dryness": ..., "redness": ..., "dark_circles": ...},
          "extras": {...any other detected concerns...},
          "skin_type": str | None,
          "task_id": str,
          "mask_urls": [str],
        }

    Note on semantics: YouCam scores are *health* scores — higher is better for
    moisture, lower-severity for oiliness/redness concerns varies by metric.
    For the Mirror Agent we normalise each concern to a 0–100 *severity* the
    agent can reason about uniformly (higher = more of the concern):
      - shine      = oiliness ui_score (higher oiliness = more shine)
      - dryness    = 100 - moisture ui_score (less hydration = more dryness)
      - redness    = redness ui_score
      - dark_circles = dark_circle ui_score
    """
    results = (task_data or {}).get("results") or {}
    outputs = results.get("output") or []
    overall = (task_data or {}).get("overall") or {}

    by_concern: Dict[str, Dict[str, Any]] = {}
    mask_urls = []
    for item in outputs:
        ctype = (item.get("type") or "").lower()
        concern = CONCERN_ALIASES.get(ctype)
        ui = item.get("ui_score")
        raw = item.get("raw_score", ui if ui is not None else None)
        if concern is None or ui is None:
            continue
        by_concern[concern] = {
            "score": int(round(_clip(ui))),
            "raw_score": round(float(raw), 2) if raw is not None else None,
            "mask_urls": item.get("mask_urls") or [],
        }
        mask_urls.extend(item.get("mask_urls") or [])

    def pick(name: str) -> Dict[str, Any]:
        return by_concern.pop(name, {"score": None, "raw_score": None, "mask_urls": []})

    shine = pick("shine")
    hydration = pick("hydration")
    redness = pick("redness")
    dark_circles = pick("dark_circles")

    # Derive dryness severity from hydration (health score, higher = better).
    dryness_score = None
    if hydration["score"] is not None:
        dryness_score = int(round(_clip(100 - hydration["score"])))
    dryness_raw = (
        round(_clip(100 - hydration["raw_score"]), 2)
        if isinstance(hydration["raw_score"], (int, float)) else None
    )

    concerns = {
        "shine": {**shine, "label": _severity(shine["score"]) + " shine" if shine["score"] is not None else "not measured"},
        "dryness": {
            "score": dryness_score,
            "raw_score": dryness_raw,
            "mask_urls": hydration["mask_urls"],
            "label": _severity(dryness_score) + " dryness" if dryness_score is not None else "not measured",
        },
        "redness": {**redness, "label": _severity(redness["score"]) + " redness" if redness["score"] is not None else "not measured"},
        "dark_circles": {
            **dark_circles,
            "label": _severity(dark_circles["score"]) + " dark circles" if dark_circles["score"] is not None else "not measured",
        },
    }

    extras = {
        name: {**info, "label": f"{_severity(info['score'])} {_CONCERN_LABELS.get(name, name)}"}
        for name, info in by_concern.items()
        if isinstance(info.get("score"), (int, float))
    }

    # Overall score: YouCam exposes per-concern scores in the task response;
    # if an aggregate is present under results.overall / "all", use it.
    agg = overall or results.get("overall") or {}
    overall_out = {
        "ui_score": agg.get("ui_score"),
        "raw_score": agg.get("raw_score"),
    }

    return {
        "mode": "live",
        "overall": overall_out,
        "concerns": concerns,
        "extras": extras,
        "skin_type": results.get("skin_type") or None,
        "task_id": task_id,
        "mask_urls": mask_urls,
    }


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

@dataclass
class YouCamClient:
    """Thin wrapper over the YouCam s2s v2.0 API."""

    api_key: Optional[str] = None          # None -> resolved lazily from env/.env
    base_url: str = DEFAULT_BASE_URL
    timeout: float = 30.0
    poll_interval: float = 0.0             # fast in tests; 2.0 in production
    max_poll_attempts: int = 90
    session: requests.Session = field(default_factory=requests.Session)

    # -- plumbing -----------------------------------------------------------

    def _key(self) -> str:
        key = self.api_key or _get_api_key()
        if not key:
            raise YouCamKeyMissing(
                "YOUCAM_API_KEY is not set — add it to .env to leave demo mode."
            )
        return key

    def _auth_headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self._key()}",
            "Content-Type": "application/json",
        }

    def _post_json(self, path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        resp = self.session.post(
            f"{self.base_url}{path}", headers=self._auth_headers(),
            data=json.dumps(payload), timeout=self.timeout,
        )
        return self._unwrap(resp, path)

    def _get_json(self, path: str) -> Dict[str, Any]:
        resp = self.session.get(
            f"{self.base_url}{path}", headers=self._auth_headers(),
            timeout=self.timeout,
        )
        return self._unwrap(resp, path)

    @staticmethod
    def _unwrap(resp: requests.Response, path: str) -> Dict[str, Any]:
        try:
            body = resp.json()
        except ValueError:
            raise YouCamError(
                f"{path}: non-JSON response ({resp.status_code}): {resp.text[:200]}"
            )
        if resp.status_code >= 400:
            raise YouCamTaskError(
                f"{path}: HTTP {resp.status_code}: {body.get('error', body)}",
                error_code=body.get("error_code"),
                payload=body,
            )
        return body

    # -- File API (Steps A+B) -------------------------------------------------

    def upload_image(
        self, image_bytes: bytes, file_name: str, content_type: str = "image/jpeg"
    ) -> str:
        """Create an upload slot then PUT the bytes. Returns the file_id."""
        meta = self._post_json(
            "/s2s/v2.0/file",
            {
                "files": [
                    {
                        "content_type": content_type,
                        "file_name": file_name,
                        "file_size": len(image_bytes),
                    }
                ]
            },
        )
        files = (((meta or {}).get("data") or {}).get("files")) or []
        if not files:
            raise YouCamError(f"file upload init returned no files: {meta}")
        entry = files[0]
        file_id = entry.get("file_id")
        requests_list = entry.get("requests") or []
        if not file_id or not requests_list:
            raise YouCamError(f"file upload init missing file_id/request: {meta}")
        put = requests_list[0]
        put_resp = self.session.put(
            put["url"],
            data=image_bytes,
            headers={
                "Content-Type": put.get("headers", {}).get("Content-Type", content_type),
                "Content-Length": str(len(image_bytes)),
            },
            timeout=self.timeout,
        )
        if put_resp.status_code >= 400:
            raise YouCamError(
                f"PUT presigned upload failed: {put_resp.status_code} {put_resp.text[:200]}"
            )
        return file_id

    # -- Task polling (Step D) ------------------------------------------------

    def _poll(self, kind_path: str, task_id: str) -> Dict[str, Any]:
        last: Dict[str, Any] = {}
        for _ in range(self.max_poll_attempts):
            body = self._get_json(f"{kind_path}/{task_id}")
            data = body.get("data") or {}
            status = (data.get("task_status") or "").lower()
            last = data
            if status == "success":
                return data
            if status == "error":
                raise YouCamTaskError(
                    f"{kind_path} task {task_id} failed: {data.get('error')}",
                    error_code=data.get("error_code") or str(data.get("error")),
                    payload=data,
                )
            time.sleep(self.poll_interval)
        raise YouCamError(
            f"{kind_path} task {task_id} did not finish within "
            f"{self.max_poll_attempts * max(self.poll_interval, 0.001):.0f}s "
            f"(last status: {last.get('task_status')})"
        )

    # -- Skin analysis (Steps C+D) ---------------------------------------------

    def analyze_skin(self, image_bytes: bytes, file_name: str = "selfie.jpg") -> Dict[str, Any]:
        """Upload a selfie and run the full skin-analysis pipeline."""
        file_id = self.upload_image(image_bytes, file_name)
        return self.analyze_skin_by_file_id(file_id)

    def analyze_skin_by_file_id(self, file_id: str) -> Dict[str, Any]:
        created = self._post_json(
            "/s2s/v2.0/task/skin-analysis",
            {"src_file_id": file_id, "dst_actions": SKIN_ACTIONS_SD, "format": "json"},
        )
        task_id = (((created or {}).get("data") or {}).get("task_id")) or ""
        if not task_id:
            raise YouCamError(f"skin-analysis create returned no task_id: {created}")
        data = self._poll("/s2s/v2.0/task/skin-analysis", task_id)
        return reduce_skin_analysis(data, task_id=task_id)

    # -- Apparel VTO (Steps C+D) ------------------------------------------------

    def render_apparel_vto(
        self,
        user_image_bytes: bytes,
        garment_url: Optional[str] = None,
        garment_image_bytes: Optional[bytes] = None,
        garment_category: str = "upper_body",
        file_name: str = "user.jpg",
    ) -> Dict[str, Any]:
        """
        Render a garment on the user photo (POST /s2s/v2.0/task/cloth-v4).

        Provide exactly one of `garment_url` (public product image URL) or
        `garment_image_bytes` (uploaded via the File API).
        """
        if bool(garment_url) == bool(garment_image_bytes):
            raise YouCamError("Provide exactly one of garment_url or garment_image_bytes.")
        file_id = self.upload_image(user_image_bytes, file_name)
        return self.render_apparel_vto_by_file_id(
            file_id,
            garment_url=garment_url,
            garment_image_bytes=garment_image_bytes,
            garment_category=garment_category,
        )

    def render_apparel_vto_by_file_id(
        self,
        user_file_id: str,
        garment_url: Optional[str] = None,
        garment_image_bytes: Optional[bytes] = None,
        garment_category: str = "upper_body",
    ) -> Dict[str, Any]:
        if bool(garment_url) == bool(garment_image_bytes):
            raise YouCamError("Provide exactly one of garment_url or garment_image_bytes.")
        payload: Dict[str, Any] = {"src_file_id": user_file_id, "garment_category": garment_category}
        if garment_url:
            payload["ref_file_url"] = garment_url
        elif garment_image_bytes is not None:
            payload["ref_file_id"] = self.upload_image(
                garment_image_bytes, "garment.jpg", content_type="image/jpeg"
            )
        else:
            raise YouCamError("Provide exactly one of garment_url or garment_image_bytes.")

        created = self._post_json("/s2s/v2.0/task/cloth-v4", payload)
        task_id = (((created or {}).get("data") or {}).get("task_id")) or ""
        if not task_id:
            raise YouCamError(f"cloth-v4 create returned no task_id: {created}")
        data = self._poll("/s2s/v2.0/task/cloth-v4", task_id)
        result_url = (((data.get("results") or {}).get("url"))) or None
        return {
            "mode": "live",
            "status": "success",
            "result_url": result_url,
            "garment_category": garment_category,
            "task_id": task_id,
        }

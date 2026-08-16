"""
Unit tests for the Mirror Agent backend — all HTTP mocked, no live keys.

Run:  python -m pytest tests/ -v
"""

from __future__ import annotations

import io
import json
import os
import sys
from pathlib import Path
from unittest import mock

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import youcam_client
from youcam_client import (
    DEMO_SKIN_ANALYSIS,
    YouCamClient,
    YouCamError,
    YouCamKeyMissing,
    YouCamTaskError,
    reduce_skin_analysis,
)

import mirror_agent
from mirror_agent import GeminiAdvisor, MirrorAgent, compose_briefing, pick_garment


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class FakeResponse:
    def __init__(self, status_code=200, json_body=None, text=""):
        self.status_code = status_code
        self._json = json_body
        self.text = text or (json.dumps(json_body) if json_body is not None else "")

    def json(self):
        if self._json is None:
            raise ValueError("no json")
        return self._json


def tiny_jpeg() -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (120, 160), (110, 90, 80)).save(buf, format="JPEG")
    return buf.getvalue()


FILE_INIT_OK = {
    "status": 200,
    "data": {
        "files": [
            {
                "content_type": "image/jpeg",
                "file_name": "selfie.jpg",
                "file_id": "FILE_ID_123",
                "requests": [
                    {
                        "method": "PUT",
                        "url": "https://example-bucket.s3.amazonaws.com/presigned-put",
                        "headers": {"Content-Length": "1234", "Content-Type": "image/jpeg"},
                    }
                ],
            }
        ]
    },
}

SKIN_TASK_CREATED = {"status": 200, "data": {"task_id": "TASK_SKIN_1"}}

SKIN_TASK_SUCCESS = {
    "status": 200,
    "data": {
        "task_status": "success",
        "results": {
            "output": [
                {"type": "oiliness", "ui_score": 62, "raw_score": 58.9, "mask_urls": ["https://x/m1.jpg"]},
                {"type": "moisture", "ui_score": 71, "raw_score": 68.2, "mask_urls": []},
                {"type": "redness", "ui_score": 29, "raw_score": 27.5, "mask_urls": []},
                {"type": "dark_circle_v2", "ui_score": 55, "raw_score": 52.7, "mask_urls": ["https://x/m2.jpg"]},
                {"type": "acne", "ui_score": 18, "raw_score": 15.0, "mask_urls": []},
                {"type": "eye_bag", "ui_score": 33, "raw_score": 31.0, "mask_urls": []},
                {"type": "texture", "ui_score": 68, "raw_score": 65.1, "mask_urls": []},
            ]
        },
    },
}

VTO_TASK_CREATED = {"status": 200, "data": {"task_id": "TASK_VTO_1"}}

VTO_TASK_SUCCESS = {
    "status": 200,
    "data": {
        "task_status": "success",
        "error": None,
        "results": {"url": "https://x/result.jpg"},
    },
}


# ---------------------------------------------------------------------------
# youcam_client — auth & key handling
# ---------------------------------------------------------------------------

class TestKeyHandling:
    def test_key_missing_raises_without_env(self, monkeypatch):
        monkeypatch.delenv("YOUCAM_API_KEY", raising=False)
        client = YouCamClient(api_key=None)
        with mock.patch.object(youcam_client, "load_dotenv_quietly"):
            with pytest.raises(YouCamKeyMissing):
                client._key()

    def test_lazy_env_key(self, monkeypatch):
        monkeypatch.setenv("YOUCAM_API_KEY", "k-test-123")
        client = YouCamClient()
        with mock.patch.object(youcam_client, "load_dotenv_quietly"):
            assert client._key() == "k-test-123"

    def test_explicit_key_beats_env(self, monkeypatch):
        monkeypatch.setenv("YOUCAM_API_KEY", "from-env")
        client = YouCamClient(api_key="explicit")
        assert client._key() == "explicit"

    def test_dotenv_loader(self, tmp_path, monkeypatch):
        env = tmp_path / ".env"
        env.write_text('YOUCAM_API_KEY="dotenv-key"\n# comment\nEMPTY_LINE\n')
        monkeypatch.setattr(youcam_client, "ENV_FILE_CANDIDATES", (env,))
        monkeypatch.delenv("YOUCAM_API_KEY", raising=False)
        youcam_client.load_dotenv_quietly()
        assert os.environ["YOUCAM_API_KEY"] == "dotenv-key"


# ---------------------------------------------------------------------------
# youcam_client — skin analysis over mocked HTTP
# ---------------------------------------------------------------------------

class TestSkinAnalysis:
    def make_client(self):
        return YouCamClient(api_key="test-key", poll_interval=0.0)

    def _mock_session(self, responses):
        """responses: list of FakeResponse returned in order for post/get; PUT returns 200."""
        calls = {"post": [], "get": [], "put": []}
        queue = list(responses)

        session = mock.Mock()
        def post(url, headers=None, data=None, timeout=None):
            calls["post"].append({"url": url, "headers": headers, "json": json.loads(data)})
            return queue.pop(0)
        def get(url, headers=None, timeout=None):
            calls["get"].append({"url": url, "headers": headers})
            return queue.pop(0)
        def put(url, data=None, headers=None, timeout=None):
            calls["put"].append({"url": url, "bytes": data})
            return FakeResponse(200, {})
        session.post.side_effect = post
        session.get.side_effect = get
        session.put.side_effect = put
        return session, calls

    def test_full_skin_pipeline(self):
        client = self.make_client()
        session, calls = self._mock_session([
            FakeResponse(200, FILE_INIT_OK),      # file init (POST)
            FakeResponse(200, SKIN_TASK_CREATED), # task create (POST)
            FakeResponse(200, SKIN_TASK_SUCCESS), # poll (GET)
        ])
        client.session = session

        result = client.analyze_skin(tiny_jpeg(), "selfie.jpg")

        # file init
        assert calls["post"][0]["url"].endswith("/s2s/v2.0/file")
        init_body = calls["post"][0]["json"]
        assert init_body["files"][0]["file_size"] == len(tiny_jpeg())
        # presigned PUT carries the bytes
        assert calls["put"][0]["url"] == "https://example-bucket.s3.amazonaws.com/presigned-put"
        assert calls["put"][0]["bytes"] == tiny_jpeg()
        # task create
        assert calls["post"][1]["url"].endswith("/s2s/v2.0/task/skin-analysis")
        assert calls["post"][1]["json"]["src_file_id"] == "FILE_ID_123"
        for action in ("oiliness", "moisture", "redness", "dark_circle_v2"):
            assert action in calls["post"][1]["json"]["dst_actions"]
        # poll
        assert calls["get"][0]["url"].endswith("/s2s/v2.0/task/skin-analysis/TASK_SKIN_1")
        # bearer auth on every call
        assert calls["post"][0]["headers"]["Authorization"] == "Bearer test-key"

        # reduced output
        assert result["mode"] == "live"
        assert result["task_id"] == "TASK_SKIN_1"
        assert result["concerns"]["shine"]["score"] == 62
        assert result["concerns"]["dryness"]["score"] == 29  # 100 - 71 moisture
        assert result["concerns"]["redness"]["score"] == 29
        assert result["concerns"]["dark_circles"]["score"] == 55
        assert result["mask_urls"] == ["https://x/m1.jpg", "https://x/m2.jpg"]
        assert result["extras"]["acne"]["score"] == 18

    def test_poll_until_success(self):
        client = self.make_client()
        running = json.loads(json.dumps(SKIN_TASK_SUCCESS))
        running["data"]["task_status"] = "running"
        session, calls = self._mock_session([
            FakeResponse(200, FILE_INIT_OK),
            FakeResponse(200, SKIN_TASK_CREATED),
            FakeResponse(200, running),         # first poll: running
            FakeResponse(200, SKIN_TASK_SUCCESS) # second poll: success
        ])
        client.session = session
        result = client.analyze_skin(tiny_jpeg())
        assert len(calls["get"]) == 2
        assert result["concerns"]["shine"]["score"] == 62

    def test_task_error_raises(self):
        client = self.make_client()
        failed = json.loads(json.dumps(SKIN_TASK_SUCCESS))
        failed["data"]["task_status"] = "error"
        failed["data"]["error"] = "error_face_position_invalid"
        session, _ = self._mock_session([
            FakeResponse(200, FILE_INIT_OK),
            FakeResponse(200, SKIN_TASK_CREATED),
            FakeResponse(200, failed),
        ])
        client.session = session
        with pytest.raises(YouCamTaskError) as exc:
            client.analyze_skin(tiny_jpeg())
        assert "error_face_position_invalid" in str(exc.value)

    def test_http_error_raises_with_code(self):
        client = self.make_client()
        session, _ = self._mock_session([
            FakeResponse(401, {"status": 401, "error": "Unauthorized", "error_code": "InvalidAccessToken"}),
        ])
        client.session = session
        with pytest.raises(YouCamTaskError) as exc:
            client.upload_image(tiny_jpeg(), "selfie.jpg")
        assert exc.value.error_code == "InvalidAccessToken"

    def test_non_json_response(self):
        client = self.make_client()
        session, _ = self._mock_session([FakeResponse(502, None, text="<html>bad gateway</html>")])
        client.session = session
        with pytest.raises(YouCamError):
            client.upload_image(tiny_jpeg(), "selfie.jpg")

    def test_missing_task_id(self):
        client = self.make_client()
        session, _ = self._mock_session([
            FakeResponse(200, FILE_INIT_OK),
            FakeResponse(200, {"status": 200, "data": {}}),
        ])
        client.session = session
        with pytest.raises(YouCamError, match="no task_id"):
            client.analyze_skin(tiny_jpeg())


# ---------------------------------------------------------------------------
# youcam_client — apparel VTO over mocked HTTP
# ---------------------------------------------------------------------------

class TestApparelVTO:
    def _client_with_session(self, responses):
        client = YouCamClient(api_key="test-key", poll_interval=0.0)
        calls = {"post": [], "get": [], "put": []}
        queue = list(responses)
        session = mock.Mock()
        def post(url, headers=None, data=None, timeout=None):
            calls["post"].append({"url": url, "json": json.loads(data)})
            return queue.pop(0)
        def get(url, headers=None, timeout=None):
            calls["get"].append({"url": url})
            return queue.pop(0)
        def put(url, data=None, headers=None, timeout=None):
            return FakeResponse(200, {})
        session.post.side_effect = post
        session.get.side_effect = get
        session.put.side_effect = put
        client.session = session
        return client, calls

    def test_vto_with_garment_url(self):
        client, calls = self._client_with_session([
            FakeResponse(200, FILE_INIT_OK),
            FakeResponse(200, VTO_TASK_CREATED),
            FakeResponse(200, VTO_TASK_SUCCESS),
        ])
        result = client.render_apparel_vto(
            tiny_jpeg(),
            garment_url="https://example.com/blazer.jpg",
            garment_category="upper_body",
        )
        assert calls["post"][1]["url"].endswith("/s2s/v2.0/task/cloth-v4")
        body = calls["post"][1]["json"]
        assert body["src_file_id"] == "FILE_ID_123"
        assert body["ref_file_url"] == "https://example.com/blazer.jpg"
        assert body["garment_category"] == "upper_body"
        assert calls["get"][0]["url"].endswith("/s2s/v2.0/task/cloth-v4/TASK_VTO_1")

        assert result["mode"] == "live"
        assert result["status"] == "success"
        assert result["result_url"] == "https://x/result.jpg"
        assert result["task_id"] == "TASK_VTO_1"

    def test_vto_requires_exactly_one_garment_source(self):
        client, _ = self._client_with_session([])
        with pytest.raises(YouCamError):
            client.render_apparel_vto(tiny_jpeg())  # neither
        with pytest.raises(YouCamError):
            client.render_apparel_vto(
                tiny_jpeg(),
                garment_url="https://a/x.jpg",
                garment_image_bytes=b"123",
            )

    def test_vto_garment_upload_path(self):
        # two uploads: user photo, then garment image
        init1 = json.loads(json.dumps(FILE_INIT_OK))
        init1["data"]["files"][0]["file_id"] = "USER_FILE_ID"
        init2 = json.loads(json.dumps(FILE_INIT_OK))
        init2["data"]["files"][0]["file_id"] = "GARMENT_FILE_ID"
        client, calls = self._client_with_session([
            FakeResponse(200, init1),
            FakeResponse(200, init2),
            FakeResponse(200, VTO_TASK_CREATED),
            FakeResponse(200, VTO_TASK_SUCCESS),
        ])
        result = client.render_apparel_vto(
            tiny_jpeg(), garment_image_bytes=tiny_jpeg()
        )
        assert calls["post"][2]["json"]["src_file_id"] == "USER_FILE_ID"
        assert calls["post"][2]["json"]["ref_file_id"] == "GARMENT_FILE_ID"
        assert result["result_url"] == "https://x/result.jpg"


# ---------------------------------------------------------------------------
# reduce_skin_analysis pure function
# ---------------------------------------------------------------------------

class TestReduceSkinAnalysis:
    def test_demo_shape_matches_live_shape(self):
        live = reduce_skin_analysis(SKIN_TASK_SUCCESS["data"])
        for key in ("shine", "dryness", "redness", "dark_circles"):
            assert key in live["concerns"], f"missing {key}"
            assert live["concerns"][key]["score"] is not None
        # demo canned data must expose the same contract
        for key in ("shine", "dryness", "redness", "dark_circles"):
            assert key in DEMO_SKIN_ANALYSIS["concerns"]

    def test_dryness_is_inverse_of_moisture(self):
        live = reduce_skin_analysis(SKIN_TASK_SUCCESS["data"])
        assert live["concerns"]["dryness"]["score"] == 100 - 71

    def test_missing_concerns_yield_none(self):
        live = reduce_skin_analysis({"results": {"output": []}})
        for key in ("shine", "dryness", "redness", "dark_circles"):
            assert live["concerns"][key]["score"] is None

    def test_scores_clipped_to_0_100(self):
        data = {"results": {"output": [
            {"type": "oiliness", "ui_score": 130},
            {"type": "moisture", "ui_score": -5},
        ]}}
        live = reduce_skin_analysis(data)
        assert live["concerns"]["shine"]["score"] == 100
        assert live["concerns"]["dryness"]["score"] == 100  # 100 - (clipped 0)


# ---------------------------------------------------------------------------
# mirror_agent — demo mode (no keys)
# ---------------------------------------------------------------------------

class TestMirrorAgentDemoMode:
    def test_demo_mode_without_any_keys(self, monkeypatch):
        monkeypatch.delenv("YOUCAM_API_KEY", raising=False)
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
        with mock.patch.object(youcam_client, "load_dotenv_quietly"):
            with mock.patch.object(mirror_agent, "_resolve_gemini_key", return_value=None):
                agent = MirrorAgent()
                result = agent.run(tiny_jpeg(), "big interview tomorrow")

        assert result.mode == "demo"
        assert "# Mirror Briefing" in result.briefing_md
        assert "DEMO MODE" in result.briefing_md or "demo mode" in result.briefing_md
        # all four headline concerns present in the report
        for key in ("shine", "dryness", "redness", "dark_circles"):
            assert key in result.skin["concerns"]
        # focus areas derived rule-based
        assert 1 <= len(result.focus_areas) <= 3
        assert result.trace[0]["step"] == "skin_analysis"
        assert result.trace[0]["status"] == "demo"
        # VTO demo placeholder generated from the actual selfie
        assert result.vto["mode"] == "demo"
        assert result.vto["demo_image"].startswith("data:image/png;base64,")

    def test_demo_briefing_mentions_interview(self, monkeypatch):
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
        monkeypatch.delenv("YOUCAM_API_KEY", raising=False)
        with mock.patch.object(youcam_client, "load_dotenv_quietly"):
            with mock.patch.object(mirror_agent, "_resolve_gemini_key", return_value=None):
                agent = MirrorAgent()
                result = agent.run(tiny_jpeg(), "big interview tomorrow")
        styling_words = (result.briefing_md + json.dumps(result.styling)).lower()
        assert any(w in styling_words for w in ("interview", "professional", "polished"))

    def test_live_skin_error_degrades_to_demo(self, monkeypatch):
        monkeypatch.delenv("YOUCAM_API_KEY", raising=False)
        with mock.patch.object(youcam_client, "load_dotenv_quietly"):
            youcam = YouCamClient(api_key="some-key", poll_interval=0.0)
            youcam.session = mock.Mock()
            youcam.session.post.return_value = FakeResponse(500, {"error": "boom"})
            with mock.patch.object(mirror_agent, "_resolve_gemini_key", return_value=None):
                agent = MirrorAgent(youcam=youcam)
                result = agent.run(tiny_jpeg(), "date night")
        assert result.mode == "demo"
        assert result.trace[0]["status"] == "demo"
        assert "live error" in result.trace[0]["reason"]


# ---------------------------------------------------------------------------
# mirror_agent — live path with mocked YouCam + mocked Gemini
# ---------------------------------------------------------------------------

class FakeGemini(GeminiAdvisor):
    """Deterministic stand-in that returns canned JSON per prompt."""

    def __init__(self, interp=None, style=None):
        super().__init__(api_key="fake")
        self.interp = interp or {
            "interpretation": "Your skin is balanced but slightly oily in the T-zone and your under-eyes look tired.",
            "focus_areas": [
                {"concern": "shine", "score": 62, "why": "T-zone oil shows on camera", "quick_fix": "Blot then powder."},
                {"concern": "dark_circles", "score": 55, "why": "reads tired", "quick_fix": "Cool compress."},
            ],
        }
        self.style = style or {
            "intent_name": "Polished Professional",
            "description": "A structured blazer over a crisp shirt reads calm and competent.",
            "garment_category": "upper_body",
            "color_notes": "Navy and white.",
            "quick_wins": ["Blot T-zone", "Concealer under eyes", "Steam the blazer"],
        }
        self.calls = []

    def _call(self, system, prompt, timeout=45):
        self.calls.append(prompt)
        return self.style if "stylist" in system else self.interp


class TestMirrorAgentLivePath:
    def _live_youcam(self):
        youcam = YouCamClient(api_key="test-key", poll_interval=0.0)
        responses = [
            FakeResponse(200, FILE_INIT_OK),
            FakeResponse(200, SKIN_TASK_CREATED),
            FakeResponse(200, SKIN_TASK_SUCCESS),
            FakeResponse(200, FILE_INIT_OK),
            FakeResponse(200, VTO_TASK_CREATED),
            FakeResponse(200, VTO_TASK_SUCCESS),
        ]
        queue = list(responses)
        session = mock.Mock()

        def post(url, headers=None, data=None, timeout=None):
            return queue.pop(0)

        def get(url, headers=None, timeout=None):
            return queue.pop(0)

        def put(url, data=None, headers=None, timeout=None):
            return FakeResponse(200, {})

        session.post.side_effect = post
        session.get.side_effect = get
        session.put.side_effect = put
        youcam.session = session
        return youcam

    def test_full_live_pipeline(self):
        agent = MirrorAgent(youcam=self._live_youcam(), gemini=FakeGemini())
        result = agent.run(tiny_jpeg(), "big interview tomorrow")

        assert result.mode == "live"
        assert result.skin["mode"] == "live"
        assert result.skin["concerns"]["shine"]["score"] == 62
        assert result.vto["mode"] == "live"
        assert result.vto["result_url"] == "https://x/result.jpg"
        # Gemini drove interpretation + styling
        assert len(agent.gemini.calls) == 2
        assert result.styling["intent_name"] == "Polished Professional"
        assert result.focus_areas[0]["concern"] == "shine"
        # briefing composed from live data
        assert "# Mirror Briefing" in result.briefing_md
        assert "LIVE" in result.briefing_md
        assert "https://x/result.jpg" in result.briefing_md
        # garment matched intent category
        assert result.garment["category"] == result.styling["garment_category"]

    def test_live_vto_failure_degrades_only_vto(self):
        youcam = self._live_youcam()
        # replace the final poll (VTO) with an error
        youcam.session.get.side_effect = [
            FakeResponse(200, SKIN_TASK_SUCCESS),  # skin poll
            FakeResponse(200, {"status": 200, "data": {"task_status": "error", "error": "error_pose"}}),
        ]
        agent = MirrorAgent(youcam=youcam, gemini=FakeGemini())
        result = agent.run(tiny_jpeg(), "party tonight")

        assert result.mode == "live"  # skin was live
        assert result.vto["mode"] == "demo"  # VTO degraded
        assert result.vto.get("demo_image", "").startswith("data:image/png;base64,")

    def test_focus_areas_ordering(self):
        agent = MirrorAgent(youcam=self._live_youcam(), gemini=FakeGemini())
        result = agent.run(tiny_jpeg(), "presentation")
        scores = [f["score"] for f in result.focus_areas]
        assert scores == sorted(scores, reverse=True)


# ---------------------------------------------------------------------------
# mirror_agent — composition helpers
# ---------------------------------------------------------------------------

class TestBriefingComposition:
    def test_demo_briefing_has_disclaimer(self):
        md = compose_briefing(
            "big interview tomorrow", DEMO_SKIN_ANALYSIS,
            {"interpretation": "You look fine.", "focus_areas": []},
            {"intent_name": "Polished Professional", "description": "Blazer.", "quick_wins": ["Sleep."]},
            {"mode": "demo", "result_url": None}, mode="demo", gemini_model=None,
        )
        assert "demo mode" in md.lower()
        assert "YOUCAM_API_KEY" in md
        assert "| Shine |" in md

    def test_briefing_includes_all_concerns(self):
        md = compose_briefing(
            "date night", DEMO_SKIN_ANALYSIS,
            {"interpretation": "ok", "focus_areas": [
                {"concern": "shine", "score": 62, "why": "oil", "quick_fix": "powder"}]},
            {"intent_name": "Warm Evening", "description": "Soft.", "quick_wins": []},
            {"mode": "demo", "result_url": None}, mode="demo", gemini_model=None,
        )
        for label in ("Shine", "Dryness", "Redness", "Dark Circles"):
            assert label in md

    def test_pick_garment_matches_category(self):
        garment = pick_garment({"garment_category": "full_body"})
        assert garment["category"] == "full_body"
        garment = pick_garment({"garment_category": "upper_body"})
        assert garment["category"] == "upper_body"
        garment = pick_garment({})
        assert garment["category"]  # always returns something


# ---------------------------------------------------------------------------
# FastAPI app — TestClient end-to-end in demo mode
# ---------------------------------------------------------------------------

class TestApp:
    @pytest.fixture
    def client(self, monkeypatch):
        from fastapi.testclient import TestClient

        monkeypatch.delenv("YOUCAM_API_KEY", raising=False)
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
        import app as app_module

        with mock.patch.object(youcam_client, "load_dotenv_quietly"):
            with mock.patch.object(mirror_agent, "_resolve_gemini_key", return_value=None):
                with mock.patch.object(app_module, "_agent") as make_agent:
                    make_agent.side_effect = lambda: MirrorAgent()
                    with TestClient(app_module.app) as c:
                        yield c

    def test_healthz(self, client):
        r = client.get("/healthz")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ok"
        assert body["mode"] == "demo"

    def test_index_serves_ui(self, client):
        r = client.get("/")
        assert r.status_code == 200
        assert "text/html" in r.headers["content-type"]
        assert "Mirror Agent" in r.text
        assert "Get my mirror briefing" in r.text
        # garment catalog embedded
        assert "professional-blazer" in r.text

    def test_briefing_demo_mode(self, client):
        r = client.post(
            "/briefing",
            files={"photo": ("selfie.jpg", tiny_jpeg(), "image/jpeg")},
            data={"context": "big interview tomorrow"},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["mode"] == "demo"
        assert body["briefing_md"].startswith("# Mirror Briefing")
        for key in ("shine", "dryness", "redness", "dark_circles"):
            assert key in body["skin"]["concerns"]
        assert body["vto"]["mode"] == "demo"
        assert body["selfie_data_url"].startswith("data:image/jpeg;base64,")

    def test_briefing_requires_photo(self, client):
        r = client.post("/briefing", files={"photo": ("empty.jpg", b"", "image/jpeg")}, data={"context": "x"})
        assert r.status_code == 400

    def test_briefing_rejects_oversized(self, client):
        big = b"x" * (10 * 1024 * 1024 + 1)
        r = client.post("/briefing", files={"photo": ("big.jpg", big, "image/jpeg")}, data={"context": "x"})
        assert r.status_code == 413

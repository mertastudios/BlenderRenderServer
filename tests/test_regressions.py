"""Regressionstests zu den Fixes: 3D-API-Auth, GitHub-Update, Token."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from server import avatar, config, updater  # noqa: E402
from server.avatar import AvatarError  # noqa: E402


class AuthMessageTests(unittest.TestCase):
    def test_without_key_explains_3d_and_how_to_create_key(self):
        msg = avatar.auth_error_message(403, key_was_sent=False)
        self.assertIn("HTTP 403", msg)
        self.assertIn("KEIN Profilbild", msg)
        self.assertIn("thumbnails: Read", msg)
        self.assertIn("create.roblox.com/dashboard/credentials", msg)
        self.assertIn("ROBLOX_API_KEY", msg)

    def test_with_key_mentions_permissions_and_ip(self):
        msg = avatar.auth_error_message(401, key_was_sent=True)
        self.assertIn("HTTP 401", msg)
        self.assertIn("thumbnails: Read", msg)
        self.assertIn("IP", msg)


class ManifestFetchTests(unittest.TestCase):
    def _session(self, status: int, payload=None, text: str = "") -> MagicMock:
        session = MagicMock()
        resp = MagicMock()
        resp.ok = 200 <= status < 300
        resp.status_code = status
        resp.text = text
        resp.json.return_value = payload if payload is not None else {}
        session.get.return_value = resp
        return session

    def test_403_fails_immediately_with_key_instructions(self):
        session = self._session(403)
        with patch.object(config, "ROBLOX_API_KEY", ""):
            with self.assertRaises(AvatarError) as ctx:
                avatar.fetch_3d_manifest(session, 8593053805)
        self.assertIn("thumbnails: Read", str(ctx.exception))
        self.assertIn("KEIN Profilbild", str(ctx.exception))
        self.assertEqual(session.get.call_count, 1)

    def test_401_with_key_mentions_wrong_permission(self):
        session = self._session(401)
        with patch.object(config, "ROBLOX_API_KEY", "test-key"):
            with self.assertRaises(AvatarError) as ctx:
                avatar.fetch_3d_manifest(session, 1)
        self.assertIn("obwohl ein API-Key gesendet wurde", str(ctx.exception))

    def test_completed_manifest_from_image_url(self):
        session = MagicMock()
        list_resp = MagicMock()
        list_resp.ok = True
        list_resp.status_code = 200
        list_resp.json.return_value = {
            "data": [{
                "state": "Completed",
                "imageUrl": "https://t0.rbxcdn.com/manifest-hash",
            }]
        }
        man_resp = MagicMock()
        man_resp.ok = True
        man_resp.status_code = 200
        man_resp.json.return_value = {
            "obj": "objhash",
            "mtl": "mtlhash",
            "textures": ["texhash"],
        }
        session.get.side_effect = [list_resp, man_resp]
        with patch.object(config, "ROBLOX_API_KEY", "k"):
            manifest, host = avatar.fetch_3d_manifest(session, 1)
        self.assertEqual(manifest["obj"], "objhash")
        self.assertEqual(host, "t0.rbxcdn.com")

    def test_direct_manifest_payload(self):
        session = self._session(200, {"obj": "aaa", "mtl": "bbb", "textures": []})
        with patch.object(config, "ROBLOX_API_KEY", "k"):
            manifest, _host = avatar.fetch_3d_manifest(session, 1)
        self.assertEqual(manifest["obj"], "aaa")

    def test_http_400_does_not_loop_forever(self):
        session = self._session(400)
        with patch.object(config, "ROBLOX_API_KEY", "k"):
            with patch("server.avatar.time.sleep"):
                with self.assertRaises(AvatarError) as ctx:
                    avatar.fetch_3d_manifest(session, 1)
        self.assertIn("HTTP 400", str(ctx.exception))
        self.assertLess(session.get.call_count, 10)


class UpdaterTests(unittest.TestCase):
    def test_api_success(self):
        fake = MagicMock()
        fake.ok = True
        fake.json.return_value = {"sha": "a" * 40}
        with patch("server.updater.requests.get", return_value=fake):
            sha, err = updater.remote_sha_detailed()
        self.assertEqual(sha, "a" * 40)
        self.assertEqual(err, "")

    def test_falls_back_to_atom_when_api_blocked(self):
        api = MagicMock()
        api.ok = False
        api.status_code = 403
        atom = MagicMock()
        atom.ok = True
        atom.text = (
            '<?xml version="1.0"?><feed>'
            "<id>https://github.com/x/y/commit/" + "b" * 40 + "</id></feed>"
        )

        def fake_get(url, *args, **kwargs):
            if "api.github.com" in url:
                return api
            return atom

        with patch("server.updater.requests.get", side_effect=fake_get):
            with patch.object(updater, "_sha_from_git", return_value=(None, "skip")):
                sha, err = updater.remote_sha_detailed()
        self.assertEqual(sha, "b" * 40)
        self.assertEqual(err, "")

    def test_all_fail_keeps_detail(self):
        with patch.object(updater, "_sha_from_api", return_value=(None, "api.github.com HTTP 403")):
            with patch.object(updater, "_sha_from_atom", return_value=(None, "atom down")):
                with patch.object(updater, "_sha_from_git", return_value=(None, "no git")):
                    sha, err = updater.remote_sha_detailed()
                    self.assertIsNone(sha)
                    self.assertIn("api.github.com HTTP 403", err)
                    self.assertIn("atom down", err)
                    updated, msg = updater.check_and_apply()
        self.assertFalse(updated)
        self.assertIn("Update uebersprungen", msg)
        self.assertIn("Rendern funktioniert trotzdem", msg)

    def test_request_sends_user_agent(self):
        captured = {}

        def fake_get(url, *args, **kwargs):
            captured["headers"] = kwargs.get("headers") or {}
            resp = MagicMock()
            resp.ok = True
            resp.json.return_value = {"sha": "c" * 40}
            return resp

        with patch("server.updater.requests.get", side_effect=fake_get):
            updater.remote_sha_detailed()
        self.assertIn("BlenderRenderServer", captured["headers"].get("User-Agent", ""))


class SessionHeaderTests(unittest.TestCase):
    def test_session_sends_api_key(self):
        with patch.object(config, "ROBLOX_API_KEY", "secret-key"):
            session = avatar._session()
        self.assertEqual(session.headers.get("x-api-key"), "secret-key")

    def test_session_without_key_has_no_header(self):
        with patch.object(config, "ROBLOX_API_KEY", ""):
            session = avatar._session()
        self.assertNotIn("x-api-key", {k.lower() for k in session.headers.keys()})


class ConfigTests(unittest.TestCase):
    def test_new_settings_exist(self):
        self.assertTrue(hasattr(config, "PUBLIC_URL"))
        self.assertTrue(hasattr(config, "PUBLIC_TUNNEL"))
        self.assertTrue(hasattr(config, "BRS_ACCESS_TOKEN"))


class AppEndpointTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            from fastapi.testclient import TestClient
            from server import app as appmod
        except Exception:
            cls.client = None
            cls.appmod = None
            return
        cls.client = TestClient(appmod.app)
        cls.appmod = appmod

    def test_health_lists_studio_url(self):
        if not self.client:
            self.skipTest("fastapi TestClient nicht verfuegbar")
        resp = self.client.get("/health")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["status"], "ok")
        self.assertIn("studio_url", body)
        self.assertIn("api_key_set", body)

    def test_token_protects_jobs_but_not_health(self):
        if not self.client:
            self.skipTest("fastapi TestClient nicht verfuegbar")
        with patch.object(config, "BRS_ACCESS_TOKEN", "secret"):
            denied = self.client.post("/jobs", json={"username": "Roblox"})
            self.assertEqual(denied.status_code, 401)
            self.assertIn("RENDER_ACCESS_TOKEN", denied.json()["detail"])
            health = self.client.get("/health")
            self.assertEqual(health.status_code, 200)

    def test_status_page_warns_without_api_key(self):
        if not self.client:
            self.skipTest("fastapi TestClient nicht verfuegbar")
        with patch.object(config, "ROBLOX_API_KEY", ""):
            with patch.object(config, "TEST_MODE", False):
                resp = self.client.get("/")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("ROBLOX_API_KEY", resp.text)
        self.assertIn("kein Profilbild", resp.text)


if __name__ == "__main__":
    unittest.main()

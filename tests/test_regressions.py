"""Regressionstests: 3D-API-Auth, GitHub-Update, Token, Rigging, Roblox-Mesh, Scene-Creation, Status & Queue."""
from __future__ import annotations

import json
import struct
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from server import avatar, blender_render, config, roblox_mesh, updater  # noqa: E402
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


class MtlFixupTests(unittest.TestCase):
    def test_appends_png_extension(self):
        out = avatar._rewrite_mtl("map_Kd 30DAY-abc", ["30DAY-abc.png"])
        self.assertIn("map_Kd 30DAY-abc.png", out)

    def test_map_ka_becomes_map_kd(self):
        out = avatar._rewrite_mtl("map_Ka 30DAY-abc", ["30DAY-abc.png"])
        self.assertNotIn("map_Ka", out)
        self.assertNotIn("map_Ka 30DAY-abc\n", out)
        self.assertIn("map_Kd 30DAY-abc.png", out)

    def test_existing_extensions_are_kept(self):
        out = avatar._rewrite_mtl("map_Kd tex.png", ["tex.png"])
        self.assertIn("map_Kd tex.png", out)

    def test_options_numbers_and_paths(self):
        out = avatar._rewrite_mtl("map_d -s 1 1 1 some/dir/Tex", ["tex.png"])
        self.assertIn("-s 1 1 1", out)
        self.assertIn("tex.png", out)
        self.assertNotIn("some/dir/Tex", out)

    def test_comments_and_plain_lines_stay_unchanged(self):
        mtl = "# Kommentar von Roblox\nnewmtl m\nKd 1 1 1\nillum 2\n"
        out = avatar._rewrite_mtl(mtl, ["x.png"])
        self.assertIn("# Kommentar von Roblox", out)
        self.assertIn("newmtl m", out)
        self.assertIn("Kd 1 1 1", out)
        self.assertIn("illum 2", out)

    def test_unknown_refs_are_left_as_is(self):
        out = avatar._rewrite_mtl("map_Kd fehlt", ["andere.png"])
        self.assertIn("map_Kd fehlt", out)


class DownloadAvatarModelTests(unittest.TestCase):
    PNG_BYTES = (
        b"\x89PNG\r\n\x1a\n"
        b"\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
        b"\x00\x00\x00\rIDATx\x9cc\xf8\xcf\xc0\x00\x00\x00\x03\x00\x01"
        b"\x5b\xd4\x1b\x0e"
        b"\x00\x00\x00\x00IEND\xaeB`\x82"
    )

    def _run(self, tmp: str, obj_bytes: bytes):
        def fake_cdn(_session, _host, name, **_kwargs):
            if name == "objhash":
                return obj_bytes
            if name == "mtlhash":
                return b"newmtl m\nmap_Ka 30DAY-tex\nmap_Kd 30DAY-tex\n"
            return self.PNG_BYTES

        with patch.object(avatar, "resolve_user_id", return_value=42), \
             patch.object(avatar, "fetch_3d_manifest", return_value=(
                 {"obj": "objhash", "mtl": "mtlhash", "textures": ["30DAY-tex"]},
                 "t3.rbxcdn.com")), \
             patch.object(avatar, "_download_cdn", side_effect=fake_cdn):
            return avatar.download_avatar_model("MertaStudios", Path(tmp))

    def test_mtl_on_disk_matches_saved_texture_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            info = self._run(tmp, b"v 0 0 0\nf 1 1 1\n")
            self.assertTrue((Path(tmp) / "30DAY-tex.png").exists())
            mtl = (Path(tmp) / "avatar.mtl").read_text(encoding="utf-8")
            self.assertNotIn("map_Ka", mtl)
            self.assertIn("map_Kd 30DAY-tex.png", mtl)
            self.assertEqual(info["textures"], ["30DAY-tex.png"])

    def test_obj_gets_exactly_one_mtllib_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._run(tmp, b"mtllib irgendeinhash\nv 0 0 0\n")
            obj = (Path(tmp) / "avatar.obj").read_text(encoding="utf-8")
            self.assertTrue(obj.startswith("mtllib avatar.mtl\n"))
            self.assertNotIn("irgendeinhash", obj)
            self.assertEqual(obj.count("mtllib"), 1)

    def test_creates_manifest_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            info = self._run(tmp, b"v 0 0 0\nf 1 1 1\n")
            manifest_file = Path(tmp) / "manifest.json"
            self.assertTrue(manifest_file.exists())
            data = json.loads(manifest_file.read_text(encoding="utf-8"))
            self.assertEqual(data.get("rig_type"), "R15")
            self.assertTrue(data.get("is_rigged"))

    def test_invalid_image_bytes_are_rejected(self):
        self.assertFalse(avatar._is_valid_image(b"<html>error</html>"))
        self.assertFalse(avatar._is_valid_image(b""))
        self.assertTrue(avatar._is_valid_image(self.PNG_BYTES))


class RiggingAndTestModelTests(unittest.TestCase):
    def test_make_test_model_creates_15_r15_parts(self):
        with tempfile.TemporaryDirectory() as tmp:
            info = avatar.make_test_model(Path(tmp))
            self.assertTrue((Path(tmp) / "avatar.obj").exists())
            self.assertTrue((Path(tmp) / "manifest.json").exists())
            manifest = json.loads((Path(tmp) / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest.get("rig_type"), "R15")
            self.assertEqual(len(manifest.get("parts", [])), 15)
            for expected_part in ("Head", "UpperTorso", "LowerTorso", "LeftUpperArm", "RightFoot"):
                self.assertTrue((Path(tmp) / f"{expected_part}.obj").exists())


class RobloxMeshParserTests(unittest.TestCase):
    def test_parse_v1_ascii_mesh(self):
        v1_text = b"version 1.00\n1\n[0,0,0][0,1,0][0,0,0][1,0,0][0,1,0][1,0,0][0,1,0][0,1,0][0,1,0]\n"
        mesh = roblox_mesh.parse_roblox_mesh(v1_text)
        self.assertEqual(mesh.version, "1.00")
        self.assertEqual(len(mesh.vertices), 3)
        self.assertEqual(len(mesh.faces), 1)
        obj_text = mesh.to_obj("Part")
        self.assertIn("o Part", obj_text)
        self.assertIn("v 0.000000 0.000000 0.000000", obj_text)

    def test_parse_v2_binary_mesh(self):
        hdr = struct.pack("<HBBII", 12, 40, 12, 3, 1)
        v1 = struct.pack("<ffffffffBBBBBBBB", 0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 255, 255, 255, 255)
        v2 = struct.pack("<ffffffffBBBBBBBB", 1, 0, 0, 0, 1, 0, 1, 0, 0, 0, 0, 0, 255, 255, 255, 255)
        v3 = struct.pack("<ffffffffBBBBBBBB", 0, 1, 0, 0, 1, 0, 0, 1, 0, 0, 0, 0, 255, 255, 255, 255)
        f1 = struct.pack("<III", 0, 1, 2)
        v2_data = b"version 2.00\n" + hdr + v1 + v2 + v3 + f1
        mesh = roblox_mesh.parse_roblox_mesh(v2_data)
        self.assertEqual(mesh.version, "2.00")
        self.assertEqual(len(mesh.vertices), 3)
        self.assertEqual(len(mesh.faces), 1)


class UpdaterTests(unittest.TestCase):
    def test_api_success(self):
        fake = MagicMock()
        fake.ok = True
        fake.json.return_value = {"sha": "a" * 40}
        with patch("server.updater.requests.get", return_value=fake):
            sha, err = updater.remote_sha_detailed()
        self.assertEqual(sha, "a" * 40)
        self.assertEqual(err, "")


class SessionHeaderTests(unittest.TestCase):
    def test_session_sends_api_key(self):
        with patch.object(config, "ROBLOX_API_KEY", "secret-key"):
            session = avatar._session()
        self.assertEqual(session.headers.get("x-api-key"), "secret-key")

    def test_session_without_key_has_no_header(self):
        with patch.object(config, "ROBLOX_API_KEY", ""):
            session = avatar._session()
        self.assertNotIn("x-api-key", {k.lower() for k in session.headers.keys()})


class BlenderSceneHelperTests(unittest.TestCase):
    def test_cframe_to_blender_matrix(self):
        # Identity at (5, 10, 15)
        cf = [5.0, 10.0, 15.0, 1, 0, 0, 0, 1, 0, 0, 0, 1]
        mat = blender_render.cframe_to_blender_matrix(cf)
        # Position in Blender should be (5, -15, 10)
        self.assertAlmostEqual(mat[0][3], 5.0)
        self.assertAlmostEqual(mat[1][3], -15.0)
        self.assertAlmostEqual(mat[2][3], 10.0)

    def test_heart_hands_assets_exist(self):
        self.assertTrue((config.MODELS_DIR / "heart_hands.obj").is_file())
        self.assertTrue((config.HANDS_DIR / "heart_hands.obj").is_file())


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

    def test_health_endpoint(self):
        if not self.client:
            self.skipTest("fastapi TestClient nicht verfuegbar")
        resp = self.client.get("/health")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["status"], "ok")
        self.assertIn("studio_url", body)
        self.assertIn("queue_length", body)

    def test_create_scene_job_and_check_status(self):
        if not self.client:
            self.skipTest("fastapi TestClient nicht verfuegbar")

        scene_payload = {
            "avatars": [
                {
                    "username": "TEST-MODE",
                    "material_mode": "GLAS",
                    "glass_strength": 0.85,
                    "heart_hands": True,
                    "skin_color": [245, 205, 170],
                    "parts": {
                        "Head": {"cframe": [0, 5, 0, 1, 0, 0, 0, 1, 0, 0, 0, 1], "size": [1, 1, 1]},
                        "UpperTorso": {"cframe": [0, 3.8, 0, 1, 0, 0, 0, 1, 0, 0, 0, 1], "size": [2, 1.6, 1]},
                    }
                }
            ],
            "objects": [
                {
                    "model_name": "heart_hands",
                    "material_mode": "DURCHSICHTIGES_GLAS",
                    "glass_strength": 0.9,
                    "cframe": [0, 2, -5, 1, 0, 0, 0, 1, 0, 0, 0, 1],
                    "size": [1.5, 1.5, 1.5],
                }
            ],
            "camera": {
                "position": [0, 0, 0],
                "target": [0, 0, -10],
            }
        }

        resp = self.client.post("/jobs", json=scene_payload)
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertIn("job_id", body)
        self.assertIn("state", body)
        self.assertIn("queue_position", body)
        job_id = body["job_id"]

        # Status abfragen
        st_resp = self.client.get(f"/jobs/{job_id}")
        self.assertEqual(st_resp.status_code, 200)
        st_body = st_resp.json()
        self.assertTrue(st_body["exists"])
        self.assertEqual(st_body["job_id"], job_id)
        self.assertIn(st_body["state"], ("queued", "active", "done"))

    def test_unknown_job_returns_404(self):
        if not self.client:
            self.skipTest("fastapi TestClient nicht verfuegbar")
        resp = self.client.get("/jobs/nonexistent123")
        self.assertEqual(resp.status_code, 404)

    def test_token_protects_jobs_but_not_health(self):
        if not self.client:
            self.skipTest("fastapi TestClient nicht verfuegbar")
        with patch.object(config, "BRS_ACCESS_TOKEN", "secret"):
            denied = self.client.post("/jobs", json={"username": "Roblox"})
            self.assertEqual(denied.status_code, 401)
            self.assertIn("RENDER_ACCESS_TOKEN", denied.json()["detail"])

            # Mit Token erfolgreich
            allowed = self.client.post(
                "/jobs",
                json={"username": "Roblox"},
                headers={"X-BRS-Token": "secret"}
            )
            self.assertEqual(allowed.status_code, 200)

            health = self.client.get("/health")
            self.assertEqual(health.status_code, 200)

    def test_cleanup_expired_jobs_after_retention_days(self):
        mgr = self.appmod.MANAGER
        old_time = time.time() - (8 * 86400) # 8 Tage alt
        with tempfile.TemporaryDirectory() as tmpdir:
            job_id = "test_expired_1"
            mgr.jobs[job_id] = {
                "id": job_id,
                "state": "done",
                "created_at": old_time,
                "dir": tmpdir,
            }
            # Vor Cleanup existiert
            self.assertIn(job_id, mgr.jobs)
            mgr._cleanup_expired()
            # Nach Cleanup entfernt
            self.assertNotIn(job_id, mgr.jobs)


if __name__ == "__main__":
    unittest.main()

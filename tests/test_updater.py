import hashlib
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ghosttranslate.updater import (
    TRUSTED_DOWNLOAD_PREFIX,
    ReleaseInfo,
    UpdateCancelled,
    UpdateError,
    download_installer,
    is_newer,
    parse_version,
    release_from_json,
)


def _release_json(**overrides):
    data = {
        "tag_name": "v3.5",
        "html_url": "https://github.com/Brenon28/GhostTranslate/releases/tag/v3.5",
        "body": "Что нового",
        "draft": False,
        "prerelease": False,
        "assets": [
            {"name": "notes.txt", "browser_download_url": TRUSTED_DOWNLOAD_PREFIX + "v3.5/notes.txt", "size": 10},
            {
                "name": "GhostTranslate_v3.5_Setup.exe",
                "browser_download_url": TRUSTED_DOWNLOAD_PREFIX + "v3.5/GhostTranslate_v3.5_Setup.exe",
                "size": 1234,
                "digest": "sha256:ABCDEF",
            },
        ],
    }
    data.update(overrides)
    return data


class VersionTests(unittest.TestCase):
    def test_parse_version(self):
        self.assertEqual(parse_version("v3.10"), (3, 10))
        self.assertEqual(parse_version("3.4.0"), (3, 4))
        self.assertEqual(parse_version(""), ())

    def test_is_newer(self):
        self.assertTrue(is_newer("v3.5", "3.4"))
        self.assertTrue(is_newer("3.10", "3.9"))
        self.assertFalse(is_newer("v3.4", "3.4"))
        self.assertFalse(is_newer("3.4.0", "3.4"))
        self.assertFalse(is_newer("v3.3", "3.4"))
        self.assertFalse(is_newer("latest", "3.4"))


class ReleaseJsonTests(unittest.TestCase):
    def test_picks_installer_and_digest(self):
        release = release_from_json(_release_json())
        self.assertEqual(release.version, "3.5")
        self.assertEqual(release.asset_name, "GhostTranslate_v3.5_Setup.exe")
        self.assertEqual(release.asset_size, 1234)
        self.assertEqual(release.sha256, "abcdef")

    def test_draft_prerelease_and_foreign_urls_are_ignored(self):
        self.assertIsNone(release_from_json(_release_json(draft=True)))
        self.assertIsNone(release_from_json(_release_json(prerelease=True)))
        data = _release_json()
        data["assets"][1]["browser_download_url"] = "https://example.com/GhostTranslate_v3.5_Setup.exe"
        self.assertIsNone(release_from_json(data))
        self.assertIsNone(release_from_json(None))

    def test_missing_digest_is_allowed(self):
        data = _release_json()
        del data["assets"][1]["digest"]
        self.assertIsNone(release_from_json(data).sha256)


class DownloadTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.payload = os.urandom(600 * 1024)
        self.source = os.path.join(self.tmp.name, "source.exe")
        with open(self.source, "wb") as f:
            f.write(self.payload)
        self.out_dir = os.path.join(self.tmp.name, "out")

    def tearDown(self):
        self.tmp.cleanup()

    def _release(self, sha256, size=None):
        return ReleaseInfo(
            version="3.5", notes="", page_url="", asset_name="GhostTranslate_v3.5_Setup.exe",
            asset_url=Path(self.source).as_uri(), asset_size=len(self.payload) if size is None else size,
            sha256=sha256,
        )

    def test_download_verifies_hash_and_reports_progress(self):
        progress = []
        path = download_installer(
            self._release(hashlib.sha256(self.payload).hexdigest()),
            lambda received, total: progress.append((received, total)),
            lambda: False,
            self.out_dir,
        )
        with open(path, "rb") as f:
            self.assertEqual(f.read(), self.payload)
        self.assertEqual(progress[-1], (len(self.payload), len(self.payload)))
        self.assertGreater(len(progress), 1)

    def test_wrong_hash_or_size_leaves_no_file(self):
        with self.assertRaises(UpdateError):
            download_installer(self._release("0" * 64), lambda *_: None, lambda: False, self.out_dir)
        with self.assertRaises(UpdateError):
            download_installer(self._release(None, size=1), lambda *_: None, lambda: False, self.out_dir)
        self.assertEqual(os.listdir(self.out_dir), [])

    def test_cancel_removes_partial_file(self):
        with self.assertRaises(UpdateCancelled):
            download_installer(self._release(None), lambda *_: None, lambda: True, self.out_dir)
        self.assertEqual(os.listdir(self.out_dir), [])


if __name__ == "__main__":
    unittest.main()

# SPDX-License-Identifier: GPL-2.0-or-later
import hashlib
import io
import json
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import catalog
from promote import verify_image


def build(variant="qmodem-next", day=1, driver="mt76"):
    repo = "Starktomy/OpenWRT-CI-H5000M" if driver == "mt76" else "Starktomy/CloseWRT-CI-H5000M"
    source = "immortalwrt-master" if driver == "mt76" else "chasey-dev-25.12-dev-wifi7"
    tag = f"H5000M-{variant}-{source}-26.11.{day:02d}-08.00.00"
    name = f"H5000M-{variant}-202611{day:02d}-sysupgrade.bin"
    return repo, {
        "tag_name": tag, "draft": False, "prerelease": False,
        "published_at": f"2026-11-{day:02d}T00:00:00Z",
        "body": f"内核版本：6.12.116\n风扇插件：test 3.2.0\n{'a' * 64}  {name}\n",
        "assets": [{"name": name, "size": 80000000, "state": "uploaded", "digest": "sha256:" + "a" * 64,
                    "browser_download_url": f"https://github.com/{repo}/releases/download/{tag}/{name}"}],
    }


class CatalogTests(unittest.TestCase):
    def test_ten_groups_are_limited_to_three(self):
        repos = {repo: [] for repo in catalog.SOURCES}
        for driver in ("mt76", "mt_wifi7"):
            for variant in catalog.VARIANTS:
                for day in range(1, 6):
                    repo, release = build(variant, day, driver)
                    repos[repo].append(release)
        result = catalog.build_catalog(repos)
        self.assertEqual(len(result["entries"]), 30)
        self.assertTrue(all(e["published_at"][8:10] in ("03", "04", "05") for e in result["entries"]))

    def test_hash_is_required_and_digest_must_agree(self):
        repo, release = build()
        release["body"] = "No checksum"
        self.assertIsNone(catalog.parse_development(repo, release))
        _, release = build()
        release["assets"][0]["digest"] = "sha256:" + "b" * 64
        with self.assertRaisesRegex(ValueError, "digest"):
            catalog.parse_development(repo, release)

    def test_wrong_variant_and_download_source_are_rejected(self):
        repo, release = build()
        release["assets"][0]["name"] = "H5000M-qmodem-20261101-sysupgrade.bin"
        self.assertIsNone(catalog.parse_development(repo, release))
        _, release = build()
        release["assets"][0]["browser_download_url"] = "https://example.invalid/firmware.bin"
        with self.assertRaises(ValueError):
            catalog.parse_development(repo, release)

    def test_stable_copy_survives_removal_of_ci_release(self):
        repo, release = build()
        original = catalog.parse_development(repo, release)
        metadata = {**original, "source_repo": repo, "source_tag": release["tag_name"]}
        tag = f"stable-{original['driver']}-{original['variant']}-{original['version']}"
        release["tag_name"] = tag
        release["assets"][0]["browser_download_url"] = f"https://github.com/{catalog.OTA_REPO}/releases/download/{tag}/{original['asset']}"
        release["body"] += "\n<!-- h5000m-ota:" + json.dumps(metadata) + " -->"
        result = catalog.build_catalog({catalog.OTA_REPO: [release]})
        self.assertEqual(len(result["entries"]), 1)
        entry = result["entries"][0]
        self.assertEqual(entry["channel"], "stable")
        self.assertEqual(entry["repo"], catalog.OTA_REPO)
        self.assertEqual(entry["source_repo"], repo)
        self.assertIn("/H5000M-OTA/releases/download/", entry["url"])

    def test_draft_does_not_become_stable(self):
        _, release = build()
        release["draft"] = True
        self.assertIsNone(catalog.parse_stable(release))

    def test_unchanged_catalog_does_not_create_empty_commits(self):
        repo, release = build()
        previous = catalog.build_catalog({repo: [release]})
        previous["generated_at"] = "2026-11-01T00:00:00Z"
        self.assertEqual(catalog.build_catalog({repo: [release]}, previous), previous)

    def test_promotion_checks_hash_and_actual_board(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "firmware.bin"
            with tarfile.open(path, "w") as tar:
                for name, value in [("CONTROL", b"BOARD=hiveton_h5000m\n"), ("kernel", b"kernel"), ("root", b"root")]:
                    item = tarfile.TarInfo("sysupgrade-hiveton_h5000m/" + name)
                    item.size = len(value)
                    tar.addfile(item, io.BytesIO(value))
            verify_image(path, hashlib.sha256(path.read_bytes()).hexdigest())
            with self.assertRaisesRegex(ValueError, "SHA256"):
                verify_image(path, "0" * 64)
            with tarfile.open(path, "w") as tar:
                value = b"BOARD=other_device\n"
                item = tarfile.TarInfo("image/CONTROL")
                item.size = len(value)
                tar.addfile(item, io.BytesIO(value))
            with self.assertRaises(ValueError):
                verify_image(path, hashlib.sha256(path.read_bytes()).hexdigest())


if __name__ == "__main__":
    unittest.main()

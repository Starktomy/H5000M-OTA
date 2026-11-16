#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""将两个编译仓库和长期稳定版汇总为 H5000M OTA 目录。"""

import argparse
from collections import defaultdict
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import subprocess

OTA_REPO = "Starktomy/H5000M-OTA"
DEVICE = "hiveton,h5000m"
VARIANTS = ("qmodem-next", "qmodem", "modem-pro", "mt5700", "mt5700m")
SOURCES = {
    "Starktomy/OpenWRT-CI-H5000M": {
        "immortalwrt-master": "mt76", "VIKINGYFY-owrt": "mt76", "chasey-dev-25.12": "mt76",
    },
    "Starktomy/CloseWRT-CI-H5000M": {"chasey-dev-25.12-dev-wifi7": "mt_wifi7"},
}
MARKER = re.compile(r"<!-- h5000m-ota:(\{[^\n]+\}) -->")


def api(endpoint):
    result = subprocess.run(["gh", "api", endpoint], check=True, capture_output=True, text=True)
    return json.loads(result.stdout)


def releases(repo):
    result = []
    page = 1
    while True:
        batch = api(f"repos/{repo}/releases?per_page=100&page={page}")
        if not isinstance(batch, list):
            raise ValueError(f"{repo}: 无效的 Release API 返回")
        if not batch:
            return result
        result.extend(batch)
        page += 1


def parse_development(repo, release):
    if repo not in SOURCES or release.get("draft"):
        return None
    tag = release.get("tag_name", "")
    for variant in VARIANTS:
        match = re.fullmatch(
            rf"H5000M-{re.escape(variant)}-(.+)-(\d{{2}}\.\d{{2}}\.\d{{2}}-\d{{2}}\.\d{{2}}\.\d{{2}})", tag,
        )
        if match and match[1] in SOURCES[repo]:
            datetime.strptime(match[2], "%y.%m.%d-%H.%M.%S")
            return entry(repo, release, SOURCES[repo][match[1]], variant, match[2], "development")
    return None


def entry(repo, release, driver, variant, version, channel):
    name_re = re.compile(rf"H5000M-{re.escape(variant)}-\d{{8}}-sysupgrade\.bin")
    assets = [a for a in release.get("assets", []) if name_re.fullmatch(a.get("name", ""))
              and a.get("state") == "uploaded" and 15 * 1024**2 <= a.get("size", 0) <= 512 * 1024**2]
    if len(assets) != 1:
        return None
    asset = assets[0]
    body = release.get("body") or ""
    hashes = re.findall(r"^([0-9a-fA-F]{64})\s+\*?" + re.escape(asset["name"]) + r"\s*$", body, re.M)
    if len(set(h.lower() for h in hashes)) != 1:
        return None
    sha256 = hashes[0].lower()
    digest = asset.get("digest")
    if digest and digest != "sha256:" + sha256:
        raise ValueError(f"{release['tag_name']}: GitHub digest 与发布校验值不一致")
    tag = release["tag_name"]
    url = f"https://github.com/{repo}/releases/download/{tag}/{asset['name']}"
    if asset.get("browser_download_url") != url:
        raise ValueError(f"{tag}: 固件下载地址与来源不一致")
    published = release["published_at"]
    datetime.fromisoformat(published.replace("Z", "+00:00"))
    kernel = re.search(r"内核版本[：:]\s*(\S+)", body)
    fan = re.search(r"风扇插件[：:]\s*([^\n]+)", body)
    client = re.search(r"OTA 客户端[：:]\s*([0-9a-f]{40})(?:\s|$)", body)
    return {
        "id": f"{channel}:{driver}:{variant}:{tag}",
        "device": DEVICE, "driver": driver, "variant": variant, "channel": channel,
        "version": version, "published_at": published, "repo": repo, "tag": tag,
        "asset": asset["name"], "size": asset["size"], "sha256": sha256, "url": url,
        "release_url": f"https://github.com/{repo}/releases/tag/{tag}",
        "kernel": kernel[1] if kernel else "", "fan": fan[1].strip() if fan else "",
        "ota_client_commit": client[1] if client else "",
    }


def parse_stable(release):
    if release.get("draft") or release.get("prerelease"):
        return None
    match = MARKER.search(release.get("body") or "")
    if not match:
        return None
    metadata = json.loads(match[1])
    driver, variant, version = (metadata.get(k) for k in ("driver", "variant", "version"))
    if driver not in ("mt76", "mt_wifi7") or variant not in VARIANTS:
        raise ValueError("稳定版的驱动或方案无效")
    if not isinstance(version, str) or not re.fullmatch(r"\d{2}\.\d{2}\.\d{2}-\d{2}\.\d{2}\.\d{2}", version):
        raise ValueError("稳定版的构建版本无效")
    datetime.strptime(version, "%y.%m.%d-%H.%M.%S")
    expected_tag = f"stable-{driver}-{variant}-{version}"
    if release.get("tag_name") != expected_tag or metadata.get("device") != DEVICE:
        raise ValueError("稳定版标签或机型与元数据不一致")
    result = entry(OTA_REPO, release, driver, variant, version, "stable")
    if result:
        if result["sha256"] != metadata.get("sha256"):
            raise ValueError("稳定版元数据与固件 SHA256 不一致")
        source_repo, source_tag = metadata.get("source_repo"), metadata.get("source_tag")
        if source_repo not in SOURCES or not isinstance(source_tag, str) or not any(
            source_tag == f"H5000M-{variant}-{source}-{version}" and source_driver == driver
            for source, source_driver in SOURCES[source_repo].items()
        ):
            raise ValueError("稳定版来源与驱动、方案或构建版本不一致")
        result["source_repo"] = source_repo
        result["source_tag"] = source_tag
    return result


def build_catalog(by_repo, previous=None):
    groups = defaultdict(list)
    for repo in SOURCES:
        for release in by_repo.get(repo, []):
            item = parse_development(repo, release)
            if item:
                groups[(item["driver"], item["variant"])].append(item)
    entries = []
    for key in sorted(groups):
        entries.extend(sorted(groups[key], key=lambda e: (e["published_at"], e["tag"]), reverse=True)[:3])
    for release in by_repo.get(OTA_REPO, []):
        item = parse_stable(release)
        if item:
            entries.append(item)
    entries.sort(key=lambda e: (e["published_at"], e["id"]), reverse=True)
    result = {
        "schema_version": 1, "device": DEVICE,
        "retention": {"development_per_driver_profile": 3, "stable": "permanent"},
        "keep_config_policy": "same_driver_and_variant",
        "entries": entries,
    }
    if previous and {k: v for k, v in previous.items() if k != "generated_at"} == result:
        result["generated_at"] = previous["generated_at"]
    else:
        result["generated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("catalog.json"))
    args = parser.parse_args()
    previous = json.loads(args.output.read_text()) if args.output.exists() else None
    data = build_catalog({repo: releases(repo) for repo in (*SOURCES, OTA_REPO)}, previous)
    args.output.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    print(f"Generated {len(data['entries'])} firmware entries; stable releases are never rotated")


if __name__ == "__main__":
    main()

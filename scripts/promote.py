#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""把指定且已验证的 CI 构建复制到 OTA Releases；不自动认定稳定版。"""

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tarfile
import tempfile

from catalog import DEVICE, OTA_REPO, SOURCES, api, parse_development


def verify_image(path, expected_sha256):
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != expected_sha256:
        raise ValueError("下载文件的 SHA256 与发布记录不一致")
    with tarfile.open(path, mode="r:") as image:
        controls = [m for m in image.getmembers() if m.isfile() and m.name.endswith("/CONTROL")]
        roots = [m for m in image.getmembers() if m.isfile() and m.name.endswith("/root")]
        kernels = [m for m in image.getmembers() if m.isfile() and m.name.endswith("/kernel")]
        if len(controls) != 1 or len(roots) != 1 or len(kernels) != 1:
            raise ValueError("镜像缺少唯一的 H5000M CONTROL / kernel / root")
        if controls[0].size > 4096:
            raise ValueError("镜像 CONTROL 异常")
        if image.extractfile(controls[0]).read().decode().strip() != "BOARD=hiveton_h5000m":
            raise ValueError("镜像不属于 H5000M")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-repo", choices=list(SOURCES), required=True)
    parser.add_argument("--source-tag", required=True)
    parser.add_argument("--notes", default="")
    args = parser.parse_args()
    if not re.fullmatch(r"H5000M-[A-Za-z0-9_.-]+-\d{2}\.\d{2}\.\d{2}-\d{2}\.\d{2}\.\d{2}", args.source_tag):
        parser.error("来源标签必须是完整的 H5000M CI 构建标签")
    source = json.loads(subprocess.check_output([
        "gh", "release", "view", args.source_tag, "--repo", args.source_repo,
        "--json", "tagName,body,assets,isDraft,publishedAt",
    ], text=True))
    # 使用 REST 的原始资产字段，以便与目录生成器进行完全相同的验证。
    release = api(f"repos/{args.source_repo}/releases/tags/{source['tagName']}")
    item = parse_development(args.source_repo, release)
    if item is None:
        raise ValueError("来源不是含校验值和完整固件的 H5000M 构建")
    tag = f"stable-{item['driver']}-{item['variant']}-{item['version']}"
    existing = subprocess.run(["gh", "release", "view", tag, "--repo", OTA_REPO], capture_output=True)
    if existing.returncode == 0:
        raise ValueError(f"{tag} 已存在；稳定版不能覆盖")
    with tempfile.TemporaryDirectory(prefix="h5000m-stable-") as directory:
        work = Path(directory)
        subprocess.run(["gh", "release", "download", args.source_tag, "--repo", args.source_repo,
                        "--pattern", item["asset"], "--dir", str(work)], check=True)
        image = work / item["asset"]
        verify_image(image, item["sha256"])
        metadata = {**item, "device": DEVICE, "source_repo": args.source_repo, "source_tag": args.source_tag}
        metadata_path = work / "h5000m-release.json"
        metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n")
        sums = work / "sha256sums"
        sums.write_text(item["sha256"] + "  " + item["asset"] + "\n")
        body = work / "release.md"
        body.write_text(
            f"H5000M 稳定版 · {item['driver']} · {item['variant']}\n\n"
            f"来源：{item['release_url']}\n\n{args.notes}\n\n"
            f"内核版本：{item['kernel']}\n风扇插件：{item['fan']}\n\n"
            f"```\n{item['sha256']}  {item['asset']}\n```\n\n"
            f"<!-- h5000m-ota:{json.dumps(metadata, ensure_ascii=False, separators=(',', ':'))} -->\n"
        )
        # 文件全部下载并验证后才创建草稿，上传完成后一次性发布。
        subprocess.run(["gh", "release", "create", tag, "--repo", OTA_REPO, "--draft",
                        "--target", "main", "--title", tag, "--notes-file", str(body)], check=True)
        subprocess.run(["gh", "release", "upload", tag, str(image), str(sums), str(metadata_path),
                        "--repo", OTA_REPO], check=True)
        subprocess.run(["gh", "release", "edit", tag, "--repo", OTA_REPO, "--draft=false"], check=True)
    print(f"Published {tag}; the OTA copy remains available after CI history rotation")


if __name__ == "__main__":
    main()

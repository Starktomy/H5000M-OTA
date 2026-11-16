#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""检查 OTA 包安装资源和 RPC 权限契约，二进制由 CI 交叉编译生成。"""
import json
from pathlib import Path
import re

base = Path(__file__).resolve().parents[1] / 'package/luci-app-online-upgrade'
makefile = (base / 'Makefile').read_text()
for path in re.findall(r'\./(root/[A-Za-z0-9/_.-]+)', makefile):
    if path == 'root/usr/bin/online-upgrade':
        continue
    assert (base / path).is_file(), f'安装资源缺失：{path}'
for path in (base / 'root').rglob('*'):
    if path.is_file():
        assert b'\r' not in path.read_bytes(), f'文本文件仍含 CR：{path}'
rpc = (base / 'root/usr/share/rpcd/ucode/luci.online-upgrade').read_text()
acl = json.loads((base / 'root/usr/share/rpcd/acl.d/luci-app-online-upgrade.json').read_text())['luci-app-online-upgrade']
for method in ('h5000m_catalog', 'h5000m_policy'):
    assert method in acl['read']['ubus']['luci.online-upgrade']
    assert re.search(r'^\s*' + method + r': \{', rpc, re.M)
assert 'h5000m_select' in acl['write']['ubus']['luci.online-upgrade']
assert "args: { id: '', keep: false }" in rpc
assert "args: { force: false }" in rpc
print('Package resources and RPC ACL contract passed')

# H5000M OTA

Hiveton H5000M / MT5700M 的统一固件目录、定制 OTA 客户端与稳定版发布仓库。

- [下载页面](https://starktomy.github.io/H5000M-OTA/)
- [机器可读版本目录](https://raw.githubusercontent.com/Starktomy/H5000M-OTA/main/catalog.json)
- [稳定版 Releases](https://github.com/Starktomy/H5000M-OTA/releases)
- 日常构建：[开源 mt76](https://github.com/Starktomy/OpenWRT-CI-H5000M/releases)、[厂商 SDK mt_wifi7](https://github.com/Starktomy/CloseWRT-CI-H5000M/releases)

## 升级规则

| 当前 → 目标 | 保留配置 |
|---|---|
| 相同驱动、相同模组方案，更新到新日期构建 | 可选；默认清空 |
| 相同驱动、相同模组方案，重装或切换历史构建 | 可选；默认清空 |
| 开源 mt76 ↔ 厂商 SDK mt_wifi7 | 必须清空 |
| 任意两种不同模组方案 | 必须清空 |
| 当前固件缺少内置身份标识 | 必须清空 |

“相同”指 **驱动＋模组方案相同**，无需构建号完全相同。发布通道（日常/稳定）不改变此规则。

设备 OTA 页面依次选择驱动、方案、通道和版本，点击“应用此版本并检查”。仅符合条件时可勾选保留配置；选择变化后必须重新应用。确认刷写时会明确显示保留或清空。

身份由 CI 写入 `/usr/share/h5000m/firmware.json`，避免普通配置备份覆盖新系统的真实身份。后端根据当前身份和实际解析的目标 Release 再次判断：清空模式只执行 `sysupgrade -n`，不注入配置备份，不恢复旧软件包；保留模式先成功备份，再通过 `sysupgrade -f` 恢复。页面参数不能绕过这条规则。

版本比较使用镜像内置的完整构建时间（含时分秒），同一天的不同构建不会混为同版，稳定副本也沿用原构建号。机型匹配、SHA256 与 `sysupgrade -T` 预检始终执行。“重装 / 切换版本”仅允许相同或更早构建，不允许跳过兼容性检查。定制客户端随固件更新，禁用通用上游插件自升级和旧包自动重装。

此前已发布的固件未包含本客户端和身份标识。首次迁移请下载对应的 `*-sysupgrade.bin`，在原系统的刷写页面取消保留配置，刷入带本次改造的新固件。普通 LuCI 手动刷写不经过本插件；手动跨组刷写也必须取消保留配置。

## 发布与保留

两 CI 仓库按 `(驱动, 模组方案)` 独立保留最近 **3 个完整发布**，十组共最多 30 个日常版本。每组当前不足 3 版时展示实际数量。同驱动的不同源码共用该方案的 3 个名额。

本仓库的 `Sync OTA Catalog` 每小时的第 17、47 分钟同步两个构建仓库，也支持手动执行。目录只收录已上传完整 sysupgrade、具备 SHA256 且来源一致的固件；未完成的上传和草稿不进入目录。GitHub Actions 排队可能导致同步延后。

稳定版长期保存在 **本仓库 Releases**，使用 `stable-驱动-方案-构建时间` 标签。固件文件会复制到这里，连同校验单和来源元数据独立保存；原 CI 版本被轮换后，稳定版仍可下载。不会自动把日常构建当成已实机验证的稳定版。

完成实机验证后，在本仓库 Actions 中手动运行 **Promote Stable Firmware**：

1. 选择来源 CI 仓库。
2. 填入完整构建标签，例如 `H5000M-qmodem-next-immortalwrt-master-26.11.16-08.00.00`，不能填 `latest`。
3. 填写实机验证情况和发布说明。

工作流下载并核验 SHA256、H5000M 镜像 CONTROL 后建立草稿，上传固件、`sha256sums`、`h5000m-release.json`，全部成功才发布并刷新目录和下载页面。相同稳定版标签不能覆盖。上传中断时草稿不对设备开放，可删除未发布草稿后重新运行。

## 五套方案

| 方案标识 | 模组管理 | 风扇 |
|---|---|---|
| `qmodem-next` | QModem Next | LianXia233 新版 Rust 风扇 |
| `qmodem` | 经典 QModem | FAN789 原版 |
| `modem-pro` | Modem Pro | FAN789 原版 |
| `mt5700` | luci-app-mt5700 | LianXia233 新版 Rust 风扇 |
| `mt5700m` | luci-app-mt5700m + transport | FAN789 原版 |

驱动标签仅描述无线驱动；其余系统和软件包的许可分别遵循对应上游。

## 维护和验证

客户端源码在 `package/luci-app-online-upgrade`，基于 LianXia233/gooyjq 的 2.6.10 版，固定来源见 [NOTICE](NOTICE)。两个 CI 从该子目录导入并交叉编译 aarch64 静态 musl 后端，不下载上游预编译插件。

```sh
python3 -m unittest discover -s tests -p 'test_catalog.py' -v
node --test tests/test_frontend.cjs
python3 scripts/check_package.py
cargo test --locked --manifest-path package/luci-app-online-upgrade/rust/Cargo.toml
python3 tests/browser_policy.py  # 需 Chrome / Chromium
```

测试覆盖十组轮换、稳定副本、校验值、升级保留策略与完整 LuCI 页面浏览器交互。自动化测试与成功构建不替代实机刷写、5G 模组、网络吞吐和风扇测试。

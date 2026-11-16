// SPDX-License-Identifier: GPL-2.0-or-later
// H5000M 的固件身份、统一目录和跨驱动/方案升级约束。

use crate::json::{self, Value};
use crate::uci;
use regex::Regex;
use std::time::Duration;

pub const DEVICE: &str = "hiveton,h5000m";
pub const CATALOG_URL: &str =
    "https://raw.githubusercontent.com/Starktomy/H5000M-OTA/main/catalog.json";
const IDENTITY_PATH: &str = "/usr/share/h5000m/firmware.json";
const VARIANTS: [&str; 5] = ["qmodem-next", "qmodem", "modem-pro", "mt5700", "mt5700m"];

#[derive(Debug, Clone, PartialEq)]
pub struct Identity {
    pub driver: String,
    pub variant: String,
}

fn text<'a>(value: &'a Value, key: &str) -> &'a str {
    value.get(key).and_then(Value::as_str).unwrap_or("")
}

impl Identity {
    pub fn from_value(value: &Value) -> Option<Self> {
        let driver = text(value, "driver");
        let variant = text(value, "variant");
        if value.get("schema_version").and_then(Value::as_u64) != Some(1)
            || text(value, "device") != DEVICE
            || !["mt76", "mt_wifi7"].contains(&driver)
            || !VARIANTS.contains(&variant)
        {
            return None;
        }
        Some(Self { driver: driver.into(), variant: variant.into() })
    }
}

pub fn current() -> Option<Identity> {
    let data = std::fs::read_to_string(IDENTITY_PATH).ok()?;
    Identity::from_value(&json::parse(&data).ok()?)
}

pub fn release_identity(repo: &str, tag: &str, asset: &str) -> Option<Identity> {
    let stamp = r"[0-9]{2}\.[0-9]{2}\.[0-9]{2}-[0-9]{2}\.[0-9]{2}\.[0-9]{2}";
    for variant in VARIANTS {
        let filename = Regex::new(&format!(r"^H5000M-{}-[0-9]{{8}}-sysupgrade\.bin$", regex::escape(variant))).ok()?;
        if !filename.is_match(asset) {
            continue;
        }
        let prefixes: Vec<(&str, String)> = match repo {
            "Starktomy/H5000M-OTA" => ["mt76", "mt_wifi7"].iter()
                .map(|driver| (*driver, format!("stable-{driver}-{variant}-"))).collect(),
            "Starktomy/OpenWRT-CI-H5000M" => ["immortalwrt-master", "VIKINGYFY-owrt", "chasey-dev-25.12"].iter()
                .map(|source| ("mt76", format!("H5000M-{variant}-{source}-"))).collect(),
            "Starktomy/CloseWRT-CI-H5000M" => vec![("mt_wifi7", format!("H5000M-{variant}-chasey-dev-25.12-dev-wifi7-"))],
            _ => return None,
        };
        for (driver, prefix) in prefixes {
            if Regex::new(&format!("^{}{stamp}$", regex::escape(&prefix))).ok()?.is_match(tag) {
                return Some(Identity { driver: driver.into(), variant: variant.into() });
            }
        }
        return None;
    }
    None
}

pub fn can_keep(installed: Option<&Identity>, target: &Identity) -> bool {
    installed == Some(target)
}

pub fn flash_arguments(keep: bool, backup: Option<&str>, image: &str) -> Result<Vec<String>, String> {
    if keep {
        let backup = backup.filter(|path| path.starts_with("/tmp/pre-upgrade-backup-") && path.ends_with(".tar.gz"))
            .ok_or("保留配置需要本次升级成功生成的备份")?;
        Ok(vec!["-f".into(), backup.into(), image.into()])
    } else {
        // 跨驱动/方案升级不会注入备份，也不会恢复旧软件包。
        Ok(vec!["-n".into(), image.into()])
    }
}

pub fn policy() -> Value {
    let installed = current();
    let repo = uci::get_or("repo", "");
    let tag = uci::get_or("tag", "");
    let name = uci::get_or("h5000m_asset", "");
    let target = release_identity(&repo, &tag, &name);
    let allowed = target.as_ref().is_some_and(|t| can_keep(installed.as_ref(), t));
    let identity = installed.map(|i| Value::Obj(vec![
        ("driver".into(), Value::str(&i.driver)), ("variant".into(), Value::str(&i.variant)),
    ])).unwrap_or(Value::Null);
    Value::Obj(vec![
        ("ok".into(), Value::Bool(true)), ("current".into(), identity),
        ("repo".into(), Value::str(&repo)), ("tag".into(), Value::str(&tag)),
        ("asset".into(), Value::str(&name)),
        ("can_keep".into(), Value::Bool(allowed)),
        ("keep_config".into(), Value::Bool(allowed && uci::get_or("keep_config", "0") == "1")),
    ])
}

pub fn validate_entry(entry: &Value) -> Result<Identity, String> {
    if text(entry, "device") != DEVICE {
        return Err("目录机型不匹配".into());
    }
    let identity = release_identity(text(entry, "repo"), text(entry, "tag"), text(entry, "asset"))
        .ok_or("目录来源、标签或固件名无效")?;
    if identity.driver != text(entry, "driver") || identity.variant != text(entry, "variant") {
        return Err("目录标识与固件来源不一致".into());
    }
    let channel = if text(entry, "repo") == "Starktomy/H5000M-OTA" { "stable" } else { "development" };
    let expected_id = format!("{channel}:{}:{}:{}", identity.driver, identity.variant, text(entry, "tag"));
    if text(entry, "channel") != channel || text(entry, "id") != expected_id {
        return Err("目录频道或版本 ID 与来源不一致".into());
    }
    let hash = text(entry, "sha256");
    if hash.len() != 64 || !hash.bytes().all(|b| b.is_ascii_hexdigit()) {
        return Err("目录缺少完整 SHA256".into());
    }
    let size = entry.get("size").and_then(Value::as_u64).unwrap_or(0);
    if !(15 * 1024 * 1024..=512 * 1024 * 1024).contains(&size) {
        return Err("目录固件大小超出范围".into());
    }
    let expected_url = format!("https://github.com/{}/releases/download/{}/{}",
        text(entry, "repo"), text(entry, "tag"), text(entry, "asset"));
    if text(entry, "url") != expected_url {
        return Err("目录下载地址与来源不一致".into());
    }
    let expected_release = format!("https://github.com/{}/releases/tag/{}", text(entry, "repo"), text(entry, "tag"));
    if text(entry, "release_url") != expected_release {
        return Err("目录发布页与来源不一致".into());
    }
    Ok(identity)
}

pub async fn catalog() -> Result<Value, String> {
    let response = crate::http::client().get(CATALOG_URL).timeout(Duration::from_secs(25))
        .send().await.map_err(|e| format!("获取版本目录失败：{e}"))?
        .error_for_status().map_err(|e| format!("版本目录不可用：{e}"))?;
    let data = response.text().await.map_err(|e| e.to_string())?;
    if data.len() > 4 * 1024 * 1024 {
        return Err("版本目录过大".into());
    }
    let value = json::parse(&data)?;
    if value.get("schema_version").and_then(Value::as_u64) != Some(1)
        || text(&value, "device") != DEVICE {
        return Err("版本目录格式或机型不匹配".into());
    }
    let entries = value.get("entries").and_then(Value::as_arr).ok_or("目录缺少固件列表")?;
    for entry in entries { validate_entry(entry)?; }
    Ok(value)
}

pub async fn select(id: &str, requested_keep: bool) -> Result<Value, String> {
    let data = catalog().await?;
    let entry = data.get("entries").and_then(Value::as_arr)
        .and_then(|entries| entries.iter().find(|entry| text(entry, "id") == id))
        .ok_or("所选版本已不在目录中，请刷新后重选")?;
    let target = validate_entry(entry)?;
    let allowed = can_keep(current().as_ref(), &target);
    for (key, value) in [
        ("repo", text(entry, "repo").to_string()), ("repo_url", String::new()),
        ("tag", text(entry, "tag").to_string()),
        ("firmware_pattern", format!("^{}$", regex::escape(text(entry, "asset")))),
        ("h5000m_asset", text(entry, "asset").to_string()),
        ("expected_sha256", text(entry, "sha256").to_lowercase()),
        ("h5000m_selection", id.to_string()),
        ("keep_config", if requested_keep && allowed { "1" } else { "0" }.to_string()),
    ] {
        if !uci::set(&key, &value) { return Err(format!("保存升级目标失败：{key}")); }
    }
    if !uci::commit() { return Err("保存升级设置失败".into()); }
    Ok(policy())
}

pub fn result(value: Result<Value, String>) -> i32 {
    match value {
        Ok(value) => { println!("{}", value.dump()); 0 }
        Err(error) => {
            println!("{}", Value::Obj(vec![("ok".into(), Value::Bool(false)), ("error".into(), Value::str(&error))]).dump());
            1
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn only_same_driver_and_variant_can_keep() {
        for driver in ["mt76", "mt_wifi7"] {
            for variant in VARIANTS {
                let current = Identity { driver: driver.into(), variant: variant.into() };
                for other_driver in ["mt76", "mt_wifi7"] {
                    for other_variant in VARIANTS {
                        let target = Identity { driver: other_driver.into(), variant: other_variant.into() };
                        assert_eq!(can_keep(Some(&current), &target), driver == other_driver && variant == other_variant);
                        assert!(!can_keep(None, &target));
                    }
                }
            }
        }
    }

    #[test]
    fn clean_flash_never_restores_any_backup() {
        assert_eq!(flash_arguments(false, Some("/tmp/pre-upgrade-backup-test.tar.gz"), "/tmp/firmware.bin").unwrap(),
                   vec!["-n", "/tmp/firmware.bin"]);
        assert!(flash_arguments(true, None, "/tmp/firmware.bin").is_err());
        assert_eq!(flash_arguments(true, Some("/tmp/pre-upgrade-backup-test.tar.gz"), "/tmp/firmware.bin").unwrap(),
                   vec!["-f", "/tmp/pre-upgrade-backup-test.tar.gz", "/tmp/firmware.bin"]);
    }

    #[test]
    fn identity_requires_known_schema_and_board() {
        let value = json::parse(r#"{"schema_version":1,"device":"hiveton,h5000m","driver":"mt76","variant":"qmodem-next"}"#).unwrap();
        assert!(Identity::from_value(&value).is_some());
        assert!(Identity::from_value(&Value::Null).is_none());
    }

    #[test]
    fn qmodem_next_and_qmodem_are_distinct() {
        let repo = "Starktomy/OpenWRT-CI-H5000M";
        assert_eq!(release_identity(repo, "H5000M-qmodem-next-immortalwrt-master-26.11.16-08.00.00", "H5000M-qmodem-next-20261116-sysupgrade.bin").unwrap().variant, "qmodem-next");
        assert!(release_identity(repo, "H5000M-qmodem-next-immortalwrt-master-26.11.16-08.00.00", "H5000M-qmodem-20261116-sysupgrade.bin").is_none());
        assert!(release_identity(repo, "H5000M-qmodem-next-chasey-dev-25.12-dev-wifi7-26.11.16-08.00.00", "H5000M-qmodem-next-20261116-sysupgrade.bin").is_none());
        assert!(release_identity(repo, "H5000M-qmodem-next-immortalwrt-master-unknown-26.11.16-08.00.00", "H5000M-qmodem-next-20261116-sysupgrade.bin").is_none());
        assert!(release_identity("Starktomy/H5000M-OTA", "stable-mt76-qmodem-next-unverified-26.11.16-08.00.00", "H5000M-qmodem-next-20261116-sysupgrade.bin").is_none());
    }

    #[test]
    fn catalog_rejects_mislabeled_or_unverifiable_targets() {
        let data = r#"{"device":"hiveton,h5000m","driver":"mt76","variant":"qmodem-next","channel":"development","id":"development:mt76:qmodem-next:H5000M-qmodem-next-immortalwrt-master-26.11.16-08.00.00","repo":"Starktomy/OpenWRT-CI-H5000M","tag":"H5000M-qmodem-next-immortalwrt-master-26.11.16-08.00.00","asset":"H5000M-qmodem-next-20261116-sysupgrade.bin","size":80000000,"sha256":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","url":"https://github.com/Starktomy/OpenWRT-CI-H5000M/releases/download/H5000M-qmodem-next-immortalwrt-master-26.11.16-08.00.00/H5000M-qmodem-next-20261116-sysupgrade.bin","release_url":"https://github.com/Starktomy/OpenWRT-CI-H5000M/releases/tag/H5000M-qmodem-next-immortalwrt-master-26.11.16-08.00.00"}"#;
        assert!(validate_entry(&json::parse(data).unwrap()).is_ok());
        for changed in [
            data.replace("\"driver\":\"mt76\"", "\"driver\":\"mt_wifi7\""),
            data.replace("\"channel\":\"development\"", "\"channel\":\"stable\""),
            data.replace("80000000", "0"),
            data.replace("aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "bad-hash"),
            data.replace("releases/download/", "releases/download/other/"),
        ] {
            assert!(validate_entry(&json::parse(&changed).unwrap()).is_err());
        }
    }
}

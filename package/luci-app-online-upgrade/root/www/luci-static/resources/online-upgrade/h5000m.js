/* SPDX-License-Identifier: GPL-2.0-or-later */
(function (root) {
	'use strict';
	var drivers = { mt76: '开源 mt76', mt_wifi7: '厂商 SDK mt_wifi7（闭源无线）' };
	var variants = { 'qmodem-next': 'QModem Next', qmodem: '经典 QModem', 'modem-pro': 'Modem Pro', mt5700: 'MT5700', mt5700m: 'MT5700M' };
	function canKeep(current, target) {
		return !!(current && target && current.driver === target.driver && current.variant === target.variant);
	}
	function matching(entries, driver, variant, channel) {
		return entries.filter(function (e) { return e.driver === driver && e.variant === variant && e.channel === channel; });
	}
	var api = { canKeep: canKeep, matching: matching };
	if (typeof module === 'object' && module.exports) module.exports = api;
	root.H5000MOTA = api;
	api.init = function (rpc, afterSelection) {
		var $ = function (id) { return document.getElementById(id); };
		var entries = [], policy = {}, pending = true, loading = true, saving = false;
		var fields = ['ota-driver', 'ota-variant', 'ota-channel', 'ota-version'];
		function selected() { return entries.find(function (e) { return e.id === $('ota-version').value; }); }
		function note(text) { $('ota-note').textContent = text; }
		function option(select, value, label) {
			var el = document.createElement('option'); el.value = value; el.textContent = label; select.appendChild(el);
		}
		function applied(entry) { return !!entry && policy.repo === entry.repo && policy.tag === entry.tag && policy.asset === entry.asset; }
		function preview() {
			var entry = selected(), eligible = canKeep(policy.current, entry);
			$('ota-keep').disabled = !eligible || saving;
			if (!eligible) $('ota-keep').checked = false;
			$('ota-apply').disabled = !entry || loading || saving;
			$('ota-keep-note').textContent = !policy.current
				? '当前固件缺少驱动与方案标识，本次必须清空配置。'
				: eligible ? '同驱动、同模组方案，可选择保留配置；默认清空。'
				: '跨驱动或跨模组方案：必须清空配置并恢复出厂设置。';
			$('ota-current').textContent = policy.current
				? '当前：' + drivers[policy.current.driver] + ' · ' + variants[policy.current.variant]
				: '当前：旧固件或身份未知';
			$('ota-detail').textContent = entry
				? entry.version + ' · ' + (entry.size / 1048576).toFixed(1) + ' MB' + (entry.kernel ? ' · 内核 ' + entry.kernel : '') + (entry.ota_client_commit ? '' : ' · 早期构建，未内置统一 OTA 客户端')
				: '此驱动、方案与发布通道暂时没有可用固件。';
			var link = $('ota-release');
			link.hidden = !entry; link.href = entry ? entry.release_url : '#';
			if (entry && pending) note('选择尚未应用，请点击“应用此版本并检查”后升级。');
			if (entry && !pending) note('已应用所选版本。升级前仍将重新校验机型和 SHA256。');
			if (!entry) note('可切换发布通道查看日常构建；稳定版由维护者验证后手动发布。');
			// 旧高级配置中的开关只显示后端已应用的结果；保留选择集中在此处。
			$('cfg-keep-config').value = policy.keep_config === true ? '1' : '0';
			$('cfg-keep-config').disabled = true;
		}
		function versions(preferred) {
			var list = matching(entries, $('ota-driver').value, $('ota-variant').value, $('ota-channel').value);
			var select = $('ota-version'); select.textContent = '';
			list.forEach(function (entry) { option(select, entry.id, entry.version + ' · ' + entry.published_at.replace('T', ' ').replace('Z', ' UTC')); });
			if (!list.length) option(select, '', '暂无版本');
			if (list.some(function (e) { return e.id === preferred; })) select.value = preferred;
			$('ota-keep').checked = false;
			pending = true; preview();
		}
		function load() {
			loading = true; $('ota-refresh').disabled = true; $('ota-apply').disabled = true;
			note('正在读取统一版本目录…');
			return Promise.all([rpc('h5000m_catalog'), rpc('h5000m_policy')]).then(function (results) {
				var catalog = results[0]; policy = results[1];
				if (!catalog || catalog.ok === false || !Array.isArray(catalog.entries)) throw new Error(catalog && catalog.error || '目录不可用');
				if (!policy || policy.ok !== true) throw new Error('无法读取当前固件身份');
				entries = catalog.entries;
				var saved = entries.find(applied);
				var first = saved || policy.current || { driver: 'mt76', variant: 'qmodem-next' };
				$('ota-driver').value = first.driver; $('ota-variant').value = first.variant;
				$('ota-channel').value = saved ? saved.channel : 'development';
				loading = false; versions(saved && saved.id);
				pending = !saved;
				$('ota-keep').checked = !!(saved && canKeep(policy.current, saved) && policy.keep_config);
				preview();
			}).catch(function (e) { pending = true; note('读取目录失败：' + e.message + '。请稍后刷新。'); })
			.finally(function () { loading = false; $('ota-refresh').disabled = false; });
		}
		api.assertReady = function () {
			if (loading || saving || pending || !applied(selected())) throw new Error('请先在 H5000M 目录中应用目标版本和保留配置选项');
		};
		Object.keys(drivers).forEach(function (key) { option($('ota-driver'), key, drivers[key]); });
		Object.keys(variants).forEach(function (key) { option($('ota-variant'), key, variants[key]); });
		fields.forEach(function (id) {
			$(id).addEventListener('change', function () {
				if (id !== 'ota-version') versions();
				else { pending = true; $('ota-keep').checked = false; preview(); }
			});
		});
		$('ota-keep').addEventListener('change', function () { pending = true; preview(); });
		$('ota-refresh').addEventListener('click', load);
		$('ota-apply').addEventListener('click', function () {
			var entry = selected(); if (!entry || saving) return;
			var keep = canKeep(policy.current, entry) && $('ota-keep').checked;
			saving = true;
			fields.forEach(function (id) { $(id).disabled = true; });
			$('ota-refresh').disabled = true; preview(); note('正在确认目标版本和配置策略…');
			rpc('h5000m_select', { id: entry.id, keep: keep }).then(function (result) {
				if (!result || result.ok !== true) throw new Error(result && result.error || '保存目标失败');
				policy = result; pending = false; saving = false;
				$('ota-keep').checked = policy.keep_config === true;
				return afterSelection();
			}).catch(function (e) { pending = true; note('应用失败：' + e.message); })
			.finally(function () {
				saving = false; fields.forEach(function (id) { $(id).disabled = false; });
				$('ota-refresh').disabled = false;
				if (!pending) preview(); else $('ota-apply').disabled = false;
			});
		});
		// 目标由目录管理；保留下载线路和性能调优设置。
		['cfg-url', 'btn-parse-url', 'btn-fetch-assets', 'cfg-asset', 'btn-apply-asset', 'cfg-repo', 'cfg-tag', 'cfg-pattern', 'cfg-repo-url', 'cfg-expected-sha256'].forEach(function (id) { $(id).disabled = true; });
		return load();
	};
})(typeof window === 'object' ? window : globalThis);

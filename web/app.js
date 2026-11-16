/* SPDX-License-Identifier: GPL-2.0-or-later */
(function () {
  'use strict';
  var entries = [], fields = ['driver', 'variant', 'channel'];
  function $(id) { return document.getElementById(id); }
  function append(parent, tag, text) { var e = document.createElement(tag); e.textContent = text; parent.appendChild(e); return e; }
  function render() {
    var list = entries.filter(function (e) { return fields.every(function (key) { return e[key] === $(key).value; }); });
    $('releases').textContent = '';
    $('status').textContent = list.length ? list.length + ' 个可用版本' : '此组合暂无版本。稳定版需要完成实机验证后由维护者发布。';
    list.forEach(function (e) {
      var card = document.createElement('article');
      append(card, 'h2', e.version);
      append(card, 'p', new Date(e.published_at).toLocaleString('zh-CN') + ' · ' + (e.size / 1048576).toFixed(1) + ' MB' + (e.kernel ? ' · 内核 ' + e.kernel : ''));
      if (e.fan) append(card, 'p', '风扇：' + e.fan);
      var url = 'https://github.com/' + e.repo + '/releases/download/' + e.tag + '/' + e.asset;
      if (e.url === url && /^Starktomy\/(OpenWRT-CI-H5000M|CloseWRT-CI-H5000M|H5000M-OTA)$/.test(e.repo)) {
        var download = append(card, 'a', '下载 sysupgrade 固件'); download.href = url; download.className = 'download';
        var notes = append(card, 'a', '发布说明'); notes.href = 'https://github.com/' + e.repo + '/releases/tag/' + e.tag;
      }
      append(card, 'code', 'SHA256  ' + e.sha256);
      $('releases').appendChild(card);
    });
  }
  fields.forEach(function (key) { $(key).addEventListener('change', render); });
  fetch('catalog.json', { cache: 'no-cache' }).then(function (r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
    .then(function (catalog) {
      if (catalog.schema_version !== 1 || catalog.device !== 'hiveton,h5000m' || !Array.isArray(catalog.entries)) throw new Error('目录格式错误');
      entries = catalog.entries; $('updated').textContent = '目录更新：' + new Date(catalog.generated_at).toLocaleString('zh-CN'); render();
    }).catch(function (e) { $('status').textContent = '目录暂时无法读取：' + e.message; });
})();

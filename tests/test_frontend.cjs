// SPDX-License-Identifier: GPL-2.0-or-later
const { test } = require('node:test');
const assert = require('node:assert/strict');
const ota = require('../package/luci-app-online-upgrade/root/www/luci-static/resources/online-upgrade/h5000m.js');
const drivers = ['mt76', 'mt_wifi7'];
const variants = ['qmodem-next', 'qmodem', 'modem-pro', 'mt5700', 'mt5700m'];
test('all 100 source/target combinations only preserve identical driver and profile', () => {
  for (const driver of drivers) for (const variant of variants) {
    for (const targetDriver of drivers) for (const targetVariant of variants) {
      const target = { driver: targetDriver, variant: targetVariant };
      assert.equal(ota.canKeep({ driver, variant }, target), driver === targetDriver && variant === targetVariant);
      assert.equal(ota.canKeep(null, target), false);
    }
  }
});
test('driver, profile and channel filters keep classic and Next releases separate', () => {
  const entries = drivers.flatMap(driver => variants.flatMap(variant => ['development', 'stable'].map(channel => ({ driver, variant, channel }))));
  assert.deepEqual(ota.matching(entries, 'mt_wifi7', 'qmodem', 'stable'), [{ driver: 'mt_wifi7', variant: 'qmodem', channel: 'stable' }]);
  assert.equal(ota.matching(entries, 'mt76', 'unknown', 'development').length, 0);
});

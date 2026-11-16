#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""在真实 Chrome 中加载完整 LuCI 页面，使用模拟 RPC 验证用户的配置策略。"""
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

base = Path(__file__).resolve().parents[1]
chrome = next((shutil.which(name) for name in ('google-chrome', 'chromium', 'chromium-browser') if shutil.which(name)), None)
if not chrome:
    raise SystemExit('Browser test requires Chrome / Chromium')
root = base / 'package/luci-app-online-upgrade/root'
template = (root / 'usr/share/ucode/luci/template/online-upgrade/main.ut').read_text()
template = re.sub(r'{%.*?%}', '', template, flags=re.S)
template = template.replace('{{ resource }}', (root / 'www/luci-static/resources').as_uri())
template = re.sub(r'{{.*?}}', '', template)
entries = []
for driver, repo, source in [('mt76', 'Starktomy/OpenWRT-CI-H5000M', 'immortalwrt-master'), ('mt_wifi7', 'Starktomy/CloseWRT-CI-H5000M', 'chasey-dev-25.12-dev-wifi7')]:
    for variant in ('qmodem-next', 'qmodem', 'modem-pro', 'mt5700', 'mt5700m'):
        tag = f'H5000M-{variant}-{source}-26.11.16-08.00.00'
        asset = f'H5000M-{variant}-20261116-sysupgrade.bin'
        entries.append(dict(id=f'development:{driver}:{variant}:{tag}', device='hiveton,h5000m', driver=driver, variant=variant, channel='development', version='26.11.16-08.00.00', tag=tag, repo=repo, asset=asset, size=80000000, published_at='2026-11-16T00:00:00Z', kernel='6.12.116', release_url=f'https://github.com/{repo}/releases/tag/{tag}'))
mock = r'''
<script>
window.testErrors=[];
window.addEventListener('error', e => testErrors.push(e.message));
window.addEventListener('unhandledrejection', e => testErrors.push(String(e.reason)));
const entries = ENTRIES;
let current = CURRENT;
let target = entries[0], keep = false;
window.calls=[];
function policy() { return {ok:true,current,repo:target.repo,tag:target.tag,asset:target.asset,can_keep:!!current&&current.driver===target.driver&&current.variant===target.variant,keep_config:keep}; }
window.fetch = async (url, opts) => {
  const body=JSON.parse(opts.body), method=body.params[2], args=body.params[3];
  calls.push({method,args});
  let result={ok:true};
  if(method==='h5000m_catalog') result={schema_version:1,device:'hiveton,h5000m',entries};
  if(method==='h5000m_policy') result=policy();
  if(method==='h5000m_select') {target=entries.find(e=>e.id===args.id); keep=policy().can_keep&&args.keep; result=policy();}
  if(method==='get_config') result={settings:{repo:target.repo,tag:target.tag,firmware_pattern:'^'+target.asset+'$',keep_config:keep?'1':'0'}};
  if(method==='get_sysinfo') result={model:'H5000M',id:'ImmortalWrt',release:'SNAPSHOT',arch:'aarch64_cortex-a53',target:'mediatek/filogic'};
  if(method==='get_status') result={stage:'idle'};
  if(method==='get_log') result={log:''};
  if(method==='list_backups') result={backups:[]};
  if(method==='list_tasks') result={ok:true,tasks:[]};
  if(method==='get_states') result={ok:false};
  return {status:200,json:async()=>({result:[0,result]})};
};
</script>
'''
checks = r'''
<script>
(async function () {
 const $=id=>document.getElementById(id);
 const assert=(v,msg)=>{if(!v)throw new Error(msg)};
 const tick=()=>new Promise(r=>setTimeout(r,30));
 async function wait(predicate) {for(let i=0;i<60;i++){if(predicate())return;await tick()}throw new Error('timeout: '+predicate)}
 function choose(id,value){$(id).value=value;$(id).dispatchEvent(new Event('change'));}
 async function apply(){ $('ota-apply').click(); await wait(()=>$('ota-note').textContent.includes('已应用')); }
 await wait(()=>$('ota-current').textContent.includes('当前：'));
 if(!current) {
   assert($('ota-keep').disabled&&!$('ota-keep').checked,'unknown identity must not keep');
   await apply();
   assert(calls.filter(c=>c.method==='h5000m_select').at(-1).args.keep===false,'unknown identity requested restore');
 } else {
   assert(!$('ota-keep').disabled&&!$('ota-keep').checked,'same profile must be opt-in');
   choose('ota-driver','mt_wifi7');
   assert($('ota-keep').disabled&&!$('ota-keep').checked,'cross driver allowed keep');
   let blocked=false;try{H5000MOTA.assertReady()}catch{blocked=true}assert(blocked,'unapplied target accepted');
   await apply();
   assert(calls.filter(c=>c.method==='h5000m_select').at(-1).args.keep===false,'cross driver restore sent');
   choose('ota-driver','mt76');
   assert(!$('ota-keep').disabled,'same profile keep unavailable');
   $('ota-keep').checked=true;$('ota-keep').dispatchEvent(new Event('change'));
   await apply();
   assert(calls.filter(c=>c.method==='h5000m_select').at(-1).args.keep===true,'explicit keep lost');
   choose('ota-variant','qmodem');
   assert($('ota-keep').disabled&&!$('ota-keep').checked,'Next/classic switch allowed keep');
   await apply();
   assert(calls.filter(c=>c.method==='h5000m_select').at(-1).args.keep===false,'cross profile restore sent');
   choose('ota-channel','stable');assert($('ota-apply').disabled,'empty stable channel flashable');
 }
 assert(testErrors.length===0,'page errors: '+testErrors.join('; '));
 document.body.setAttribute('data-test-result','passed');
})().catch(e=>{document.body.setAttribute('data-test-result','failed');document.body.appendChild(document.createTextNode('TEST FAILURE: '+e.stack));});
</script>
'''
with tempfile.TemporaryDirectory(prefix='h5000m-browser-') as directory:
    directory=Path(directory)
    for name, current in [('known',dict(driver='mt76',variant='qmodem-next')),('legacy',None)]:
        fixture = directory / f'{name}.html'
        fixture.write_text('<!doctype html><html><head><meta charset="utf-8">'+mock.replace('ENTRIES',json.dumps(entries)).replace('CURRENT',json.dumps(current))+'</head><body>'+template+checks+'</body></html>')
        result=subprocess.run([chrome,'--headless','--no-sandbox','--disable-dev-shm-usage','--disable-gpu','--allow-file-access-from-files',f'--user-data-dir={directory/name}','--virtual-time-budget=6000','--dump-dom',fixture.as_uri()],capture_output=True,text=True,timeout=45)
        if result.returncode or 'data-test-result="passed"' not in result.stdout:
            (directory/f'{name}-result.html').write_text(result.stdout)
            failure=re.search(r'TEST FAILURE:.*?(?=</body>)',result.stdout,re.S)
            raise SystemExit(f'{name}: browser policy failed\n'+(failure[0][:3000] if failure else result.stderr[-2000:]))
        print(f'{name}: full LuCI browser policy passed')

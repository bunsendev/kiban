import {el,field,button} from './api.js';
const adminToken=location.hash.slice(1);
history.replaceState(null,'',location.pathname);
const root=document.querySelector('#admin'),status=document.querySelector('#admin-status');
async function request(action,body){
 const response=await fetch('/api/operations/'+action,{method:body===undefined?'GET':'POST',headers:{'Content-Type':'application/json','X-Feedback-Admin':adminToken},body:body===undefined?undefined:JSON.stringify(body)});
 const v=await response.json();if(!response.ok)throw new Error(v.detail||'設定を確認してください');return v;
}
async function run(fn){try{await fn();}catch(e){status.textContent=e.message;}}
const messages={CONNECTED:'サーバーとの接続に成功しました。Field Pilotの接続準備は完了です。',AUTH:'認証失敗：Tokenを確認してください。',CLIENT_ID:'端末IDが登録・許可されていません。',KEY:'受信公開鍵を確認してください。',PRIVACY_POLICY:'送信ポリシーが拒否されました。サーバー管理者へ確認してください。',NETWORK:'通信できません。ネットワークを確認してください。',SERVER:'サーバーの応答・SHA・受付IDを確認できません。',SERVER_REJECTED:'サーバーが受付を拒否しました。'};
await run(async()=>{
 const v=await request('admin-config'),c=v.config;
 const quick=el('section','',root);
 el('h2','端末を選んで接続する',quick);
 el('p','IT担当者が端末設定ファイルを登録すると、端末IDの選択で送信先・認証・公開鍵をまとめて設定できます。現場担当者の入力は不要です。',quick);
 const picker=el('select','',el('label','このPCの端末ID',quick));
 const info=el('p','',quick);let presets=[];
 function refresh(items){presets=items;picker.replaceChildren();const empty=el('option','端末を選んでください',picker);empty.value='';for(const p of items){const opt=el('option',p.client_id,picker);opt.value=p.client_id;}info.textContent=items.length?'このPCに割り当てたIDを選んでください。':'端末設定ファイルを登録してください。';}
 picker.onchange=()=>{const p=presets.find(x=>x.client_id===picker.value);info.textContent=p?`送信先：${p.endpoint} / 鍵ID：${p.key_id} / SHA-256：${p.key_fingerprint}`:'';};
 const importFile=field(quick,'IT担当者：端末設定ファイルを登録','file',false);importFile.accept='.json';
 importFile.onchange=()=>run(async()=>{try{const f=importFile.files[0];if(!f)return;if(f.size>65536)throw new Error('設定ファイルは64KB以下です');let data;try{data=JSON.parse(await f.text());}catch{throw new Error('設定ファイルの形式を確認してください');}refresh(await request('profile-import',data));status.textContent='暗号化して登録しました。端末を選択してください。';}finally{importFile.value='';}});
 const agree=field(quick,'送信先・指紋を確認し、操作件数などの送信に同意する','checkbox',false);
 const change=field(quick,'受信鍵を変更する場合：切替を承認する','checkbox',false);
 const apply=button('この端末で接続する',()=>run(async()=>{if(!picker.value||!agree.checked)throw new Error('端末を選び、送信内容への同意を確認してください');apply.disabled=true;try{status.textContent='設定と接続テストを実行中…';const r=await request('profile-apply',{client_id:picker.value,consent:true,confirm_key_change:change.checked});status.textContent=messages[r.status]||'接続を確認できません。';}finally{apply.disabled=false;}}),quick);
 await request('device-profiles').then(refresh);
 const advanced=el('details','',root);el('summary','IT担当者：個別入力・変更（通常は不要）',advanced);
 const endpoint=field(advanced,'Feedback Endpoint');endpoint.value=c.endpoint;
 const device=field(advanced,'Device ID');device.value=c.client_id;
 const token=field(advanced,'Feedback Token（変更時のみ入力・再表示なし）','password',false);token.autocomplete='off';
 const keyId=field(advanced,'Receiver Key ID');keyId.value=c.key_id||'';
 const pem=el('textarea','',el('label','Receiver RSA Public Key',advanced));pem.rows=6;pem.value=c.public_key;
 const file=field(advanced,'公開鍵ファイルを選ぶ（公開鍵のみ）','file',false);file.accept='.pem,.pub,.txt';
 file.onchange=()=>run(async()=>{if(file.files[0]?.size>8192)throw new Error('公開鍵ファイルは8KB以下です');if(file.files[0])pem.value=await file.files[0].text();fingerprint='';fp.textContent='公開鍵を確認し直してください。';});
 let fingerprint='';const fp=el('p','公開鍵の指紋を確認してください。',advanced);
 pem.oninput=()=>{fingerprint='';fp.textContent='公開鍵を確認し直してください。';};
 button('公開鍵の指紋を確認',()=>run(async()=>{const v=await request('key-preview',{public_key:pem.value});fingerprint=v.key_fingerprint;fp.textContent='SHA-256: '+fingerprint;}),advanced);
 const rotate=field(advanced,'受信鍵を交換する場合：新Key ID・指紋を確認し切替を承認する','checkbox',false);
 const comments=field(advanced,'改善意見の自由記述も送信する（秘密情報を記入しない）','checkbox',false);comments.checked=c.include_comments;
 const consent=field(advanced,'送信先・内容を確認し、起動時・終業時・手動送信に同意する','checkbox',false);
 button('設定を保存',()=>run(async()=>{
  if(!fingerprint)throw new Error('公開鍵の指紋を確認してください。');
  try{await request('configure',{enabled:true,consent:consent.checked,endpoint:endpoint.value,client_id:device.value,token:token.value,key_id:keyId.value,key_fingerprint:fingerprint,public_key:pem.value,include_comments:comments.checked,confirm_key_change:rotate.checked});status.textContent='設定を保存しました。接続テストを実行してください。';}finally{token.value='';}
 }),advanced);
 button('Feedback Server 接続テスト',()=>run(async()=>{status.textContent='業務データを含まない接続テストを実行中…';const r=await request('connection-test',{});status.textContent=messages[r.status]||'接続を確認できません。設定を確認してください。';}),advanced);
 button('送信を停止',()=>run(async()=>{await request('configure',{enabled:false});status.textContent='送信を停止しました。業務データはこのPCに残ります。';}),advanced);
 el('p','RSA秘密鍵は入力・配置しないでください。更新署名用の公開鍵とも異なります。既存の未送信データは元の受信鍵情報を保持します。',advanced);
});

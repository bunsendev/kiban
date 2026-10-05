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
 const endpoint=field(root,'Feedback Endpoint');endpoint.value=c.endpoint;
 const device=field(root,'Device ID');device.value=c.client_id;
 const token=field(root,'Feedback Token（変更時のみ入力・再表示なし）','password',false);token.autocomplete='off';
 const keyId=field(root,'Receiver Key ID');keyId.value=c.key_id||'';
 const pem=el('textarea','',el('label','Receiver RSA Public Key',root));pem.rows=6;pem.value=c.public_key;
 const file=field(root,'公開鍵ファイルを選ぶ（公開鍵のみ）','file',false);file.accept='.pem,.pub,.txt';
 file.onchange=()=>run(async()=>{if(file.files[0]?.size>8192)throw new Error('公開鍵ファイルは8KB以下です');if(file.files[0])pem.value=await file.files[0].text();fingerprint='';fp.textContent='公開鍵を確認し直してください。';});
 let fingerprint='';const fp=el('p','公開鍵の指紋を確認してください。',root);
 pem.oninput=()=>{fingerprint='';fp.textContent='公開鍵を確認し直してください。';};
 button('公開鍵の指紋を確認',()=>run(async()=>{const v=await request('key-preview',{public_key:pem.value});fingerprint=v.key_fingerprint;fp.textContent='SHA-256: '+fingerprint;}),root);
 const rotate=field(root,'受信鍵を交換する場合：新Key ID・指紋を確認し切替を承認する','checkbox',false);
 const comments=field(root,'改善意見の自由記述も送信する（秘密情報を記入しない）','checkbox',false);comments.checked=c.include_comments;
 const consent=field(root,'送信先・内容を確認し、起動時・終業時・手動送信に同意する','checkbox',false);
 button('設定を保存',()=>run(async()=>{
  if(!fingerprint)throw new Error('公開鍵の指紋を確認してください。');
  try{await request('configure',{enabled:true,consent:consent.checked,endpoint:endpoint.value,client_id:device.value,token:token.value,key_id:keyId.value,key_fingerprint:fingerprint,public_key:pem.value,include_comments:comments.checked,confirm_key_change:rotate.checked});status.textContent='設定を保存しました。接続テストを実行してください。';}finally{token.value='';}
 }),root);
 button('Feedback Server 接続テスト',()=>run(async()=>{status.textContent='業務データを含まない接続テストを実行中…';const r=await request('connection-test',{});status.textContent=messages[r.status]||'接続を確認できません。設定を確認してください。';}),root);
 button('送信を停止',()=>run(async()=>{await request('configure',{enabled:false});status.textContent='送信を停止しました。業務データはこのPCに残ります。';}),root);
 el('p','RSA秘密鍵は入力・配置しないでください。更新署名用の公開鍵とも異なります。既存の未送信データは元の受信鍵情報を保持します。',root);
});

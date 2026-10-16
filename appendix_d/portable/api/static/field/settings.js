import {api,el,field,button,saveWithNotice} from './api.js';
import {operations} from './operations.js';
import {showVersion} from './version.js';
import {aiUsage} from './ai-usage.js';

export function settings(ctx,parent){
 showVersion(parent);
 const bar=el('nav','',parent);bar.setAttribute('aria-label','このPCの設定');bar.className='device-settings';
 const savedState=el('p','APIキーの保存状態を確認中…',parent);savedState.setAttribute('role','status');
 async function savedStatus(){
  try{const v=await api('/api/ai-credentials');savedState.textContent=v.available?'APIキー：保存済み・このユーザーで読込確認済み':v.saved?'APIキー：保存済みですが読込できません。AI・API設定から再設定してください。':'APIキー：未設定。PDF・画像のAI読み取りには設定が必要です。';document.dispatchEvent(new CustomEvent('portable-api-key-status',{detail:v}));return v;}
  catch{savedState.textContent='APIキーの保存状態を確認できません。画面を再読込してください。';throw new Error('保存状態を確認できません');}
 }
 savedStatus().catch(()=>{});
 const guide=el('a','操作マニュアル',bar);guide.href='/field/manual';guide.target='_blank';guide.rel='noopener';
 function open(title,render){
  const dialog=el('dialog','',parent);dialog.setAttribute('aria-label',title);
  dialog.style.maxWidth='min(760px, 92vw)';dialog.style.maxHeight='85vh';
  el('h2',title,dialog);
  button('閉じる',()=>dialog.close(),dialog,true);
  dialog.addEventListener('close',()=>dialog.remove(),{once:true});
  const body=el('div','',dialog);dialog.showModal();
  render(body).catch(()=>el('p','設定を読み込めませんでした。閉じてもう一度開いてください。',body));
 }
 button('AI・API設定',()=>open('AI・API設定',async body=>{
  el('p','手書き・写真・PDFの読み取りと、CSVの列対応の提案に共通で使います。送信用Tokenとは別です。',body);
  el('p','OpenAI APIの利用料金が発生します。原本の送信は、読み取り時に同意してから行います。',body);
  const state=el('p','確認中…',body);state.setAttribute('role','status');
  const key=field(body,'OpenAI APIキー','password',false);key.autocomplete='off';
  async function refresh(){const v=await savedStatus();state.textContent=v.available?'APIキーは保存済みです。このWindowsユーザーで次回も利用できます。':v.saved?'保存済みキーを利用できません。再設定してください。':'APIキーは未設定です。';}
  const save=button('このPCに保存・変更',async()=>{
   save.disabled=true;
   try{await saveWithNotice(async()=>{const result=await api('/api/ai-credentials',{api_key:key.value.trim()});if(!result.available)throw new Error('保存したキーを読み込めません。Windowsユーザーを確認してください。');key.value='';},'APIキーをこのPCに保存しました。読込も確認できました。\nAPIへの接続確認は、読み取り時に行います。');await refresh();}
   catch(e){state.textContent=e.message||'保存できませんでした。APIキーと端末の設定を確認してください。';}
   finally{save.disabled=false;}
  },body);
  button('保存状態を再確認',()=>refresh().catch(()=>{state.textContent='保存状態を確認できません。画面を再読込してください。';}),body,true);
  const confirmed=field(body,'保存したキーを削除する','checkbox',false);
  button('APIキーを削除',async()=>{
   if(!confirmed.checked){state.textContent='削除の確認にチェックしてください。';return;}
   try{await saveWithNotice(()=>api('/api/ai-credentials/delete',{confirm:true}),'保存したAPIキーを削除しました。');key.value='';confirmed.checked=false;await refresh();}
   catch{state.textContent='削除できませんでした。もう一度お試しください。';}
  },body,true);
  el('p','キーはこのPCのWindowsユーザー専用に暗号化保存され、再表示されません。保存は接続成功の確認ではありません。',body);
  await refresh();
  await aiUsage(body);
 }),bar);
 button('ログ提出・アップデート',()=>open('ログ提出・アップデート',async body=>{
  await operations(ctx,body);const details=body.querySelector('details');if(details)details.open=true;
 }),bar,true);
}

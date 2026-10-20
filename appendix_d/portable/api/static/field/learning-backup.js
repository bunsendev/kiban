const $=id=>document.getElementById(id);
let selected=null;
const statusNames={NOT_RESTORED:'復元はまだ実行していません',RESTORED:'復元が完了しました',FAILED:'復元できませんでした。元のデータを維持しています',INTERRUPTED_ROLLED_BACK:'中断を検知し、元のデータへ戻しました'};
async function api(path,options){const r=await fetch('/api/learning-backup/'+path,options);if(!r.ok){const v=await r.json();throw Error(v.detail||'処理できませんでした');}return r;}
function action(id,fn){$(id).onclick=async()=>{$(id).disabled=true;$('message').textContent='処理中です。お待ちください…';try{await fn();$('message').textContent='処理が完了しました';}catch(e){$('message').textContent=e.message;}finally{$(id).disabled=id==='restore'&&!selected;}};}
async function status(){const r=await(await api('status')).json();$('result').textContent=(statusNames[r.status]||r.status)+(r.pending?'\n復元予約済み：ランチャーを終了して再起動してください':'')+(r.previous_data?'\n復元前データの退避先：'+r.previous_data:'')+(r.error?'\n詳細：'+r.error:'')+'\n復旧用フォルダ：'+r.recovery_folder;}
action('backup',async()=>{const r=await api('create',{method:'POST'}),blob=await r.blob(),url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download='Bunsen-Learning-Backup-'+new Date().toISOString().slice(0,10)+'.zip';a.click();setTimeout(()=>URL.revokeObjectURL(url),60000);alert('バックアップZIPを作成しました。ダウンロード先を確認してください。');});
$('file').onchange=()=>{selected=null;$('restore').disabled=true;$('preview-result').textContent='';};
action('preview',async()=>{selected=null;$('restore').disabled=true;const f=$('file').files[0];if(!f)throw Error('バックアップZIPを選んでください');const r=await(await api('preview',{method:'POST',body:f})).json();selected=r;$('preview-result').textContent=`検証済み：${r.files}ファイル／${r.version||'旧形式・版不明'}／${r.created_at||'作成日時不明'}${r.legacy?'（CRC検査のみ。作成時ハッシュなし）':''}`;$('restore').disabled=false;});
action('restore',async()=>{if(!selected||!$('confirm').checked)throw Error('内容の検証と置換復元の確認が必要です');if(selected.legacy&&!$('legacy').checked)throw Error('旧形式の確認欄にチェックしてください');await api('restore',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id:selected.id,confirm:true,allow_legacy:$('legacy').checked})});alert('復元を予約しました。ランチャーを終了し、アプリを起動し直してください。');await status();});
action('cancel',async()=>{await api('cancel',{method:'POST'});alert('復元予約を取り消しました');await status();});
action('refresh',status);status().catch(e=>{$('message').textContent=e.message;});

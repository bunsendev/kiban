const dropFolder=document.getElementById('drop-folder-path');
const dropState=document.getElementById('drop-folder-state');
const dropRecent=document.getElementById('drop-folder-recent');
const dropScan=document.getElementById('drop-folder-scan');
let knownDropReceipts=null;

function renderDropFolder(value,notify=false){
  dropFolder.textContent=value.folder;
  dropState.textContent=value.pending.length
    ? `${value.pending.length}件をコピー完了まで待っています。`
    : '投入待ちです。ZIPを置くと自動で分析します。';
  dropRecent.replaceChildren();
  for(const item of value.recent.slice(0,5)){
    const li=document.createElement('li');li.textContent=`${item.filename}：${item.status==='PROCESSED'?'分析受付済み':'受付不可'}（${item.detail}）`;dropRecent.appendChild(li);
  }
  const current=new Set(value.recent.map(item=>item.receipt_id));
  if(notify&&knownDropReceipts){
    for(const item of value.recent){
      if(!knownDropReceipts.has(item.receipt_id)&&item.status==='PROCESSED'){
        document.dispatchEvent(new CustomEvent('portable-drop-ingested',{detail:{analysisId:item.analysis_id}}));break;
      }
    }
  }
  knownDropReceipts=current;
}

async function refreshDropFolder(notify=true){
  try{const response=await fetch('/api/drop-folder');const value=await response.json();if(!response.ok)throw new Error(value.detail||'投入フォルダを確認できません。');renderDropFolder(value,notify);}
  catch(error){dropState.textContent=error.message;dropState.className='error';}
}

dropScan.addEventListener('click',async()=>{
  dropScan.disabled=true;dropState.textContent='投入ファイルを確認中です。';
  try{const response=await fetch('/api/drop-folder/scan',{method:'POST'});const value=await response.json();if(!response.ok)throw new Error(value.detail||'投入ファイルを確認できません。');renderDropFolder(value,true);}
  catch(error){dropState.textContent=error.message;dropState.className='error';}finally{dropScan.disabled=false;}
});

refreshDropFolder(false);
setInterval(()=>refreshDropFolder(true),5000);

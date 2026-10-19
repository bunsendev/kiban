import { api, el, field, button, saveWithNotice } from './api.js';
import {exclusionsPanel} from './product-exclusions.js';
import {inventoryCheckPanel} from './document-inventory-checks.js';
import {cancelControl} from './document-cancel.js';
import { masterPanel } from './document-master.js';
import { reviewTable, serializeControls } from './document-review-table.js';
import {reviewPolicy,sourceComparison} from './document-review-policy.js';

export async function documents(ctx, parent) {
  const group=el('details','',parent);
  el('summary','手書き・写真・PDFから取り込む',group);
  el('p','PDF・PNG・JPEG（1ファイル10 MBまで）。読み取り後に原本を確認し、修正してから分析へ進めます。',group);
  const input=field(group,'原本を選ぶ（複数可・文書ZIP可）','file'); input.accept='.pdf,.png,.jpg,.jpeg,.zip';input.multiple=true;
  const master=await masterPanel(ctx,group);
  const fileChoice=el('select','',el('label','確認する原本（一覧の表示は1文書ずつ）',group));
  let pendingEdits=false,lastChoice='',bulkStopped=false,lastMaster=master.choice.value;
  master.choice.addEventListener('change',()=>ctx.run(async()=>{
    if(pendingEdits&&!window.confirm('未保存の編集を破棄してマスター版を切り替えますか？')){master.choice.value=lastMaster;return;}
    lastMaster=master.choice.value;await refresh();
  }));
  const list=el('div','',group);
  list.addEventListener('input',()=>{pendingEdits=true;});
  fileChoice.onchange=()=>ctx.run(async()=>{
    if(pendingEdits&&!window.confirm('未保存の編集を破棄して原本を切り替えますか？')){fileChoice.value=lastChoice;return;}
    await refresh();
  });
  const notice=el('p','',group);notice.setAttribute('role','status');
  function showKeyStatus(v){notice.textContent=v.available?'APIキーは保存済み・読込確認済みです。原本を登録し、送信同意後に読み取れます。':'APIキーが未設定、または読込できません。画面上部のAI・API設定で保存してください。';}
  async function keyStatus(){const v=await api('/api/ai-credentials');showKeyStatus(v);return v;}
  const updateKeyStatus=e=>{if(group.isConnected)showKeyStatus(e.detail);else document.removeEventListener('portable-api-key-status',updateKeyStatus);};
  document.addEventListener('portable-api-key-status',updateKeyStatus);
  await keyStatus();
  button('原本を登録する',()=>ctx.run(async()=>{
    if(!input.files.length) throw new Error('原本を選択してください');
    let count=0;const failures=[];
    for(const f of input.files){try{
      const zipped=f.name.toLowerCase().endsWith('.zip');if(f.size>(zipped?100:10)*1024*1024)throw new Error('容量制限を超えています');
      const r=await fetch(zipped?'/api/documents/batch':'/api/documents/upload',{method:'POST',headers:{'X-File-Name':encodeURIComponent(f.name)},body:f});
      const v=await r.json();if(!r.ok)throw new Error(v.detail||'登録できませんでした');
      count+=zipped?v.accepted.length:1;if(zipped)for(const e of v.errors)failures.push(`${e.file}：${e.reason}`);
    }catch(e){failures.push(`${f.name}：${e.message}`);}}
    input.value='';await refresh();ctx.message(`登録 ${count}件。${failures.join('／')}`);
  }),group);
  button('未読取の印刷PDFを一括読取（API不要）',()=>ctx.run(async()=>{
    let count=0;const failures=[];bulkStopped=false;
    for(const doc of await api('/api/documents')){if(bulkStopped)break;if(doc.mime!=='application/pdf'||doc.extraction||doc.approval||doc.cancelled)continue;
      ctx.message(`${doc.name} を読取中／完了 ${count}件。中止しても成功分は残ります。`);
      try{await api(`/api/documents/${doc.id}/local`,{});count++;}catch(e){failures.push(`${doc.name}：${e.message}`);}}
    await refresh();ctx.message(`${bulkStopped?'一括読取を中止しました。':''}読取 ${count}件。承認は未実施です。${failures.join('／')}`);
  }),group,true);
  button('一括読取を中止（成功分は保持）',()=>{bulkStopped=true;},group,true);
  button('確認済み文書をまとめて分析へ渡す',()=>ctx.run(async()=>{
    let count=0;const failures=[];
    for(const doc of await api('/api/documents')){if(!doc.approval||doc.approval.dispatched||doc.superseded_by||doc.cancelled)continue;
      try{await api(`/api/documents/${doc.id}/dispatch`,{});count++;}catch(e){failures.push(`${doc.name}：${e.message}`);}}
    await refresh();ctx.message(`受渡し ${count}件。${failures.join('／')}投入フォルダの確認で履歴をまとめて分析します。`);
  }),group,true);
  button('投入フォルダの画像・PDFを確認',()=>ctx.run(async()=>{
    const v=await api('/api/documents/folder',{}); await refresh();
    ctx.message(`${v.count}ファイルを確認しました。未表示のファイルは形式・10 MB制限をご確認ください。`);
  }),group,true);
  async function refresh(){
    list.replaceChildren();
    const all=await api('/api/documents'),selected=fileChoice.value;
    fileChoice.replaceChildren();for(const doc of all){const o=el('option',`${doc.name} ／ ${doc.approval?'確認済み':doc.cancelled?'取りやめ済み':doc.extraction?'確認待ち':'未読取'}`,fileChoice);o.value=doc.id;}
    fileChoice.value=all.some(d=>d.id===selected)?selected:all.find(d=>!d.approval&&!d.cancelled)?.id||all[0]?.id||'';
    lastChoice=fileChoice.value;pendingEdits=false;
    for(const doc of all){
      if(doc.id!==fileChoice.value)continue;
      const box=el('details','',list); el('summary',`${doc.name} ／ ${doc.approval?'確認済み':doc.cancelled?'取りやめ済み':doc.extraction?'確認待ち':'未読取'}`,box);
      let stopped=!!doc.cancelled;
      if(!doc.approval){
        if(doc.cancelled){
          el('p','取りやめ済みです。原本・保存済みの読取結果は残っています。',box);
          button('このファイルの確認を再開',()=>ctx.run(async()=>{await api(`/api/documents/${doc.id}/resume`,{});await refresh();}),box,true);
        }else cancelControl(ctx,box,doc.id,value=>{stopped=value;},refresh);
      }
      const link=el('a','原本を別タブで開く',box); link.href=`/api/documents/${doc.id}/original`;link.target='_blank';link.rel='noopener';
      if(doc.mime.startsWith('image/')){const img=el('img','',box);img.src=link.href;img.alt='確認用の原本';img.style.maxWidth='100%';img.loading='lazy';}
      if(doc.cancelled)continue;
      if(doc.correction_of)el('p','訂正版です。除外チェックを外して再対象化できます。元入力が受渡し済みの場合は二重計上防止のためIT担当者による差替えが必要です。',box);
      let zeroCurrent;
      if(!doc.approval && doc.mime==='application/pdf'){
        zeroCurrent=field(box,'この帳票の「現在」欄は空欄＝0、両欄空欄の明細は取込対象外にする（当出・他の帳票には適用しない）','checkbox',false);
        zeroCurrent.checked=doc.extraction?.blank_current_policy==='CURRENT_BLANK_ZERO_EXCLUDE_EMPTY';
        button(doc.extraction?'印刷在庫表の列を取り直す（API不要）':'印刷在庫表を読み取る（API不要）',()=>ctx.run(async()=>{await api(`/api/documents/${doc.id}/local`,{retry:!!doc.extraction,blank_current_zero:zeroCurrent.checked});if(!stopped)await refresh();}),box);
      }
      if(!doc.approval){
        el('p',`原本は${doc.page_count||1}ページ。ページごとに読み取り・保存します。失敗時も成功したページは残ります。OpenAIに原本と補助テキストを送信し、API料金が発生します。`,box);
        if(!doc.extraction)box.open=true;
        const consent=field(box,'この原本全体のOpenAIへの送信に同意する','checkbox',false);
        const split=field(box,'手書きの左右2表を拡大して読む（全体・左・右の3画像を送信。入力量・料金が増える場合があります）','checkbox',false);
        split.checked=doc.extraction?.page_reviews?.some(v=>v.layout==='two_tables')||doc.extraction?.layout==='two_tables';
        const page=field(box,'読み取るページ番号','number',false);page.min=1;page.max=doc.page_count||1;page.value=1;
        const status=el('p',doc.extraction?.pages_read?`読取済みページ：${doc.extraction.pages_read.join('、')}`:'',box);
        async function readPages(retry,all){
          if(!consent.checked)throw new Error('送信への同意を確認してください');
          if(!(await keyStatus()).available)throw new Error('APIキーを利用できません。画面上部のAI・API設定で保存してください。');
          read.disabled=true;again.disabled=true;bulk.disabled=true;
          try{
            const pages=all?Array.from({length:doc.page_count||1},(_,i)=>i+1):[Number(page.value)];
            for(const p of pages){if(stopped)break;status.textContent=`${p} / ${doc.page_count||1}ページを読み取り中です。1ページ最大90秒ほどお待ちください。`;
              await api(`/api/documents/${doc.id}/extract`,{consent:true,page:p,retry,layout:split.checked?'two_tables':'whole',master_version:master.choice.value||''});}
            if(!stopped)await refresh();
          }catch(e){if(stopped)return;status.textContent=e.message;throw e;}
          finally{read.disabled=false;again.disabled=false;bulk.disabled=false;}
        }
        const read=button('AIで読み取る',()=>ctx.run(()=>readPages(false,false)),box);
        const bulk=button('未読取ページを続けて読み取る',()=>ctx.run(()=>readPages(false,true)),box,true);
        const again=button('指定ページを再読取する（追加料金）',()=>ctx.run(()=>readPages(true,false)),box,true);
        if(doc.extraction)button('読取履歴を確認',()=>ctx.run(async()=>{
          const history=await api(`/api/documents/${doc.id}/history`);
          status.textContent=history.map(v=>`${v.at} ／ ${v.status==='failed'?'失敗（以前の結果を保持）':v.status==='cancelled'?'取りやめ':v.status==='resumed'?'再開':`${v.rows.length}行を保存`}`).join('\n');
        }),box,true);
      }
      if(!doc.extraction)continue;
      const diagnostics=el('details','',box);el('summary','読取点検の詳細（収支・原本項目・同条件明細）',diagnostics);
      inventoryCheckPanel(diagnostics,doc.extraction);
      for(const review of doc.extraction.page_reviews||[doc.extraction]){
        if(review.layout==='two_tables')el('p',`${review.page||''}ページ：左右拡大読取 ／ ${review.model||'モデル未確認'}`,box);
        for(const warning of review.quality_warnings||[])el('p','読取確認：'+warning,box);
      }
      if(!doc.extraction.complete)el('p','全明細を読み取れていません。読めた行を修正・確認して採用できます。未読取部分は理由を残して保留し、原本全体の確認完了とは扱いません。',box);
      if(doc.approval){
        if(doc.superseded_by)el('p','訂正版を作成済みです。「訂正」の付いたファイルを開いてください。元の履歴は保持します。',box);
        else {
          const correctionActor=field(box,'訂正の確認者'),correctionReason=field(box,'訂正理由（例：除外商品を対象へ戻す）');
          button('履歴を残して訂正する',()=>ctx.run(async()=>{await api(`/api/documents/${doc.id}/correction`,{actor:correctionActor.value,reason:correctionReason.value});await refresh();}),box,true);
        }
        el('p',`確認者：${doc.approval.actor} ／ ${doc.approval.at}。原本・AI抽出・修正内容を保存済みです。`,box);
        if(!doc.approval.dispatched) button('確認済みデータを分析へ渡す',()=>ctx.run(async()=>{await api(`/api/documents/${doc.id}/dispatch`,{});await refresh();}),box);
        else el('p','分析へ受け渡し済み。「投入フォルダから読み込む」で受付結果を開いてください。JAN・単位・履歴不足などは既存の確認画面で続けて確認します。',box);
        continue;
      }
      el('p','帳票の読み方・例外・保留と採用範囲を確認します。通常行は機械点検の通過であり、読取精度の保証ではありません。ボール＝ケース、バラ＝商品1個。入数の推測・数量の自動補完はしません。',box);
      box.open=true;
      const plan=await api(`/api/documents/${doc.id}/review/plan`,{master_version:master.choice.value||''});
      const summary=el('section','',box);summary.className='document-review';
      el('h3','読取・確認サマリー',summary);
      el('p',`読取商品 ${new Set(plan.rows.map(r=>r.jan).filter(Boolean)).size} JAN ／ ${plan.rows.length}明細`,summary);
      el('p',`機械点検通過 ${plan.counts.READY||0}行 ／ 例外確認 ${plan.counts.REVIEW||0}行 ／ 処理保留 ${plan.counts.HOLD||0}行 ／ 除外予定 ${plan.counts.EXCLUDED||0}行`,summary).setAttribute('role','status');
      el('p',plan.notice,summary);
      if(!plan.counts.REVIEW&&!plan.counts.HOLD)el('p','例外・保留は0件です。帳票・原本日付・適用ルールと採用範囲を確認し、文書承認へ進めます。自動承認はしていません。',summary);
      for(const [cause,count] of Object.entries(plan.causes))el('p',`${cause}：${count}行`,summary);
      const policyHost=el('details','',box);el('summary','単位ルールを確認・保存する',policyHost);
      policyHost.className='document-review';policyHost.open=plan.native&&!Object.keys(plan.applied_rules).length;
      const comparison=sourceComparison(box,doc);
      const table=reviewTable(ctx,box,plan.rows,master,{...plan,onSource:comparison});
      const {edits,update}=table;
      await reviewPolicy(ctx,policyHost,doc,table,plan,master,refresh);
      button('一覧の商品候補をまとめて補完（API送信なし）',()=>ctx.run(async()=>{
        if(!master.choice.value)throw new Error('照合に使うJANマスター版を選んでください');
        const result=await api('/api/document-master/suggest-rows',{version:master.choice.value,rows:edits.map(serializeControls)});
        for(let i=0;i<edits.length;i++)for(const key of ['jan','product_code','master_version','master_cell','note','source_jan'])if(edits[i][key]&&result.rows[i][key]!==undefined)edits[i][key].value=result.rows[i][key];
        pendingEdits=true;update();ctx.message('一意に照合できる商品候補を入力しました。数量・日付は変更していません。原本確認後に保存してください。');
      }),box,true);
      const partial=field(box,'未読取部分を保留し、確認できた明細だけ採用する','checkbox',false);
      const partialReason=field(box,'未読取部分の扱い・採用範囲の理由','text',false);
      for(const n of [partial,partialReason]){n.parentElement.style.display='block';n.parentElement.style.marginBottom='12px';}
      const actor=field(box,'原本の確認者');
      if(doc.draft){actor.value=doc.draft.actor;el('p','途中保存した内容を復元しました。正式採用はまだ行っていません。',box);}
      button('途中保存する（未完成でも保存可）',()=>ctx.run(async()=>{await saveWithNotice(()=>api(`/api/documents/${doc.id}/draft`,{rows:edits.map(serializeControls),actor:actor.value,revision:doc.extraction.revision}),'途中保存しました。後から再開できます。');}),box,true);
      const confirm=field(box,'原本の帳票・例外・保留・適用ルールと、単位・換算・採用範囲を確認した','checkbox',false);
      for(const n of [actor,confirm]){n.parentElement.style.display='block';n.parentElement.style.marginBottom='12px';}
      button('修正内容を確認して保存',()=>ctx.run(async()=>{
        const rows=edits.map(serializeControls);
        await saveWithNotice(()=>api(`/api/documents/${doc.id}/approve`,{actor:actor.value,confirmed:confirm.checked,rows,revision:doc.extraction.revision,partial_confirmed:partial.checked,partial_reason:partialReason.value,review_guard:true,master_version:master.choice.value||''}),partial.checked?'確認した範囲を保存しました。未読取部分は保留のままです。':'原本の確認内容と修正を保存しました。分析へ渡す操作に進めます。');await refresh();
      }),box);
    }
  }
  await exclusionsPanel(ctx,group,refresh,master);
  await refresh();
}

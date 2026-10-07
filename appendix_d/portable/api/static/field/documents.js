import { api, el, field, button, saveWithNotice } from './api.js';
import { masterPanel, masterChoice } from './document-master.js';

const labels = {page:'原本ページ番号',note:'確認メモ',kind:'データの種類',jan:'JAN',product_code:'商品コード',
  product_name:'商品名',date:'出荷日',expiry:'賞味期限',quantity:'原本の数量',unit:'原本の単位',
  location:'倉庫',snapshot:'在庫基準日',case_factor:'1単位あたりの箱数（単独数量の場合）',
  case_quantity:'現在ケース数（併記の場合）',loose_quantity:'現在バラ数（空欄は未確認）',units_per_case:'1箱あたりのバラ数（換算を確認）'};

export async function documents(ctx, parent) {
  const group=el('details','',parent);
  el('summary','手書き・写真・PDFから取り込む',group);
  el('p','PDF・PNG・JPEG（1ファイル10 MBまで）。読み取り後に原本を確認し、修正してから分析へ進めます。',group);
  const input=field(group,'原本を選ぶ','file'); input.accept='.pdf,.png,.jpg,.jpeg';
  const master=await masterPanel(ctx,group);
  const list=el('div','',group);
  const notice=el('p','',group);notice.setAttribute('role','status');
  function showKeyStatus(v){notice.textContent=v.available?'APIキーは保存済み・読込確認済みです。原本を登録し、送信同意後に読み取れます。':'APIキーが未設定、または読込できません。画面上部のAI・API設定で保存してください。';}
  async function keyStatus(){const v=await api('/api/ai-credentials');showKeyStatus(v);return v;}
  const updateKeyStatus=e=>{if(group.isConnected)showKeyStatus(e.detail);else document.removeEventListener('portable-api-key-status',updateKeyStatus);};
  document.addEventListener('portable-api-key-status',updateKeyStatus);
  await keyStatus();
  button('原本を登録する',()=>ctx.run(async()=>{
    const f=input.files[0]; if(!f) throw new Error('原本を選択してください');
    if(f.size>10*1024*1024) throw new Error('10 MB以内で選択してください');
    const r=await fetch('/api/documents/upload',{method:'POST',headers:{'X-File-Name':encodeURIComponent(f.name)},body:f});
    const v=await r.json(); if(!r.ok) throw new Error(v.detail||'登録できませんでした');
    input.value=''; await refresh();
  }),group);
  button('投入フォルダの画像・PDFを確認',()=>ctx.run(async()=>{
    const v=await api('/api/documents/folder',{}); await refresh();
    ctx.message(`${v.count}ファイルを確認しました。未表示のファイルは形式・10 MB制限をご確認ください。`);
  }),group,true);
  async function refresh(){
    list.replaceChildren();
    for(const doc of await api('/api/documents')){
      const box=el('details','',list); el('summary',`${doc.name} ／ ${doc.approval?'確認済み':doc.extraction?'確認待ち':'未読取'}`,box);
      const link=el('a','原本を別タブで開く',box); link.href=`/api/documents/${doc.id}/original`;link.target='_blank';link.rel='noopener';
      if(doc.mime.startsWith('image/')){const img=el('img','',box);img.src=link.href;img.alt='確認用の原本';img.style.maxWidth='100%';img.loading='lazy';}
      if(!doc.extraction && doc.mime==='application/pdf')button('印刷在庫表を読み取る（API不要）',()=>ctx.run(async()=>{await api(`/api/documents/${doc.id}/local`,{});await refresh();}),box);
      if(!doc.approval){
        el('p',`原本は${doc.page_count||1}ページ。ページごとに読み取り・保存します。失敗時も成功したページは残ります。OpenAIに原本と補助テキストを送信し、API料金が発生します。`,box);
        if(!doc.extraction)box.open=true;
        const consent=field(box,'この原本全体のOpenAIへの送信に同意する','checkbox',false);
        const page=field(box,'読み取るページ番号','number',false);page.min=1;page.max=doc.page_count||1;page.value=1;
        const status=el('p',doc.extraction?.pages_read?`読取済みページ：${doc.extraction.pages_read.join('、')}`:'',box);
        async function readPages(retry,all){
          if(!consent.checked)throw new Error('送信への同意を確認してください');
          if(!(await keyStatus()).available)throw new Error('APIキーを利用できません。画面上部のAI・API設定で保存してください。');
          read.disabled=true;again.disabled=true;bulk.disabled=true;
          try{
            const pages=all?Array.from({length:doc.page_count||1},(_,i)=>i+1):[Number(page.value)];
            for(const p of pages){status.textContent=`${p} / ${doc.page_count||1}ページを読み取り中です。1ページ最大90秒ほどお待ちください。`;
              await api(`/api/documents/${doc.id}/extract`,{consent:true,page:p,retry});}
            await refresh();
          }catch(e){status.textContent=e.message;if(all)await refresh();throw e;}
          finally{read.disabled=false;again.disabled=false;bulk.disabled=false;}
        }
        const read=button('AIで読み取る',()=>ctx.run(()=>readPages(false,false)),box);
        const bulk=button('未読取ページを続けて読み取る',()=>ctx.run(()=>readPages(false,true)),box,true);
        const again=button('指定ページを再読取する（追加料金）',()=>ctx.run(()=>readPages(true,false)),box,true);
        if(doc.extraction)button('読取履歴を確認',()=>ctx.run(async()=>{
          const history=await api(`/api/documents/${doc.id}/history`);
          status.textContent=history.map(v=>`${v.at} ／ ${v.status==='failed'?'失敗（以前の結果を保持）':`${v.rows.length}行を保存`}`).join('\n');
        }),box,true);
      }
      if(!doc.extraction)continue;
      if(!doc.extraction.complete)el('p','全明細を読み取れていません。読めた行を修正・確認して採用できます。未読取部分は理由を残して保留し、原本全体の確認完了とは扱いません。',box);
      if(doc.approval){
        el('p',`確認者：${doc.approval.actor} ／ ${doc.approval.at}。原本・AI抽出・修正内容を保存済みです。`,box);
        if(!doc.approval.dispatched) button('確認済みデータを分析へ渡す',()=>ctx.run(async()=>{await api(`/api/documents/${doc.id}/dispatch`,{});await refresh();}),box);
        else el('p','分析へ受け渡し済み。「投入フォルダから読み込む」で受付結果を開いてください。JAN・単位・履歴不足などは既存の確認画面で続けて確認します。',box);
        continue;
      }
      el('p','全行を原本と照合してください。不明な行は理由を付けて除外できます。箱なら換算1、くくり・パレットは1単位あたりの箱数を入力してください。勝手な換算はしません。',box);
      const edits=[];const rowsParent=el('div','',box);
      function addRow(row,i){
        const section=el('details','',rowsParent);el('summary',`${i+1}行目：${row.product_name||row.jan||'商品不明'} ／ 原本${row.page||'?'}ページ`,section);
        el('p',`読み取り時の注意：${row.note||'記載なし（原本確認は必要）'}`,section);
        const controls={};
        for(const [k,label] of Object.entries(labels)){
          let n;
          if(k==='kind'){
            n=el('select','',el('label',label,section));
            for(const [v,t] of [['unknown','選択してください'],['shipment','出荷実績'],['inventory','倉庫在庫']]){const o=el('option',t,n);o.value=v;}
          }else n=field(section,label,['date','expiry','snapshot'].includes(k)?'date':'text',false);
          n.value=row[k]||'';controls[k]=n;
        }
        controls.component_confirmed=field(section,'ケース・バラの列の意味と空欄を確認した（空欄は必要なら明示的に0を入力）','checkbox',false);
        masterChoice(ctx,section,controls,master);
        controls.exclude=field(section,'この行を除外する','checkbox',false);
        controls.reason=field(section,'除外理由','text',false);edits.push(controls);
      }
      doc.extraction.rows.forEach(addRow);
      button('原本から明細を追加する',()=>addRow({},edits.length),box,true);
      const partial=field(box,'未読取部分を保留し、確認できた明細だけ採用する','checkbox',false);
      const partialReason=field(box,'未読取部分の扱い・採用範囲の理由','text',false);
      const actor=field(box,'原本の確認者');
      const confirm=field(box,'すべての行を原本と照合し、単位・換算・除外を確認した','checkbox',false);
      button('修正内容を確認して保存',()=>ctx.run(async()=>{
        const rows=edits.map(cs=>Object.fromEntries(Object.entries(cs).map(([k,n])=>[k,['exclude','component_confirmed'].includes(k)?n.checked:n.value])));
        await saveWithNotice(()=>api(`/api/documents/${doc.id}/approve`,{actor:actor.value,confirmed:confirm.checked,rows,revision:doc.extraction.revision,partial_confirmed:partial.checked,partial_reason:partialReason.value}),partial.checked?'確認した範囲を保存しました。未読取部分は保留のままです。':'原本の確認内容と修正を保存しました。分析へ渡す操作に進めます。');await refresh();
      }),box);
    }
  }
  await refresh();
}

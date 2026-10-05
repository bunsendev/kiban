import { api, el, field, button } from './api.js';

const labels = {kind:'データの種類',jan:'JAN',product_code:'商品コード',
  product_name:'商品名',date:'出荷日',expiry:'賞味期限',quantity:'原本の数量',unit:'原本の単位',
  location:'倉庫',snapshot:'在庫基準日',case_factor:'1単位あたりの箱数'};

export async function documents(ctx, parent) {
  const group=el('details','',parent);
  el('summary','手書き・写真・PDFから取り込む',group);
  el('p','PDF・PNG・JPEG（1ファイル10 MBまで）。読み取り後に原本を確認し、修正してから分析へ進めます。',group);
  const input=field(group,'原本を選ぶ','file'); input.accept='.pdf,.png,.jpg,.jpeg';
  const list=el('div','',group);
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
      if(!doc.extraction){
        el('p','この原本全体（手書き・明細・数量を含む）をOpenAIへ送信します。API料金が発生します。保存済みAPIキーを使用します。',box);
        const consent=field(box,'この原本全体のOpenAIへの送信に同意する','checkbox',false);
        const status=el('p','',box);
        const read=button('AIで読み取る',()=>ctx.run(async()=>{
          if(!consent.checked) throw new Error('送信への同意を確認してください');
          read.disabled=true;status.textContent='読み取り中です。最大90秒ほどお待ちください。';
          try{await api(`/api/documents/${doc.id}/extract`,{consent:true});await refresh();}
          finally{read.disabled=false;status.textContent='';}
        }),box);continue;
      }
      if(!doc.extraction.complete){el('p','全明細を読み取れていません。原本を分割するか鮮明に撮影して再投入してください。自動取込はしません。',box);continue;}
      if(doc.approval){
        el('p',`確認者：${doc.approval.actor} ／ ${doc.approval.at}。原本・AI抽出・修正内容を保存済みです。`,box);
        if(!doc.approval.dispatched) button('確認済みデータを分析へ渡す',()=>ctx.run(async()=>{await api(`/api/documents/${doc.id}/dispatch`,{});await refresh();}),box);
        else el('p','分析へ受け渡し済み。「投入フォルダから読み込む」で受付結果を開いてください。JAN・単位・履歴不足などは既存の確認画面で続けて確認します。',box);
        continue;
      }
      el('p','全行を原本と照合してください。不明な行は理由を付けて除外できます。箱なら換算1、くくり・パレットは1単位あたりの箱数を入力してください。勝手な換算はしません。',box);
      const edits=[];
      doc.extraction.rows.forEach((row,i)=>{
        const section=el('details','',box);el('summary',`${i+1}行目：${row.product_name||row.jan||'商品不明'} ／ 原本${row.page||'?'}ページ`,section);
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
        controls.exclude=field(section,'この行を除外する','checkbox',false);
        controls.reason=field(section,'除外理由','text',false);edits.push(controls);
      });
      const actor=field(box,'原本の確認者');
      const confirm=field(box,'すべての行を原本と照合し、単位・換算・除外を確認した','checkbox',false);
      button('修正内容を確認して保存',()=>ctx.run(async()=>{
        const rows=edits.map(cs=>Object.fromEntries(Object.entries(cs).map(([k,n])=>[k,k==='exclude'?n.checked:n.value])));
        await api(`/api/documents/${doc.id}/approve`,{actor:actor.value,confirmed:confirm.checked,rows});await refresh();
      }),box);
    }
  }
  await refresh();
}

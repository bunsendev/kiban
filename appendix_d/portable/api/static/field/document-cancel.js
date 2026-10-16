import {api,el,button} from './api.js';

export function cancelControl(ctx,parent,identifier,setStopped,refresh){
 const panel=el('div','',parent);panel.hidden=true;
 el('p','取りやめますか？原本と保存済み結果は残ります。送信済みのAPI処理・料金は取り消せません。',panel);
 const stop=button('取りやめる',()=>ctx.run(async()=>{
  stop.disabled=true;setStopped(true);
  try{
   await api(`/api/documents/${identifier}/cancel`,{});
   await refresh();ctx.message('取りやめました。保存済みの原本・結果は残っています。');
  }catch(e){setStopped(false);throw e;}
  finally{stop.disabled=false;}
 }),panel);
 button('戻る',()=>{panel.hidden=true;},panel,true);
 button('このファイルの読み取り・確認を取りやめる',()=>{panel.hidden=false;},parent,true);
 return panel;
}

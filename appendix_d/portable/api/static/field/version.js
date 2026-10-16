import {api,el} from './api.js';

// Read the running application, never infer its version from the folder name.
export async function showVersion(parent){
 const info=el('p','インストール済みバージョン：確認中…',parent);
 info.setAttribute('role','status');
 try{
  const value=await api('/ready');
  if(typeof value.version!=='string'||!value.version.trim())throw new Error('version');
  info.textContent=`インストール済みバージョン：${value.version}`;
 }catch{
  info.textContent='インストール済みバージョンを確認できません。画面を再読込してください。';
 }
}

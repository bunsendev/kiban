import {settings} from './settings.js';

const parent=document.getElementById('device-settings');
const error=document.getElementById('settings-error');
if(parent){
 const ctx={async run(action){
  error.textContent='';
  try{await action();}
  catch{error.textContent='操作を完了できませんでした。接続・設定を確認して、もう一度お試しください。';}
 }};
 settings(ctx,parent);
}

import {settings} from './settings.js';
import {documents} from './documents.js';

const parent=document.getElementById('device-settings');
const error=document.getElementById('settings-error');
const documentStatus=document.getElementById('document-error');
function message(text,failed=false){
 const target=documentStatus||error;
 target.textContent=text;target.className=failed?'error':'';
}
const ctx={message,async run(action){
 message('');
 try{await action();}
 catch(e){message(e.message||'操作を完了できませんでした。もう一度お試しください。',true);}
}};
if(parent)settings(ctx,parent);
const intake=document.getElementById('document-intake');
if(intake)ctx.run(async()=>{
 await documents(ctx,intake);
 const panel=intake.querySelector('details');if(panel)panel.open=true;
});

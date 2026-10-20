import { api, el, field, button, displayTime } from './api.js';

const updateLabels={NOT_CHECKED:'未確認',UNCONFIGURED:'公開鍵の設定が必要です',NO_RELEASE:'配布可能なPortable更新はまだありません',CURRENT:'最新版です',AVAILABLE:'更新があります',CHECK_FAILED:'更新を確認できません。現在の版はそのまま使えます',STAGED:'検証済み・再起動待ち',UPDATED:'更新が完了しました',ROLLED_BACK:'更新に失敗したため元の版へ戻しました',APPLY_FAILED:'更新できませんでした。元の版を維持しています',RESTART_REQUESTED:'バックアップ・更新・再起動を準備しています'};

export async function operations(ctx,parent){
  const box=el('details','',parent);el('summary','ログ提出・アップデート・バックアップ',box);
  const info=el('div','',box);
  const backup=el('a','学習データのバックアップ・復元',box);backup.href='/learning-backup';backup.target='_blank';backup.rel='noopener';
  el('p','送信設定の変更はIT担当者へご依頼ください。',box);
  const state=el('p','',box);state.setAttribute('role','status');
  async function refresh(){
    const v=await api('/api/operations/status');info.replaceChildren();
    const f=v.feedback;
    el('h2','ログの提出',info);
    el('p',f.config.enabled?'送信有効：起動時に未送信分を再送、ランチャー終了時に送信します。ブラウザーを閉じるだけでは送信しません。':'送信は停止中です。このPCにだけ保存しています。',info);
    el('p',`未送信 ${f.pending_outbox}件 ／ 要確認 ${f.rejected_package}件 ／ 最終成功 ${displayTime(f.last_sync)}`,info);
    if(f.config.enabled&&!f.token_saved)el('p','送信用Tokenを読み込めません。IT担当者へ再設定をご依頼ください。',info);
    if(f.last?.last_error)el('p',`直近の状態：${f.last.last_error}。認証失敗はToken設定を確認し「今すぐ送信」で再試行してください。`,info);
    const send=button('今すぐログを送信',()=>ctx.run(async()=>{send.disabled=true;state.textContent='送信中…';try{await api('/api/operations/send',{});await refresh();state.textContent='送信状況を更新しました。';}finally{send.disabled=false;}}),info);send.disabled=!f.config.enabled;
    el('p','通常は操作件数・処理の成功／失敗／中断件数・判断の採用／修正／保留件数・意見件数を送ります。自由記述は管理者が許可した場合だけ含めます。',info);
    el('h2',`アップデート（現在 ${v.version}）`,info);
    el('p',(updateLabels[v.update.status]||'状態を確認してください')+(v.update.version?`：${v.update.version}`:''),info);
    if(v.update.last_apply)el('p',`前回の更新：${updateLabels[v.update.last_apply.status]||'要確認'}`,info);
    button('更新を確認',()=>ctx.run(async()=>{state.textContent='更新を確認中…';await api('/api/operations/update-check',{});await refresh();state.textContent='確認しました。';}),info,true);
    if(v.update.status==='AVAILABLE'){
      const confirmed=field(info,'作業を保存しました。バックアップ後の更新・再起動に進む','checkbox',false);
      button('アップデートする',()=>ctx.run(async()=>{
        if(!confirmed.checked)throw new Error('作業保存と再起動の確認にチェックしてください');
        state.textContent='署名検証・ダウンロード中です。しばらくお待ちください。';
        const r=await api('/api/operations/update-apply',{confirm:true});state.textContent=updateLabels[r.status]||r.status;
      }),info);
    }
    if(!v.can_apply)el('p','更新の適用は「ブンセン予測を起動.cmd」から起動した場合に利用できます。',info);
    button('送信・更新状況を再表示',()=>ctx.run(refresh),info,true);
  }
  await refresh();
}

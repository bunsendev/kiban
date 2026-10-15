import {el} from './api.js';

export function inventoryCheckPanel(parent, extraction){
 const q=extraction.inventory_checks;if(!q)return;
 const panel=el('section','',parent);panel.className='document-review';
 el('h3','印刷在庫表の読取点検',panel);
 const summary=el('p',`在庫 ${q.inventory_rows}行 ／ 数量収支一致 ${q.match}行 ／ 不一致 ${q.mismatch}行 ／ 計算できない ${q.unverifiable}行 ／ 収支未点検 ${q.unchecked||0}行 ／ 必須項目確認 ${q.field_issues.length}行 ／ 同条件の複数明細 ${q.repeated_buckets.length}組`,panel);summary.setAttribute('role','status');
 el('p',q.basis,panel);el('p',q.assumption,panel);
 el('p','原本の前残＋当入－当出＋当調と現在欄を比較します。一致しても誤読がない保証ではありません。当調を現在庫へ再加算せず、出荷実績へ自動転用しません。',panel);
 const details=el('details','',panel);el('summary','確認が必要な明細と点検の見方',details);
 for(const r of q.movement_rows.filter(r=>r.status!=='match'))el('p',`${r.page}ページ ／ JAN ${r.jan}：${r.status==='mismatch'?'数量収支が不一致（差 '+r.difference+'、バラ換算の仮定）':'数量・C入を原本で確認'}`,details);
 const labels={jan:'JAN',snapshot:'在庫基準日',expiry:'賞味期限',source_detail_date:'倉庫入庫日',product_name:'商品名',location:'倉庫'};
 for(const r of q.field_issues)el('p',`${r.page}ページ ／ JAN ${r.jan||'不明'}：${r.fields.map(k=>labels[k]||k).join('、')}を確認`,details);
 for(const r of q.repeated_buckets)el('p',`JAN ${r.jan} ／ ${r.location} ／ 賞味期限 ${r.expiry} ／ 倉庫入庫日 ${r.receipt_date}：同条件の明細が${r.rows.length}行あります。原本行を保持し、自動削除しません。`,details);
 el('p','指定済み対象外商品は下の一覧で通常表示から外れます。「すべて」または「除外予定のみ」で確認・解除できます。点検件数には対象外の在庫明細も含みます。',details);
}

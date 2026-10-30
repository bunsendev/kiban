import {qualityPanel, methodFields} from './data-quality.js';

// Both entry screens use the same quality checks, consent and request contract.
export function createDetailedForecastMethods({qualityRoot, methodRoot, run, reopen, home}) {
  let current=null, generation=0;
  return {
    async show(analysisId) {
      const version=++generation, host=document.createElement('div');
      const check=await qualityPanel({run,open:reopen,home},host,analysisId);
      if(version!==generation)return null;
      qualityRoot.replaceChildren(host);
      const signature=JSON.stringify([analysisId,check.id,check.methods]);
      if(!current||current.signature!==signature){
        methodRoot.replaceChildren();
        const read=methodFields(methodRoot,check);
        current={analysisId,signature,read};
      }
      return check;
    },
    read(analysisId) {
      if(!current||current.analysisId!==analysisId)
        throw new Error('予測方式の確認が完了していません。状態を再表示してください。');
      return current.read();
    },
  };
}

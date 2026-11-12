import {author,C} from './native_deck.mjs';
const source='linear42_only_vector.py; interpretable_soft_rules.py:NAMES; pinned GBD CNFBaseFeatures.cc';
const common='The model uses exactly forty-two statistics from the formula. They are measurements, not forty-two independent decision rules. No application-family names, instance identifiers, satisfiability answers or solver runtime labels are available as prediction inputs.';
export function inputs42(p,n){
 const a=author(p,n,'42 statistics describe each formula','What exactly does the best tree ensemble observe?',source,{suppressDivider:true});
 a.tx('Input scope','Computed from the formula; no application-family labels',60,132,1160,38,26,C.muted,false,'the information available to the selector and the exclusion of family labels');
 a.tx('Group heading','Input group',60,212,280,34,25,C.ink,true,'the natural category of input measurements');
 a.tx('Meaning heading','What it measures',370,212,705,34,25,C.ink,true,'the concrete information in each input group');
 a.tx('Count heading','Count',1108,212,108,34,25,C.ink,true,'the number of numeric inputs, separate from clusters or rules','right');
 const rows=[
  ['Formula size','Variables; clauses',2],
  ['Clause lengths','Fractions of empty, 1–9 and ≥10-literal clauses',11],
  ['Clause signs','All-positive, all-negative, Horn and dual-Horn fractions',4],
  ['Sign balance','How mixed signs are within clauses and for each variable',10],
  ['Variable activity','Occurrences; participation in Horn and dual-Horn clauses',15],
 ];
 rows.forEach(([group,meaning,count],i)=>{const y=281+i*67;
  a.tx('Feature group '+i,group,60,y,285,43,27,C.ink,true,'the readable category '+group.toLowerCase());
  a.tx('Feature meaning '+i,meaning,370,y,715,58,25,C.ink,false,'a plain-language definition of '+group.toLowerCase());
  a.tx('Feature dimension '+i,String(count),1108,y,108,43,29,C.purple,true,'the exact dimensionality of '+group.toLowerCase(),'right');
 });
 a.tx('Distribution summary count','Each distribution gives five summaries of its average, spread and extremes.',60,626,1160,34,22,C.muted,false,'why two sign-balance distributions give ten inputs and three activity distributions give fifteen');
 a.footer('Horn: ≤1 positive literal; dual-Horn: ≤1 negative literal. Distribution summaries and exact input mapping are in the appendix.');
 a.notes('本页回答42维到底是什么，不把它们说成42条单独选相位的规则。2个规模：变量范围、子句数；11个长度比例：空、1到9、≥10；4个符号类型比例：全正、全负、Horn、dual-Horn；10个符号均衡统计：逐子句和逐变量两种分布各5项；15个活动统计：变量出现次数、Horn参与、dual-Horn参与三种分布各5项。合计2+11+4+10+15=42。均衡度是min(正,负)/max(正,负)，0表示单边，1表示相等。分布的五个量为均值、方差、最小、最大以及固定提取器记录的entropy；部分输入有对数或尺度归一化。精确42列和边界语义见附录。这里不加入63个联合分布或可用标志。',
 common+' The groups are size, clause lengths, clause signs, sign balance, and variable activity. The counts are two, eleven, four, ten, and fifteen. Sign balance has five summaries across clauses and five across variables. Variable activity has five summaries each for total occurrences, Horn participation and dual-Horn participation. All forty-two numbers go into the ensemble together; no one feature is claimed to determine the winning phase.');
 return a.finish();
}
export function catalog42(p,n,catalog){
 const a=author(p,n,'Appendix: exact 42-input mapping','How do the feature groups expand into forty-two model inputs?',source,{suppressDivider:true});
 const rows=[
  ['1–2','Size','log(1 + variables); log(1 + clauses)'],
  ['3–13','Lengths','Empty fraction; length 1–9 and ≥10 fractions'],
  ['14–17','Clause types','All-positive; all-negative; Horn; dual-Horn'],
  ['18–22','Clause balance','Five summaries of within-clause sign balance'],
  ['23–27','Variable balance','Five summaries of each variable’s sign balance'],
  ['28–32','Occurrences','Five summaries of literal occurrences per variable'],
  ['33–37','Horn activity','Five summaries of Horn participation per variable'],
  ['38–42','Dual-Horn activity','Five summaries of dual-Horn participation per variable'],
 ];
 rows.forEach(([ids,group,meaning],i)=>{const y=147+i*51;
  a.tx('Feature indices '+i,ids,60,y,110,36,24,C.purple,true,'the exact positions in the model input vector');
  a.tx('Feature category '+i,group,190,y,265,36,24,C.ink,true,'the group occupying these input coordinates');
  a.tx('Feature expansion '+i,meaning,485,y,735,42,24,C.ink,false,'the actual statistics in this coordinate range');
 });
 a.tx('Summary definition','Five summaries: mean, variance, minimum, maximum and entropy.',60,577,1160,35,24,C.ink,false,'the five values making each distribution group concrete');
 a.tx('Extension boundary','The 63 length × sign bins are an experimental extension, outside these 42 inputs.',60,626,1160,32,22,C.muted,false,'the distinction between the current forty-two-input policy and the separate extension');
 a.footer('Occurrence groups use log / mean-normalized transforms; sign-balance summaries retain their recorded scale.');
 a.notes('逐坐标映射见下列完整清单。entropy是固定GBD实现记录的分布摘要，不另换实现。规模中的变量数遵循固定提取器的DIMACS变量编号范围，可含未使用编号；变量均衡保留上游v<n_vars边界，未静默修复后再混用旧模型。长度空比例为max(0,1−其他长度比例之和)。全正/全负及Horn比例按固定原始提取器定义处理空子句。三个活动分布的5变换为log1p(mean)、log1p(variance/max(mean²,1e−12))、min/max(mean,1e−12)、log1p(max/max(mean,1e−12))及entropy。这些复现细节不在主讲展开。63个长度×正文字比例分箱只放在这里说明边界，不作为当前最好模型的一部分。',
 'This is the complete coordinate map. The five summaries are mean, variance, minimum, maximum, and the extractor’s entropy statistic. The occurrence groups apply the frozen logarithmic and mean-normalized transforms. The exact source semantics are retained, including boundary behavior. The extra sixty-three length-by-sign bins belong to a separate experimental input and are not part of the current forty-two-feature ensemble.',
 JSON.stringify(catalog,null,2));
 return a.finish();
}

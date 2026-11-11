import {author,legend,cumulative,C} from './native_deck.mjs';

function page(p,n,title,question,source,d){
 const a=author(p,n,title,question,source,{suppressDivider:true});
 a.s.speakerNotes.text=d.notes[String(n)];return a;
}
function down(a,name,x,y1,y2,why){
 a.line(name,x,y1,x,y2,C.muted,2,why);
 a.path(name+' head',[[x-5,y2-8],[x,y2],[x+5,y2-8]],C.muted,2,'the downward reading order for '+name);
}
function finish(a,result){result.push(a.finish());}

export async function refined({presentation:p,input:{data:d}}){
 const out=[];
 {
 const a=page(p,1,'Baseline by CPU time','How much room is there beyond default phasing?','raw_data_20261110/statistics.json; vbs_preferences_20261110/all_preferences.csv',d);
 a.tx('Experimental population','CaDiCaL on 4,719 retained Anniversary 2022 instances',60,132,1160,34,25,C.muted,false,'the solver and population required to interpret the baseline');
 legend(a,true);cumulative(a,d,'cpu_s');
 a.row('Default endpoint','D solves','3,385',239,C.blue);
 a.row('Oracle endpoint','VBS solves','3,547',351,C.ink);
 a.tx('Oracle cost bound','10.85%',1010,486,210,58,43,C.purple,true,'the free per-instance PAR2 saving ceiling relative to D');
 a.tx('Bound meaning','max. PAR2 saving vs D',1000,546,220,54,21,C.muted,false,'what the 10.85% measures, without equating it to solve-count growth');
 a.tx('Horizontal axis title','CPU seconds per instance',110,600,850,32,23,C.ink,false,'the horizontal units for the cumulative curve','center');
 a.footer('PAR2: solved CPU time within 600 s; otherwise 1,200 s. VBS picks the best phase for each instance, for free.');
 finish(a,out);
 }
 {
 const a=page(p,2,'Baseline by conflicts','Does the gap also appear in search work?','vbs_preferences_20261110/all_preferences.csv',d);
 a.tx('Conflict definition','Conflicts count contradictions encountered during search.',60,132,1160,34,25,C.muted,false,'a one-line definition before introducing the new axis');
 legend(a);cumulative(a,d,'conflicts',true);
 a.tx('Horizontal axis title','Conflicts until completion (log spacing)',110,600,1100,33,23,C.ink,false,'the units and spacing used on the horizontal axis','center');
 a.footer('Verified completions from the same 600 CPU s runs. VBS minimizes conflicts separately from time.');
 finish(a,out);
 }
 {
 const a=page(p,3,'Clustering by formula structure','What features were clustered, and what phase did the clusters favor?','structural_clusters.py:FEATURE_GROUPS,load; structural_clusters_20261110/summary.json; structural_views_20261110/summary.json',d);
 a.tx('Example label','Example formula',60,149,590,33,24,C.muted,false,'marking the CNF as a counting illustration, not a measured benchmark');
 a.tx('Example formula','(x ∨ y) ∧ (¬x ∨ y ∨ z)',60,197,650,54,34,C.ink,true,'a concrete formula from which every displayed example value can be counted');
 a.tx('Feature column heading','Feature',60,288,450,34,25,C.muted,false,'the measured property, before displaying its example value');
 a.tx('Value column heading','Example value',492,288,214,34,25,C.muted,false,'separating illustrative feature values from real policy scores','right');
 const rows=[['Mean clause length','(2 + 3) / 2 = 2.5'],['Two-literal clauses','1 / 2 = 50%'],['All-positive clauses','1 / 2 = 50%']];
 rows.forEach(([label,value],i)=>{
  const y=356+i*70;
  a.tx('Feature example '+i,label,60,y,450,39,27,C.ink,false,'the actual clustering feature '+label.toLowerCase());
  a.tx('Feature value '+i,value,492,y,214,40,25,C.blue,true,'the counted value of '+label.toLowerCase(),'right');
 });
 a.tx('Model input scope','12 static features',829,240,370,40,29,C.ink,true,'the actual number of inputs used by the original eight-cluster run','center');
 down(a,'Feature to clusters',1014,297,333,'clustering using formula measurements without runtime inputs');
 a.tx('Cluster count','8 structural clusters',814,355,400,42,29,C.ink,true,'the number of measured groups in the displayed experiment','center');
 down(a,'Clusters to choice',1014,414,450,'choosing each cluster’s lowest-mean-cost fixed phase');
 a.tx('Cluster result','D is best in all 8',800,473,419,48,34,C.blue,true,'the lowest-mean-PAR2 fixed phase in each original cluster','center');
 a.tx('Cost criterion','Lowest mean PAR2',824,531,380,33,23,C.muted,false,'best refers to aggregate scored cost, not every member having the same winner','center');
 a.footer('Expanded clustering: +0.16% saving vs D, with uncertainty spanning zero. Full features and results in the appendix.');
 a.notes('用同一个教学公式说明特征：(x∨y)∧(¬x∨y∨z)，两子句长度为2和3，所以均长2.5；一个是二元，一个全正，两个比例都是50%。这三项均在原8簇的12项特征中，显示原尺度；日志变换、裁剪和标准化见附录。右侧“D最好”指簇内平均PAR2最低，不是每个成员都偏好D。原8簇人口为61、502、441、843、572、165、1504、631。Astra建议属于更广的结构探索，不能与该12项输入混为一谈。扩展15组的0.1573%区间为−0.3062%到0.6343%。',
 'Here are concrete examples of what we clustered. The two clauses have lengths two and three, so the average length is two point five. One of the two clauses is binary, and one is all-positive, giving fifty percent for each feature. The actual clustering uses twelve static features. In each of the original eight clusters, D has the lowest mean penalized runtime. A broader clustering search gave only a small uncertain gain. The full feature list and preprocessing are in the appendix.');
 finish(a,out);
 }
 {
 const a=page(p,4,'Predict savings before switching phase','What does supervised learning predict, and when does it choose a forced phase?','research-state.yaml:R12_linear42_positive_evidence_clarification; materialize_linear42_candidate.py',d);
 a.box('Formula input',60,248,280,152,'the formula and static measurements available before solving');
 a.tx('Formula label','Formula\n42 static features',82,281,242,91,29,C.ink,true,'the predictor input and dimensionality');
 a.arrow('Feature to prediction',353,324,420,324,'mapping static features to predicted savings');
 a.box('Prediction model',435,225,373,198,'the tree ensemble, distinct from the SAT solver');
 a.tx('Model identity','ExtraTrees ensemble',457,249,333,42,29,C.purple,true,'the actual model supporting the reported gain');
 a.tx('Prediction meaning','F+ saving vs D\nF− saving vs D',457,316,333,79,29,C.ink,false,'the two regression targets and their common baseline');
 a.arrow('Prediction to selection',821,324,909,324,'using the predicted advantage for phase selection');
 a.tx('Selection condition','Saving > threshold?\nPick best F+ / F−\nOtherwise: D',930,263,289,150,28,C.ink,true,'the complete switch-or-default rule');
 a.footer('The switching threshold is selected on validation data.');
 finish(a,out);
 }
 {
 const a=page(p,5,'Supervised selection saves 2.10% on development folds','How much of the VBS cost gap does the selector capture?','research-state.yaml:R12_linear42_positive_evidence_clarification; linear42_bounded_prefetch_cost',d);
 a.tx('Common cost baseline','PAR2 cost reduction relative to D',60,133,1160,36,26,C.muted,false,'the shared denominator and direction of the two bars');
 const left=284,right=1110,map=v=>left+(right-left)*v/12;
 for(const [label,value,y,color] of [['Supervised selector',d.supervised.gain_pct,286,C.purple],['Free VBS',10.8528134644,414,C.ink]]){
  a.tx('Saving label '+label,label,60,y-13,204,75,28,C.ink,label.startsWith('Supervised'),'which scored strategy is being compared');
  a.line('Saving bar '+label,left,y+10,map(value),y+10,color,22,'the PAR2 reduction '+value.toFixed(6)+' percent relative to fixed D');
  a.tx('Saving value '+label,value.toFixed(2)+'%',map(value)+15,y-15,147,49,34,color,true,'the direct measured saving for this strategy');
 }
 a.line('Common saving axis',left,488,right,488,C.line,1.4,'the common percentage scale for policy and free oracle');
 [0,5,10].forEach(v=>a.tx('Saving tick '+v,v+'%',map(v)-30,506,70,32,23,C.muted,false,'the percentage scale value '+v,'center'));
 a.tx('Additional verified solves','+34 solved instances',60,581,640,43,30,C.purple,true,'the solve-count improvement, distinct from the PAR2 percentage');
 a.tx('Incomplete acquisition scope','Full feature costs pending',724,583,496,43,27,C.muted,true,'the unresolved cost condition that qualifies the headline');
 a.footer('Five development folds; equivalent instances stay together. Recorded query costs included.');
 finish(a,out);
 }
 {
 const a=page(p,6,'The gain shrinks on held-out structural groups','Does the gain persist when structural groups are absent from training?','research-state.yaml:R12_linear42_positive_evidence_clarification',d);
 a.tx('Common metric','PAR2 saving vs D. Each structural holdout excludes a group from training.',60,134,1160,66,25,C.muted,false,'the common metric and what the holdout changes');
 const rows=[['Mixed folds',2.0976772347],['Coarse structural holdout',.3708522818],['Fine structural holdout',-.2608130689]];
 rows.forEach(([label,v],i)=>{const y=267+i*119;
  a.tx('Split '+i,label,60,y,810,55,31,C.ink,i===0,'the train/evaluation partition for this result');
  a.tx('Split saving '+i,(v>=0?'+':'')+v.toFixed(2)+'%',935,y-4,280,62,45,v<0?C.orange:C.purple,true,'the R12 result under '+label.toLowerCase(),'right');
 });
 a.footer('Same candidate and development population.');
 finish(a,out);
 }
 {
 const a=page(p,7,'Can a few rules retain the ensemble’s gain?','How does model inspection produce a testable, readable rule?','research-state.yaml:astra_linear42_interpretation,R26_astra_rule; score_astra_small_fplus.py',d);
 const xs=[60,484,918];
 const labels=['Saved ensemble','Astra inspection','Candidate rules'];
 const detail=['Features, thresholds\nand leaf predictions','Propose short\nfeature conditions','Evaluate on\nheld-out folds'];
 xs.forEach((x,i)=>{a.box('Interpretation object '+i,x,221,300,151,'the '+labels[i].toLowerCase()+' object in model interpretation');a.tx('Interpretation label '+i,labels[i],x+20,243,260,39,28,i===1?C.purple:C.ink,true,'the named input, reader or output');a.tx('Interpretation detail '+i,detail[i],x+20,301,260,64,24,C.ink,false,'the operation or information at this stage');});
 a.arrow('Model inspection flow',373,296,470,296,'passing the saved model to interpretation');a.arrow('Rule proposal flow',797,296,904,296,'passing readable conditions to evaluation');
 a.tx('Concrete rule template','Example: low clause count + low dual-Horn fraction',60,453,1160,50,31,C.ink,true,'the source-supported two-feature rule template');
 a.tx('Rule action','Choose F+ when both conditions hold; otherwise D',60,529,1160,43,29,C.ink,false,'the complete rule action and fallback');
 a.footer('Dual-Horn: at most one negated literal per clause. Thresholds are fitted inside training folds.');
 finish(a,out);
 }
 {
 const a=page(p,8,'Simple rules retain less than 0.5% saving','Do the readable candidates preserve the original ensemble advantage?','research-state.yaml:R12,R26,R31,R32',d);
 a.tx('Common cost baseline','PAR2 cost reduction relative to D',60,134,1160,38,26,C.muted,false,'the common percentage definition across displayed policies');
 const rows=[['Original ensemble',2.0976772347,C.purple],['Two-condition rule',.1716960116,C.blue],['Tree (≤16 leaves)',.4931167660,C.blue],['Directional rules (≤32 leaves)',.4400539588,C.blue]];
 rows.forEach(([label,v,col],i)=>{const y=248+i*91;a.tx('Compression label '+i,label,60,y,820,47,31,C.ink,i===0,'the model or rule associated with the score');a.tx('Compression saving '+i,v.toFixed(2)+'%',935,y-6,280,63,46,col,true,'the measured saving for '+label.toLowerCase(),'right');});
 a.footer('Simple-rule scores assume free features and queries; the ensemble score includes query costs.');
 finish(a,out);
 }
 {
 const a=page(p,9,'Appendix: population and cost accounting','What data, cutoffs and incomplete costs underlie the comparison?','START_HERE_ZH.md; raw_data_20261110/statistics.json; research-state.yaml',d);
 const rows=[['Original Anniversary 2022 entries','5,355'],['Official all-track-unsolved exclusions','636'],['Retained development instances','4,719'],['Configuration records','14,157 / 14,157'],['CPU cutoff per run','600 s'],['All three phases time out','1,172 instances'],['Inputs with measured extraction costs','1,024 / 4,719']];
 rows.forEach(([label,v],i)=>{const y=145+i*49;a.tx('Population field '+i,label,60,y,850,39,25,C.ink,false,'the evaluation condition '+label);a.tx('Population value '+i,v,909,y,307,39,26,C.blue,true,'the exact value of '+label.toLowerCase(),'right');});
 a.tx('Cost equation','PAR2 = solved CPU seconds, otherwise 1,200 seconds',60,524,1160,42,27,C.ink,true,'the common timeout penalty');
 a.tx('Saving equation','Saving (%) = 100 × (D PAR2 − policy PAR2) / D PAR2',60,590,1160,44,27,C.ink,true,'the exact denominator used for reported improvements');
 a.footer('CaDiCaL 3.0.1, seed 0. 3,695 unpriced inputs remain; 45 measured acquisition failures fall back to paid D.');
 finish(a,out);
 }
 {
 const a=page(p,10,'Appendix: expanded clustering results','What happened beyond the original eight clusters?','structural_views_20261110/summary.json',d);
 a.tx('Column view','Features used',60,147,360,34,26,C.ink,true,'the feature set and its dimensionality');
 [12,24,48].forEach((k,j)=>a.tx('Column k '+k,k+' clusters',500+j*240,147,210,34,26,C.ink,true,'the number of clusters','right'));
 const viewNames={size:'Size (2 features)',width:'Clause width (11)',sign:'Signs (7)',graph:'Graph (8)',combined:'Combined (28)'};
 ['size','width','sign','graph','combined'].forEach((view,i)=>{const y=224+i*65;a.tx('View '+view,viewNames[view],60,y,390,39,27,C.ink,false,'the feature set and number of input statistics');[12,24,48].forEach((k,j)=>{const v=d.cluster_variants.find(v=>v.view===view&&v.k===k).par2_improvement_pct;a.tx('View score '+view+k,(v>=0?'+':'')+v.toFixed(2)+'%',500+j*240,y,210,39,27,v<0?C.orange:C.blue,false,'the out-of-fold PAR2 gain for this view and cluster count','right');});});
 a.tx('Nested result','Selected policy: +0.16%; 95% interval [−0.31%, +0.63%]',60,601,1160,45,27,C.ink,true,'the nested selection result rather than a favorable cell chosen afterwards');
 a.footer('All values are PAR2 savings vs D. Feature acquisition costs excluded.');
 a.s.speakerNotes.text+='\nExpanded feature dimensions: size 2; width 11; signs 7; graph 8; combined 28. Column counts 12/24/48 refer to clusters. The original 8-cluster run separately used 12 features.';
 finish(a,out);
 }
 {
 const a=page(p,11,'Appendix: original 8-cluster feature set','What measurements entered the original clustering?','structural_clusters.py:FEATURE_GROUPS,load,standardize',d);
 const rows=[['Size (2)','Variable count; clauses / variables'],['Clause lengths (5)','Mean length; fractions of length 1, 2, 3 and ≥5'],['Signs (3)','All-positive; all-negative; dual-Horn minus Horn fractions'],['Connectivity (2)','Variable-degree CV; connected components / variables']];
 rows.forEach(([label,value],i)=>{const y=157+i*94;a.tx('Feature group '+i,label,60,y,285,46,27,C.purple,true,'the feature group and dimensionality');a.tx('Feature definition '+i,value,380,y,840,76,26,C.ink,false,'the actual input statistics for this group');});
 a.tx('CV definition','Degree CV = standard deviation / mean of variable–clause degrees',60,562,1160,43,24,C.muted,false,'the definition of the one less familiar graph statistic');
 a.footer('Horn: at most one positive literal per clause. Dual-Horn: at most one negative literal.');
 a.notes('原八簇共有12维：log1p变量数、log1p子句/变量数、log1p平均长度；单位、二元、三元、长度≥5子句比例；全正、全负以及dual-Horn减Horn子句比例；log1p变量度CV；log1p连通分量/变量数。四类特征按1/sqrt(类内维数)加权。clipping、均值和标准差在训练折拟合，再用于评价折。正二元比例另有相关分析，但不是原8簇的12个输入之一；不把它或所有Astra建议都混进本实验。',
 'These are the twelve actual inputs to the original clustering. They cover size, clause lengths, clause signs and connectivity. We show their natural meanings here. The implementation applies the specified logarithmic transforms and fits clipping and standardization within training folds. Group weights prevent a category with more dimensions from dominating simply because it has more features.');
 finish(a,out);
 }
 return out;
}

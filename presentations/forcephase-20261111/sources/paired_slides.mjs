import {author,C} from './native_deck.mjs';
const names={Fplus:'F+',Fminus:'F−'},fmt=n=>n.toLocaleString('en-US');
const source='vbs_preferences_20261110/all_preferences.csv; meeting 7:21–8:20 and 12:04–13:40';
function record(a,o,label,why,design,kind='path'){
 const s=o.toSnapshot();a.log.push({slide:a.log[0].slide,id:s.aid||s.id,name:label,kind,priority:'main',necessity:why,design,source,removalImpact:'The audience would lose '+why,scores:{necessity:4,clarity:4,simplicity:4,evidence:5,readability:4,distraction:0}});return o;
}
function markers(a,label,points,fill,symbol='circle',r=1.65){
 if(!points.length)return;
 const pad=5,x=Math.min(...points.map(p=>p[0]))-pad,y=Math.min(...points.map(p=>p[1]))-pad;
 const w=Math.max(...points.map(p=>p[0]))-x+pad,h=Math.max(...points.map(p=>p[1]))-y+pad,commands=[];
 for(const [ax,ay] of points){
  const cx=ax-x,cy=ay-y,k=.5522847498*r;
  if(symbol==='circle')commands.push({moveTo:{x:cx+r,y:cy}},{cubicBezTo:{x1:cx+r,y1:cy+k,x2:cx+k,y2:cy+r,x:cx,y:cy+r}},{cubicBezTo:{x1:cx-k,y1:cy+r,x2:cx-r,y2:cy+k,x:cx-r,y:cy}},{cubicBezTo:{x1:cx-r,y1:cy-k,x2:cx-k,y2:cy-r,x:cx,y:cy-r}},{cubicBezTo:{x1:cx+k,y1:cy-r,x2:cx+r,y2:cy-k,x:cx+r,y:cy}},{close:{}});
  else if(symbol==='up')commands.push({moveTo:{x:cx,y:cy-r}},{lineTo:{x:cx+r,y:cy+r}},{lineTo:{x:cx-r,y:cy+r}},{close:{}});
  else commands.push({moveTo:{x:cx+r,y:cy}},{lineTo:{x:cx-r,y:cy+r}},{lineTo:{x:cx-r,y:cy-r}},{close:{}});
 }
 const o=a.s.shapes.add({name:label,geometry:'custom',position:{left:x,top:y,width:w,height:h},fill,line:{fill:'none',width:0},customPaths:[{width:w,height:h,commands}]});
 return record(a,o,label,`all ${points.length} paired observations in the ${label} category`,'Native editable vector series. Every point retains its measured transformed coordinate, including overlapping points.');
}
function highlight(a,label,x,y,col){
 const o=a.s.shapes.add({name:'Example '+label+' ring',geometry:'ellipse',position:{left:x-5.8,top:y-5.8,width:11.6,height:11.6},fill:'#FFFFFF/20',line:{fill:col,width:2.2}});
 record(a,o,'Example '+label+' ring','the measured outlier linked to example '+label,'Hollow ring preserves the measured location; its number links to values below.','shape');
 const dx=x>1100?-23:10;
 a.line('Example '+label+' leader',x+Math.sign(dx)*5,y+5,x+dx,y+14,C.ink,1,'linking the numbered example to its measured location');
 a.tx('Example '+label+' number',label,x+dx-2,y+12,26,29,20,C.ink,true,'the lookup key for measured example '+label);
}
function panel(a,data,k,index,metric){
 const time=metric==='cpu_s',label=names[k],col=C[k],left=index?736:116,top=time?265:242,w=420,h=time?259:282;
 const min=time?.005:0,max=time?600:5e7,t=v=>time?Math.log10(v):Math.log10(1+v),lo=t(min),hi=t(max);
 const x=v=>left+w*(t(v)-lo)/(hi-lo),y=v=>top+h-h*(t(v)-lo)/(hi-lo),tx=left+w+15,ty=top-15;
 a.tx('Panel '+k,label+' vs D',left-2,177,440,36,28,col,true,'the forced phase compared with native default on the same formula');
 a.tx('Vertical units '+k,label+(time?' CPU seconds':' conflicts'),left-2,215,365,26,19,C.muted,false,'the vertical units; lower means less under the forced phase');
 const ticks=time?[[.01,'0.01'],[.1,'0.1'],[1,'1'],[10,'10'],[100,'100']]:[[0,'0'],[10,'10'],[1e3,'1,000'],[1e5,'100k'],[1e7,'10M']];
 for(const [v,txt] of ticks){
  if(v!==min){a.line('X grid '+k+txt,x(v),top,x(v),top+h,C.line,.8,'reading the common numeric scale');a.line('Y grid '+k+txt,left,y(v),left+w,y(v),C.line,.8,'reading the common numeric scale');}
  a.tx('X tick '+k+txt,txt,x(v)-30,top+h+8,60,27,17,C.muted,false,'the horizontal coordinate '+txt,'center');
  a.tx('Y tick '+k+txt,txt,left-68,y(v)-10,58,25,17,C.muted,false,'the vertical coordinate '+txt,'right');
 }
 a.line('X axis '+k,left,top+h,left+w,top+h,C.muted,1.2,'the D numeric measurement axis');
 a.line('Y axis '+k,left,top,left,top+h,C.muted,1.2,'the forced-phase numeric measurement axis');
 a.line('Equal measurements '+k,left,top+h,left+w,top,C.muted,1.5,'the equal-measurement diagonal; below it the forced phase is lower');
 if(time){
  a.line('Timeout rail x '+k,tx,top,tx,top+h,C.line,1.5,'the categorical D timeout rail, separate from numeric solve time');
  a.line('Timeout rail y '+k,left,ty,left+w,ty,C.line,1.5,'the categorical forced-phase timeout rail');
  a.tx('Timeout tick x '+k,'TO',tx-16,top+h+8,39,27,17,C.muted,true,'D did not solve within the cutoff','center');
  a.tx('Timeout tick y '+k,'TO',left-57,ty-10,47,25,17,C.muted,true,'the forced phase did not solve within the cutoff','right');
 }
 const both=[],onlyD=[],onlyF=[];
 for(const r of data.rows){const d=r.D,f=r[k];if(d.solved&&f.solved)both.push([x(d[metric]),y(f[metric])]);else if(time&&d.solved)onlyD.push([x(d.cpu_s),ty]);else if(time&&f.solved)onlyF.push([tx,y(f.cpu_s)]);}
 markers(a,k+' both solved '+metric,both,'#718CA7/70');
 if(time){markers(a,k+' only D solved',onlyD,C.blue+'/70','up',2.4);markers(a,k+' only forced solved',onlyF,col+'/70','right',2.4);}
 data.examples.filter(e=>e.action===k).forEach(e=>highlight(a,e.label,x(e.D[metric]),y(e[k][metric]),e.direction==='forced_faster'?col:C.blue));
 a.tx('Horizontal units '+k,'D '+(time?'CPU seconds (log scale)':'conflicts (log(1 + count) spacing)'),left-24,560,480,32,time?21:19,C.ink,false,'the horizontal units and transformation','center');
 const c=data.pair_counts[k];
 if(time){
  a.tx('Completion categories '+k,`${fmt(c.only_F)} only ${label} · ${fmt(c.only_D)} only D · ${fmt(c.neither)} neither`,left-36,600,530,32,21,C.ink,false,'one-sided completions and both-timeout cases, retaining the hard formulas');
  a.tx('Measured example values '+k,index?'3: 540→0.60 s     4: 0.029→116 s':'1: 162→0.28 s     2: 0.125→362 s',left-36,637,530,29,20,C.ink,false,'rounded CPU times for the highlighted wins and losses');
 }else{
  a.tx('Conflict comparison support '+k,`${fmt(c.both_solved)} paired completions`,left-36,602,530,32,23,C.ink,true,'the exact both-solved population of the conflict scatter');
  a.tx('Conflict direction counts '+k,`${label} lower: ${fmt(c.conflicts_F_lower)} · equal: ${fmt(c.conflicts_equal)}`,left-36,638,530,29,21,C.muted,false,'counts of strictly lower and tied forced-phase conflicts');
 }
}
function exampleNotes(data){return data.examples.map(e=>{const k=e.action;return `Example ${e.label}: instance_key=${e.id}; ${names[k]} versus D. D: ${e.D.cpu_s} CPU s, ${fmt(e.D.conflicts)} conflicts. ${names[k]}: ${e[k].cpu_s} CPU s, ${fmt(e[k].conflicts)} conflicts. Both solved. D/forced CPU ratio=${e.forced_speedup_vs_D.toFixed(6)}.`;}).join('\n');}
export function pairedTime(p,n,data){
 const a=author(p,n,'Phase effects vary sharply by instance','Which benchmarks gain or lose from forced phases?',source,{suppressDivider:true});
 a.tx('How to read the comparison','One point = one instance. Below the diagonal: forced phase faster; above: D faster.',60,132,1160,37,24,C.muted,false,'the observation unit, equality reference and direction of advantage');
 panel(a,data,'Fplus',0,'cpu_s');panel(a,data,'Fminus',1,'cpu_s');
 a.footer('TO: timeout at 600 CPU s, not a solve time. Dots: both solved; triangles: one solved. Examples show D → forced seconds.');
 a.notes('教授要求看散点图两侧的具体实例。横轴D，纵轴F，均是CPU秒对数间距；下方F快，上方D快。已完成对显示为点，只有一方完成为三角；未完成放专用TO边界，不伪装成600秒精确解题时间。双方超时不画数值点，保留在neither计数。F+独有92题，D独有401题；F−独有112题，D独有442题。1–4为实测极端例子，不是平均加速，也不是新规则的验证。接下来问这些差异能否从结构预知。',
 'Cumulative curves hide large differences between individual formulas. Each point compares the same formula under D and one forced phase. Below the diagonal favors the forced phase; above favors D. F-plus solves ninety-two instances that D misses, while D solves four hundred and one that F-plus misses. For F-minus, those counts are one hundred and twelve and four hundred and forty-two. Examples one to four show large gains and losses. They are descriptive extremes, not average speedups. We now ask whether structure can predict when switching helps.',
 exampleNotes(data)+'\nSelection: '+data.example_selection+'\nNo new solver runs or fits. Full lookup: paired-instance-examples-20261111.csv.');
 return a.finish();
}
export function pairedConflicts(p,n,data){
 const a=author(p,n,'Appendix: paired comparisons by conflicts','Do the highlighted time differences also appear in search work?',source,{suppressDivider:true});
 a.tx('Conflict scatter reading','One point = one formula solved by both. Below the diagonal: fewer forced-phase conflicts.',60,132,1160,37,24,C.muted,false,'the paired population and direction of the conflict comparison');
 panel(a,data,'Fplus',0,'conflicts');panel(a,data,'Fminus',1,'conflicts');
 a.footer('Same examples 1–4 as the time plot. Only both-solved pairs within 600 CPU s; zero conflicts retained. k = 1,000; M = 1,000,000.');
 a.notes('教授要求保存并比较同一题各配置的conflicts。这页用已完成轨迹逐题配对，不靠累计图的边际分布推断。0用log(1+count)保留；只显示双方均在600 CPU秒完成的2984及2943对。超时的冲突计数不是解题总工作量，因此不混入。1–4与时间页四题一致，四例方向一致；不据此推出整个样本的因果解释。单侧解出题仍在时间页与源数据保留。',
 'Here is the requested paired view of conflicts. We compare the same formulas, keeping pairs where both configurations completed within the existing six-hundred-second runs. Lower points mean fewer conflicts under the forced phase. Examples one through four are the same as in the time plot. Their advantages and disadvantages also appear in conflicts, without establishing a causal mechanism for the whole population. Zero-conflict completions remain through log-one-plus-count spacing.',
 exampleNotes(data)+'\nSource matrix checksum: '+data.source_sha256);
 return a.finish();
}

const C={ink:'#252D36',muted:'#6B7785',line:'#DCE2E9',blue:'#1F6FA8',purple:'#6A43B8',orange:'#B86A2B',D:'#1F6FA8',Fplus:'#6A43B8',Fminus:'#B86A2B',VBS:'#252D36'};
const NAME={D:'D',Fplus:'F+',Fminus:'F−',VBS:'VBS'};

function author(p,n,title,question,source,options={}){
 const s=p.slides.add({width:1280,height:720});s.background.fill='#FFFFFF';const log=[];
 function record(o,name,why,design,kind='text',priority='main'){
  const snap=o.toSnapshot();log.push({slide:n,id:snap.aid||snap.id,name,kind,priority,necessity:why,design,source,removalImpact:'The audience would lose '+why.replace(/^[A-Z]/,a=>a.toLowerCase()),scores:{necessity:priority==='navigation'?2:4,clarity:4,simplicity:4,evidence:4,readability:4,distraction:0}});return o;
 }
 function tx(name,text,x,y,w,h,size=25,color=C.ink,bold=false,why='',align='left'){
  const o=s.shapes.add({name,geometry:'textbox',position:{left:x,top:y,width:w,height:h},fill:'none',line:{fill:'none',width:0}});
  o.text=text;o.text.style={fontSize:size,typeface:'Arial',color,bold,alignment:align,verticalAlignment:'top',insets:0,autoFit:'none',wrap:'square'};
  return record(o,name,why||'the meaning of '+name,`Native editable Arial text, ${size}px; ${align} alignment. Color ${color} marks ${color===C.muted?'supporting scope':'the relevant concept or result'}.`);
 }
 function path(name,pts,color=C.line,width=1.2,why='the plotted relationship',box=null){
  const minx=Math.min(...pts.map(a=>a[0])),miny=Math.min(...pts.map(a=>a[1]));
  const pos=box||{left:minx,top:miny,width:Math.max(1,Math.max(...pts.map(a=>a[0]))-minx),height:Math.max(1,Math.max(...pts.map(a=>a[1]))-miny)};
  const points=box?pts:pts.map(a=>[a[0]-minx,a[1]-miny]);
  const o=s.shapes.add({name,geometry:'custom',position:pos,fill:'none',line:{fill:color,width,style:'solid'},customPaths:[{width:pos.width,height:pos.height,commands:points.map((a,i)=>i?{lineTo:{x:a[0],y:a[1]}}:{moveTo:{x:a[0],y:a[1]}})}]});
  return record(o,name,why,'Native editable data path. Geometry follows the supplied values; no smoothing. Stroke color consistently identifies the same phase.','path');
 }
 function line(name,x1,y1,x2,y2,color=C.line,width=1.2,why='the comparison baseline'){return path(name,[[x1,y1],[x2,y2]],color,width,why);}
 function box(name,x,y,w,h,why){
  const o=s.shapes.add({name,geometry:'rect',position:{left:x,top:y,width:w,height:h},fill:'#FFFFFF',line:{fill:C.line,width:1.5}});
  return record(o,name,why,'Thin unfilled boundary defines a technical object without creating a decorative panel.','shape');
 }
 function arrow(name,x1,y1,x2,y2,why){
  line(name,x1,y1,x2,y2,C.muted,2,why);
  const sign=x2>=x1?1:-1;path(name+' head',[[x2-sign*9,y2-5],[x2,y2],[x2-sign*9,y2+5]],C.muted,2,'the direction of '+name);
 }
 function row(name,label,value,y,color=C.ink){tx(name+' label',label,1010,y,205,28,21,C.muted,false,'which quantity the adjacent number measures');tx(name+' value',value,1010,y+30,205,56,44,color,true,'the exact '+label.toLowerCase());}
 tx('Title',title,60,38,1150,86,40,C.ink,true,'the single question or supported result on this page');
 if(!options.suppressDivider)line('Footer divider',60,659,1220,659,C.line,1,'the separation between the primary evidence and its scope');
 const page=tx('Page number',String(n),1190,686,30,22,16,C.muted,false,'page navigation','right');log[log.length-1].priority='navigation';
 return {s,log,tx,path,line,box,arrow,row,question,source,
  footer(text){tx('Scope and source',text,60,673,1108,38,17,C.muted,false,'the evaluation scope and source that limit this page’s conclusion');},
  takeaway(text){tx('Takeaway',text,60,600,1160,49,28,C.ink,true,'the conclusion supported by the displayed evidence');},
  notes(zh,en,extra=''){s.speakerNotes.text=`中文讲述逻辑\n${zh}\n\nEnglish speaker script\n${en}\n\nSources\n${source}\n${extra}`;},
  finish(){return {slide:n,title,question,source,elements:log};}};
}

function legend(a,full=false){
 ['D','Fplus','Fminus','VBS'].forEach((k,i)=>{
  const x=110+i*270;a.line('Legend stroke '+k,x,181,x+30,181,C[k],k==='D'?4:2.5,'the curve identity '+NAME[k]);
  a.tx('Legend '+k,full?({D:'D  native default',Fplus:'F+  prefer true',Fminus:'F−  prefer false',VBS:'VBS  best per instance'})[k]:NAME[k],x+40,166,230,34,21,C[k],false,'the meaning of the '+NAME[k]+' curve');
 });
}

function cumulative(a,data,metric,wide=false){
 const plot=data.plots[metric],left=110,top=229,w=wide?1100:plot.width,h=plot.height,ratio=w/plot.width;
 [0,1000,2000,3000,4000].forEach(v=>{
  const y=top+h*(1-v/4000);if(v)a.line('Count grid '+v,left,y,left+w,y,C.line,1,'reading cumulative verified solve counts at '+v);
  a.tx('Count tick '+v,String(v),47,y-13,52,27,20,C.muted,false,'the solved-count axis tick '+v,'right');
 });
 a.line('Count axis',left,top,left,top+h,C.muted,1.5,'the common zero and range of the count axis');
 a.line('Budget axis',left,top+h,left+w,top+h,C.muted,1.5,'the time or conflict budget along the horizontal axis');
 a.tx('Vertical axis definition','Verified instances solved',110,202,650,27,20,C.muted,false,'what each vertical coordinate counts');
 plot.ticks.forEach(t=>{
  a.line('Budget tick '+t.label,left+t.x*ratio,top+h,left+t.x*ratio,top+h+6,C.muted,1,'the horizontal threshold '+t.label);
  a.tx('Budget label '+t.label,t.label,left+t.x*ratio-62,top+h+10,124,27,19,C.muted,false,'the budget value '+t.label,'center');
 });
 // Draw D last to keep the default visible where lines coincide.
 for(const k of ['Fplus','Fminus','VBS','D'])a.path('Cumulative '+metric+' '+k,plot.series[k].points.map(p=>[p[0]*ratio,p[1]]),C[k],k==='D'?3.5:2.5,
   `the exact cumulative ${metric} observations for ${NAME[k]}; supplied ${plot.series[k].solved} verified solves, geometric tolerance below 0.20 slide pixels`,{left,top,width:w,height:h});
 return a;
}


export {author,legend,cumulative,C};

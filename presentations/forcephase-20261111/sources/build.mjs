import fs from 'node:fs/promises';
import path from 'node:path';
import {Presentation,PresentationFile} from '@oai/artifact-tool';
import {refined} from './refined_deck.mjs';
const root=path.dirname(new URL(import.meta.url).pathname);
const data=JSON.parse(await fs.readFile(path.join(root,'deck-data.json'),'utf8'));
const p=Presentation.create({slideSize:{width:1280,height:720}});
const ledger=await refined({presentation:p,input:{data}});
const out=path.join(root,'rebuilt');await fs.mkdir(out,{recursive:true});
await (await PresentationFile.exportPptx(p)).save(path.join(out,'forcephase-results.pptx'));
await fs.writeFile(path.join(out,'element-ledger.json'),JSON.stringify(ledger,null,2));
for(let i=0;i<p.slides.items.length;i++){
 const png=await p.export({format:'png',slide:p.slides.items[i],scale:1});
 await fs.writeFile(path.join(out,'slide-'+String(i+1).padStart(2,'0')+'.png'),new Uint8Array(await png.arrayBuffer()));
}
console.log('Rebuilt',p.slides.items.length,'slides. No new experiments.');

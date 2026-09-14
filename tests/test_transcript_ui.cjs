// Exercise the real export handler without reading the user's system clipboard.
const {test} = require('node:test');
const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const {join} = require('node:path');
const vm = require('node:vm');
const code = readFileSync(join(__dirname, '../frameproof/assets/web/app.js'), 'utf8');
const handler = code.slice(code.indexOf('async function exportTranscript('), code.indexOf("\n$('copy-transcript').addEventListener"));

function context({failCopy=false,failRequest=false,stale=false}={}) {
  const output = {status:'',copied:null,download:null};
  const state = {id:'meeting',request:1,total:205,offset:100,busy:false};
  const status = {set textContent(value){output.status=value;}};
  return {output, state, globals:{
    transcriptState:state, AbortController, setTimeout, clearTimeout, URLSearchParams,
    $:()=>status, transcriptControls:()=>{},
    navigator:{clipboard:{writeText:async text=>{if(failCopy)throw Error('clipboard denied');output.copied=text;}}},
    document:{body:{append:()=>{}}},
    element:()=>({click(){output.download=this.href;},remove(){}}),
    fetch:async url=>{output.url=url;if(stale)state.id='other';return {
      ok:!failRequest,url:'http://127.0.0.1:8769'+url,
      json:async()=>({error:'Read failed'}),
      blob:async()=>({text:async()=>Array.from({length:205},(_,i)=>`Реплика ${i+1}`).join('\n\n')})
    };},
  }};
}

test('copy includes all 205 segments regardless of displayed page',async()=>{
  const c=context();await vm.runInNewContext(handler+"; exportTranscript('txt',true)",c.globals);
  assert.match(c.output.copied,/Реплика 1\n/);assert.match(c.output.copied,/Реплика 205$/);
  assert.match(c.output.status,/Весь текст скопирован/);assert.equal(c.state.busy,false);
});
test('clipboard failure gives download alternative',async()=>{
  const c=context({failCopy:true});await vm.runInNewContext(handler+"; exportTranscript('txt',true)",c.globals);
  assert.equal(c.output.copied,null);assert.match(c.output.status,/Можно скачать TXT/);
});
test('late export does not copy text of a previous meeting',async()=>{
  const c=context({stale:true});await vm.runInNewContext(handler+"; exportTranscript('txt',true)",c.globals);
  assert.equal(c.output.copied,null);assert.equal(c.output.download,null);
});
test('server error is inline and never triggers download',async()=>{
  const c=context({failRequest:true});await vm.runInNewContext(handler+"; exportTranscript('txt')",c.globals);
  assert.equal(c.output.download,null);assert.match(c.output.status,/Read failed/);
});
for(const format of ['txt','md','srt'])test(`native attachment download: ${format}`,async()=>{
  const c=context();await vm.runInNewContext(handler+`; exportTranscript('${format}')`,c.globals);
  assert.match(c.output.download,new RegExp(`format=${format}$`));assert.equal(c.output.copied,null);
});

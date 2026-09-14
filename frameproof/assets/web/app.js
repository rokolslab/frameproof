'use strict';
const $ = id => document.getElementById(id);
const state = {token:'', index:null, job:null, externalTitle:'', request:0, limit:20, composing:false, timer:null, upload:null, busy:false, stopped:false, folder:'', parent:'', offset:0, picker:null, copySelected:new Set()};
const labels = {running:'Обработка выполняется',done:'Готово',error:'Ошибка обработки',cancelled:'Остановлено',cancelling:'Остановка процессов…',interrupted:'Прервано при завершении хоста'};
function element(tag, text, className) { const node=document.createElement(tag); if(text!==undefined)node.textContent=text; if(className)node.className=className; return node; }
function button(text, action) { const node=element('button',text);node.type='button';node.addEventListener('click',()=>run(action));return node; }
function status(text) { $('status').textContent=text; }
function configureOcr(ocr) {
  if (!ocr?.options?.length) return;
  const select=$('ocr');
  select.replaceChildren(...ocr.options.map(option=>{
    const node=element('option',option.label);node.value=option.id;return node;
  }));
  select.value=ocr.default;
  select.disabled=false;
}
async function run(action) {try {await action();} catch(error){status(error.message);}}
async function api(path, body, signal, timeoutMs=20000) {
  const controller = new AbortController();
  const timeout=setTimeout(()=>controller.abort(),timeoutMs);
  const abort=()=>controller.abort();signal?.addEventListener('abort',abort,{once:true});
  try {
    const response=await fetch(path,{method:body===undefined?'GET':'POST',headers:body===undefined?{}:{'Content-Type':'application/json','X-Frameproof-Token':state.token},body:body===undefined?undefined:JSON.stringify(body),signal:controller.signal});
    const data=await response.json();if(!response.ok)throw Error(data.error||'Запрос не выполнен.');return data;
  } catch(error){if(error.name==='AbortError')throw Error('Запрос отменён или хост не отвечает. Повтори действие.');throw error;}
  finally{clearTimeout(timeout);signal?.removeEventListener('abort',abort);}
}
function page(name) {document.querySelectorAll('.page').forEach(p=>p.hidden=p.id!==name);document.querySelectorAll('[data-page]').forEach(b=>b.setAttribute('aria-current',b.dataset.page===name?'page':'false'));document.title=`${{create:'Новое видео',library:'Обработки',setup:'Готовность'}[name]} — Frameproof`;if(name==='setup')run(checkSetup);if(name==='library')run(refreshJobs);}
document.querySelectorAll('[data-page]').forEach(b=>b.addEventListener('click',()=>page(b.dataset.page)));
$('source').addEventListener('change',()=>{for(const kind of ['upload','host','url'])$(kind+'-source').hidden=$('source').value!==kind;});
$('speech-engine').addEventListener('change',()=>{$('speech-model').disabled=$('speech-engine').value==='mlx';});
for(const id of ['video-file','host-path','url'])$(id).addEventListener('input',()=>{$(id).removeAttribute('aria-invalid');$('source-error').textContent='';});
$('preset').addEventListener('change',()=>{const p=$('preset').value;if(p==='custom')return;$('max-gap').value=p==='detail'?5:15;$('fast').checked=p==='fast';});
for(const id of ['max-gap','max-frames','width','max-height','ocr-width','fast','no-cues'])$(id).addEventListener('change',()=>$('preset').value='custom');
function confirmation(text,verb,action){const dialog=$('confirm-dialog'),focus=document.activeElement;$('confirm-text').textContent=text;$('confirm-yes').textContent=verb;$('confirm-yes').onclick=()=>{dialog.close();run(action);};dialog.addEventListener('close',()=>focus?.focus(),{once:true});dialog.showModal();$('confirm-no').focus();}
$('confirm-no').addEventListener('click',()=>$('confirm-dialog').close());
$('shutdown').addEventListener('click',()=>confirmation('Приложение перестанет отвечать в браузере. Сохранённые результаты останутся на хосте. Активную обработку сначала нужно остановить.','Завершить',async()=>{await api('/api/shutdown',{});state.stopped=true;status('Приложение завершено. Для новой работы запусти его на хосте.');document.querySelectorAll('button,input,select').forEach(n=>n.disabled=true);}));
$('cancel-job').addEventListener('click',()=>confirmation('Текущая обработка будет остановлена вместе с дочерними процессами. Частичный результат не считается готовым.','Остановить',async()=>{await api('/api/cancel',{});await refreshJobs();}));
function clearDeletedJob(id){
  if(state.job!==id)return;
  resultSequence++;state.request++;frameSequence++;searchAbort?.abort();
  state.job=null;state.index=null;transcriptJobState='';transcriptState.id=null;transcriptState.request++;
  $('job-detail').hidden=true;$('transcript').hidden=true;$('result').hidden=true;
}
function deleteJob(job){
  confirmation(`Удалить обработку «${job.title}»? Будут безвозвратно удалены её индекс, расшифровка, кадры и журнал на хосте. Исходное видео не удаляется.`, 'Удалить обработку', async()=>{
    await api('/api/delete-job',{id:job.id});clearDeletedJob(job.id);jobsSnapshot='';await refreshJobs();$('index-path').focus();status('Обработка удалена с хоста. Исходное видео осталось без изменений.');
  });
}
function updateCopySelection(){const count=state.copySelected.size;$('copy-selection').textContent=`Выбрано: ${count}`;$('copy-selected').disabled=count===0;}
function chooseCopyDestination(){if(!state.copySelected.size)return;picker('copy-destination');}
async function copySelected(destination){const data=await api('/api/copy-indexes',{ids:[...state.copySelected],destination});state.copySelected.clear();updateCopySelection();await refreshJobs();status(`Скопировано обработок: ${data.copied.length}. Папка назначения: ${destination}`);}
async function checkSetup(){
  const data=await api('/api/readiness'),gpu=data.gpu||{};configureOcr(data.ocr);$('environment').textContent=`${data.system} ${data.machine} · Python ${data.python} · ${data.isolated?'Изолированное окружение':'Системный Python — рекомендуется .venv'} · ${data.environment}`;
  const gpuText=gpu.nvidia_detected?(gpu.cuda_available?`CUDA готова: ${gpu.device_name||'NVIDIA GPU'}${gpu.memory_total_mb?`, ${gpu.memory_total_mb} МБ VRAM`:''}. Whisper будет использовать GPU.`:`NVIDIA GPU обнаружена, но CUDA недоступна. Распознавание речи заблокировано до установки CUDA PyTorch. ${gpu.detail||''}`):'NVIDIA GPU на хосте не обнаружена. Whisper может использовать CPU.';
  $('gpu').textContent=gpuText;$('gpu-runtime').textContent=gpuText;
  $('dependencies').replaceChildren(...data.items.map(item=>{
    const ready=item.ready??item.installed,box=element('article',undefined,'card dependency'+(ready?'':' missing'));
    box.append(element('h2',item.name),element('p',ready?'Готов':item.installed?'Установлен, требуется настройка':'Не установлен'),element('p',item.detail||item.purpose));
    if(item.command){box.append(element('code',item.command),button('Копировать команду',async()=>{await navigator.clipboard.writeText(item.command);status('Команда скопирована. Выполни её на хосте приложения.');}));}
    if(!ready&&item.can_install){const install=button(item.installed?'Настроить':'Установить',()=>confirmation(`Установить и настроить ${item.name} на ${$('host').textContent}? Будут загружены пакеты, приняты их лицензии и дополнен пользовательский PATH. Установка тихая; UAC при необходимости появится на хосте. Дождись завершения, не закрывай приложение.`,'Установить',()=>startInstall(item.id)));install.dataset.install=item.id;box.append(install);}
    const link=element('a','Официальная инструкция');link.href=item.url;link.target='_blank';link.rel='noopener noreferrer';box.append(element('p'),link);return box;
  }));
  await refreshInstall();
}
let installSnapshot='',installPending=false,installRequest=null;
async function startInstall(component){
  if(installPending)return;
  installPending=true;
  const label=component==='whisper'?'Настраиваем Whisper: заменяем CPU PyTorch на CUDA 12.8 и проверяем GPU. Это может занять несколько минут.':'Устанавливаем компонент…';
  $('install-state').textContent=label;status(label);
  installRequest={component,request_id:crypto.randomUUID(),confirmed:true};
  try{await api('/api/install',installRequest);installRequest=null;await refreshInstall();}
  catch(error){$('install-state').textContent=error.message+' Если связь прервалась, нажми «Проверить повторно» перед новой попыткой.';}
  finally{installPending=false;}
}
async function refreshInstall(){
  const job=await api('/api/install'),running=job.state==='running';
  $('install-state').textContent=job.message||'Установки не выполняются.';
  if(job.state==='error')status(job.message||'Установка завершилась ошибкой. Открой журнал установки.');
  $('install-state').setAttribute('aria-busy',String(running));
  $('install-log').textContent=job.log||'Журнал появится после начала установки.';
  document.querySelectorAll('[data-install]').forEach(b=>b.disabled=running||installPending);
  const signature=JSON.stringify([job.request_id,job.state]);
  if(signature!==installSnapshot){const previous=installSnapshot;installSnapshot=signature;if(previous&&['done','error'].includes(job.state))await checkSetup();}
}
$('refresh-setup').addEventListener('click',()=>run(checkSetup));
async function browse(path='',offset=0){
  $('files-error').textContent='';try{const data=await api('/api/browse?'+new URLSearchParams({path,offset}));state.folder=data.path;state.parent=data.parent;state.offset=offset;$('folder').textContent=data.path||'Разрешённые папки хоста';$('choose-folder').hidden=!['index-path','copy-destination'].includes(state.picker)||!data.path;$('more-files').hidden=!data.more;
    $('files').replaceChildren(...data.entries.map(entry=>button((entry.directory?'Папка: ':'Файл: ')+entry.name,async()=>{if(entry.directory){await browse(entry.path);return;}if(state.picker==='index-path')return;$(state.picker).value=entry.path;$('files-dialog').close();})));
    if(!data.entries.length)$('files').append(element('p','Нет доступных файлов. Добавь папку при запуске: --media-root "путь".'));
  }catch(error){$('files-error').textContent=error.message;}
}
function picker(field){state.picker=field;$('files-dialog').showModal();run(()=>browse());}
$('browse-video').addEventListener('click',()=>picker('host-path'));$('browse-subs').addEventListener('click',()=>picker('subs-path'));$('browse-index').addEventListener('click',()=>run(async()=>{status('Откройте папку в системном окне на хосте…');const selected=await api('/api/pick-index-folder',{},undefined,310000);if(selected.cancelled){status('Выбор папки отменён.');return;}$('index-path').value=selected.path;$('index-path').dataset.selection=selected.selection;$('index-path').dataset.title=selected.title;status(`Выбрана папка: ${selected.path}`);}));
$('copy-selected').addEventListener('click',()=>chooseCopyDestination());$('close-files').addEventListener('click',()=>$('files-dialog').close());$('folder-up').addEventListener('click',()=>run(()=>browse(state.parent)));$('more-files').addEventListener('click',()=>run(()=>browse(state.folder,state.offset+100)));$('choose-folder').addEventListener('click',()=>{const destination=state.folder;if(state.picker==='copy-destination'){confirmation(`Скопировать выбранные обработки (${state.copySelected.size}) в «${destination}»? Существующие папки не будут перезаписаны.`, 'Скопировать', async()=>{await copySelected(destination);});}else $('index-path').value=destination;$('files-dialog').close();});
function upload(file){
  if(!file||file.size===0)throw Error('Выбери непустой файл.');if(file.size>20*1024**3)throw Error('Максимальный размер файла — 20 ГиБ.');
  return new Promise((resolve,reject)=>{const xhr=new XMLHttpRequest();state.upload=xhr;$('abort-upload').hidden=false;$('upload-progress').hidden=false;$('upload-progress').value=0;xhr.open('POST','/api/upload?'+new URLSearchParams({name:file.name}));xhr.setRequestHeader('X-Frameproof-Token',state.token);xhr.upload.onprogress=e=>{if(e.lengthComputable){$('upload-progress').value=Math.round(e.loaded/e.total*100);$('upload-state').textContent=`${file.name}: ${$('upload-progress').value}%`;}};xhr.onload=()=>{try{const data=JSON.parse(xhr.responseText);if(xhr.status>=400)reject(Error(data.error));else resolve(data);}catch{reject(Error('Хост вернул неверный ответ.'));}};xhr.onerror=()=>reject(Error('Не удалось загрузить файл. Проверь соединение и повтори.'));xhr.onabort=()=>reject(Error('Загрузка отменена.'));xhr.onloadend=()=>{state.upload=null;$('abort-upload').hidden=true;};xhr.send(file);});
}
$('abort-upload').addEventListener('click',()=>state.upload?.abort());
$('create-form').addEventListener('submit',async event=>{
  event.preventDefault();if(state.busy)return;$('form-error').textContent='';$('source-error').textContent='';
  const source=$('source').value, target=source==='host'?$('host-path').value:source==='url'?$('url').value:'';
  if((source==='upload'&&!$('video-file').files.length)||(source!=='upload'&&!target.trim())){$('source-error').textContent='Выбери видео или введи ссылку.';const field=$(source==='upload'?'video-file':source==='host'?'host-path':'url');field.setAttribute('aria-invalid','true');field.setAttribute('aria-describedby','source-error');field.focus();return;}
  if($('subs-file').files.length&&$('subs-path').value){$('form-error').textContent='Выбери один источник субтитров.';return;}
  const body={source,target,name:$('video-name').value,subs:$('subs-path').value,speech:$('speech').value,lang:$('lang').value,ocr:$('ocr').value,fast:$('fast').checked,no_cues:$('no-cues').checked};
  body.speech_engine=$('speech-engine').value;body.speech_model=$('speech-model').value;
  for(const id of ['max-gap','max-frames','width','max-height','ocr-width']){const input=$(id),value=Number(input.value);if(!input.value||!Number.isFinite(value)||value<Number(input.min)||value>Number(input.max)){$('form-error').textContent=`Проверь параметр: ${input.closest('label').firstChild.textContent}`;input.closest('details').open=true;input.focus();return;}body[id.replaceAll('-','_')]=value;}
  state.busy=true;$('start').disabled=true;
  try{await api('/api/preflight',{...body,upload_subs:Boolean($('subs-file').files.length)});if(source==='upload'){const sent=await upload($('video-file').files[0]);body.target=sent.path;if(!body.name)body.name=sent.name;}if($('subs-file').files.length)body.subs=(await upload($('subs-file').files[0])).path;const job=await api('/api/index',body);state.job=job.id;status('Обработка запущена. Вкладку можно закрыть.');page('library');await selectJob(job.id);}
  catch(error){$('form-error').textContent=error.message;}
  finally{state.busy=false;$('start').disabled=false;$('abort-upload').hidden=true;$('upload-progress').hidden=true;}
});
let jobsSnapshot='',transcriptJobState='',resultSequence=0;
const transcriptState={id:null,offset:0,total:0,request:0,busy:false};
function transcriptControls(enabled){$('copy-transcript').disabled=!enabled;document.querySelectorAll('[data-transcript-format]').forEach(b=>b.disabled=!enabled);}
function resetTranscript(id){transcriptState.id=id;transcriptState.request++;transcriptState.offset=0;transcriptState.total=0;transcriptState.busy=false;$('transcript').hidden=false;$('transcript-reader').replaceChildren();$('transcript-saved').textContent='';$('transcript-status').textContent='Загружаем сохранённый текст…';$('transcript-pages').hidden=true;$('retry-transcript').hidden=true;transcriptControls(false);}
async function loadTranscript(id,offset=0){
  const seq=++transcriptState.request;transcriptState.busy=true;$('transcript-reader').setAttribute('aria-busy','true');$('transcript-status').textContent='Загружаем сохранённый текст…';$('retry-transcript').hidden=true;$('transcript-prev').disabled=true;$('transcript-next').disabled=true;transcriptControls(false);
  try{
    const data=await api('/api/transcript?'+new URLSearchParams({id,offset}));if(seq!==transcriptState.request||id!==transcriptState.id)return;
    transcriptState.offset=data.offset;transcriptState.total=data.total;
    $('transcript-saved').textContent=data.saved?`Текст автоматически сохранён на хосте: ${data.folder}. Закрытие вкладки или приложения его не удаляет.`:'Текст пока не сохранён: распознанных реплик нет.';
    $('transcript-reader').replaceChildren(...data.rows.map(row=>{const section=element('article',undefined,'transcript-segment');section.append(element('span',row.tc,'transcript-time'),element('p',row.text));return section;}));
    $('transcript-status').textContent=data.total?'Текст доступен для чтения. Копирование и скачивание включают все реплики, не только текущую страницу.':'Распознанного текста пока нет. Если обработка идёт, дождись её завершения. Если завершена — проверь журнал, включи распознавание речи или добавь субтитры и запусти новую обработку.';
    $('transcript-pages').hidden=data.total<=100;$('transcript-range').textContent=`Реплики ${data.offset+1}–${data.offset+data.rows.length} из ${data.total}`;
    $('transcript-prev').disabled=data.offset===0;$('transcript-next').disabled=data.offset+data.rows.length>=data.total;transcriptControls(data.total>0);
  }catch(error){if(seq!==transcriptState.request)return;$('transcript-status').textContent=`Не удалось загрузить текст. ${error.message}`;$('retry-transcript').hidden=false;$('retry-transcript').disabled=false;}
  finally{if(seq===transcriptState.request){transcriptState.busy=false;$('transcript-reader').setAttribute('aria-busy','false');}}
}
$('retry-transcript').addEventListener('click',()=>run(()=>loadTranscript(transcriptState.id,transcriptState.offset)));
for(const [id,delta] of [['transcript-prev',-100],['transcript-next',100]])$(id).addEventListener('click',()=>run(async()=>{await loadTranscript(transcriptState.id,Math.max(0,transcriptState.offset+delta));$('transcript-title').focus();}));
async function exportTranscript(format,copy=false){
  if(transcriptState.busy||!transcriptState.total)return;
  const id=transcriptState.id,seq=transcriptState.request,controller=new AbortController(),timer=setTimeout(()=>controller.abort(),20000);transcriptState.busy=true;transcriptControls(false);$('transcript-status').textContent=copy?'Подготавливаем весь текст для копирования…':'Подготавливаем файл…';
  try{
    const response=await fetch('/api/transcript?'+new URLSearchParams({id,format}),{signal:controller.signal});if(!response.ok){const data=await response.json();throw Error(data.error||'Не удалось получить текст.');}
    const blob=await response.blob();if(id!==transcriptState.id||seq!==transcriptState.request)return;
    if(copy){await navigator.clipboard.writeText(await blob.text());$('transcript-status').textContent='Весь текст скопирован. Можно вставить в документ или передать агенту.';}
    else{const link=element('a');link.href=response.url;link.download=`transcript.${format}`;document.body.append(link);link.click();link.remove();$('transcript-status').textContent='Файл передан браузеру для скачивания. Исходный результат остаётся на хосте.';}
  }catch(error){if(id===transcriptState.id&&seq===transcriptState.request)$('transcript-status').textContent=(copy?'Не удалось скопировать. Можно скачать TXT. ':'Не удалось скачать. Повтори попытку. ')+(error.name==='AbortError'?'Хост не ответил вовремя.':error.message);}
  finally{clearTimeout(timer);if(id===transcriptState.id&&seq===transcriptState.request){transcriptState.busy=false;transcriptControls(transcriptState.total>0);}}
}
$('copy-transcript').addEventListener('click',()=>run(()=>exportTranscript('txt',true)));
document.querySelectorAll('[data-transcript-format]').forEach(b=>b.addEventListener('click',()=>run(()=>exportTranscript(b.dataset.transcriptFormat))));
function renderJobProgress(job){
  const progress=job.progress||{stage:'Подготовка',percent:null},bar=$('job-progress');
  const running=job.state==='running'||job.state==='cancelling';
  bar.hidden=!running&&job.state!=='done';
  if(progress.percent===null)bar.removeAttribute('value');else bar.value=progress.percent;
  bar.setAttribute('aria-busy',String(running));
  $('job-stage').textContent=progress.stage+(progress.percent===null?'':` — ${progress.percent}%`);
}
async function refreshJobs(){
  if(state.stopped)return;const jobs=await api('/api/jobs'),snapshot=JSON.stringify(jobs);
  if(snapshot!==jobsSnapshot){jobsSnapshot=snapshot;state.copySelected=new Set([...state.copySelected].filter(id=>jobs.some(j=>j.id===id&&j.state==='done')));$('jobs').replaceChildren(...jobs.map(j=>{const box=element('article',undefined,'card'),actions=element('div',undefined,'row');if(j.state==='done'){const select=element('input');select.type='checkbox';select.checked=state.copySelected.has(j.id);select.setAttribute('aria-label',`Выбрать обработку «${j.title}» для копирования`);select.addEventListener('change',()=>{select.checked?state.copySelected.add(j.id):state.copySelected.delete(j.id);updateCopySelection();});actions.append(select,element('span','Выбрать для копирования'));}actions.append(button('Открыть обработку',()=>selectJob(j.id)));const remove=button('Удалить обработку',()=>deleteJob(j));remove.className='danger';remove.disabled=['running','cancelling'].includes(j.state);actions.append(remove);box.append(element('h2',j.title),element('p',`${labels[j.state]||j.state} · ${new Date(j.created*1000).toLocaleString('ru-RU')}`),actions);return box;}));if(!jobs.length)$('jobs').append(element('p','Пока нет обработок. Добавь первое видео.'));updateCopySelection();}
  if(state.job){
    const selected=state.job,j=await api('/api/job?'+new URLSearchParams({id:selected}));if(state.job!==selected)return;
    $('job-title').textContent=j.title;$('job-state').textContent=labels[j.state]||j.state;renderJobProgress(j);const speed=j.transcription_speed;$('transcription-speed').textContent=speed?`Средняя скорость распознавания: ${Number(speed.realtime_factor).toLocaleString('ru-RU',{maximumFractionDigits:2})}× реального времени. ${Math.round(speed.audio_seconds||0)} с аудио за ${Math.round(speed.elapsed_seconds||0)} с, включая загрузку модели.`:'';$('resources').textContent=`${j.resources}. Вычисления: ${j.compute?.actual||'не определены'}${j.compute?.requested?` (запрошено: ${j.compute.requested})`:''}.`;$('job-log').textContent=j.log||'Ожидаем вывод процесса…';$('cancel-job').disabled=!['running','cancelling'].includes(j.state);
    const signature=j.id+':'+j.state;
    if(transcriptJobState!==signature){transcriptJobState=signature;await loadTranscript(j.id);}
    if(state.job===selected&&j.state==='done'&&state.index!==j.id)await openResult(j.id);
  }
}
async function selectJob(id){resultSequence++;state.request++;frameSequence++;state.job=id;$('job-detail').hidden=false;$('result').hidden=true;state.index=null;transcriptJobState='';resetTranscript(id);await refreshJobs();if(state.job===id)$('transcript-title').focus();}
async function openResult(id){
  const sequence=++resultSequence;
  frameSequence++;
  const report=await api('/api/report?'+new URLSearchParams({id}));if(sequence!==resultSequence)return;state.index=id;state.request++;$('result').hidden=false;$('result-title').textContent=report.video.title;$('coverage').textContent=`Покрытие: ${Math.round(report.coverage.ratio*100)}%. Максимальный разрыв: ${report.coverage.actual_max_gap_sec} с. Кадров: ${report.frames.count}. Реплик: ${report.transcript.segment_count}.`;$('gaps').replaceChildren(...report.coverage.gaps.map(g=>element('li',`Без гарантии кадров: ${g.tc}`)));$('frames').replaceChildren();$('hits').replaceChildren();$('query').value='';$('verification').replaceChildren();$('search-state').textContent='Введи запрос или открой кадры по времени.';if(!report.transcript.segment_count)status('В индексе нет речи. Поиск по речи недоступен; кадры можно открыть по времени.');
  $('result-title').textContent=state.job===id?$('job-title').textContent:(state.externalTitle||report.video.title.split(/[\\/]/).pop());
  $('claims').value='';
  if(report.transcript.segment_count)status('Индекс видео готов. Расшифровка и поиск показаны ниже.');
}
$('open-index').addEventListener('click',()=>run(async()=>{const sequence=++resultSequence,field=$('index-path'),body=field.dataset.selection?{selection:field.dataset.selection}:{path:field.value},result=await api('/api/open',body);delete field.dataset.selection;state.externalTitle=result.title||field.dataset.title||'';if(sequence!==resultSequence)return;state.job=null;state.request++;$('job-detail').hidden=true;resetTranscript(result.id);await loadTranscript(result.id);if(transcriptState.id!==result.id)return;await openResult(result.id);if(transcriptState.id===result.id){$('transcript-title').focus();status('Готовый индекс открыт.');}}));
let searchAbort;
async function search(){
  clearTimeout(state.timer);searchAbort?.abort();const seq=++state.request,query=$('query').value.trim();$('more-hits').hidden=true;if(!query){$('hits').replaceChildren();$('search-state').textContent='Введи запрос.';return;}if(!state.index)return;searchAbort=new AbortController();$('search-state').textContent='Ищем…';
  try{const data=await api('/api/search?'+new URLSearchParams({id:state.index,q:query,limit:state.limit}),undefined,searchAbort.signal);if(seq!==state.request)return;$('hits').replaceChildren(...data.hits.map(h=>{const row=element('article',undefined,'hit');row.append(element('p',`${h.kind==='speech'?'Речь':'Текст на экране'} · ${h.ref} · ${tc(h.t)}`,'meta'),element('p',h.text),button('Открыть кадры рядом',()=>frames(h.t)));return row;}));$('search-state').textContent=data.hits.length?`Показано совпадений: ${data.hits.length}${data.more?' — есть ещё':''}. ${data.gaps.length?'Рядом есть зоны без кадров: '+data.gaps.map(g=>g.tc).join(', '):''}`:'Совпадений нет. Попробуй другое слово.';$('more-hits').hidden=!data.more||state.limit>=200;
  }catch(error){if(seq===state.request)$('search-state').textContent=error.message;}
}
function tc(t){const s=Math.round(t);return `${Math.floor(s/60)}:${String(s%60).padStart(2,'0')}`;}
$('query').addEventListener('compositionstart',()=>{state.composing=true;clearTimeout(state.timer);searchAbort?.abort();state.request++;});$('query').addEventListener('compositionend',()=>{state.composing=false;state.timer=setTimeout(search,300);});$('query').addEventListener('input',()=>{clearTimeout(state.timer);searchAbort?.abort();state.request++;state.limit=20;if(!state.composing)state.timer=setTimeout(search,300);});$('query').addEventListener('keydown',e=>{if(e.key==='Enter'&&!e.isComposing&&!state.composing){e.preventDefault();run(search);}});$('clear').addEventListener('click',()=>{$('query').value='';$('query').focus();run(search);});$('more-hits').addEventListener('click',()=>{state.limit+=20;run(search);});
let frameSequence=0;
async function frames(at){if(!state.index)return;const seq=++frameSequence,id=state.index;const data=await api('/api/frames?'+new URLSearchParams({id,at,count:3}));if(seq!==frameSequence||id!==state.index)return;$('frames').replaceChildren(...data.map(f=>{const figure=element('figure'),image=element('img');image.alt=`Кадр ${f.id}, ${tc(f.t)}`;image.src='/frame?'+new URLSearchParams({id,frame:f.id});image.addEventListener('error',()=>status(`Не удалось открыть ${f.id}. Повтори запрос кадров.`));const citation=`[${tc(f.t)} / ${f.id}]`;figure.append(image,element('figcaption',citation),button('Копировать ссылку на кадр',async()=>{await navigator.clipboard.writeText(citation);status('Метка кадра скопирована.');}));return figure;}));if(!data.length)$('frames').append(element('p','Кадров нет.'));}
$('frames-form').addEventListener('submit',e=>{e.preventDefault();run(()=>frames($('at').value));});
$('verify').addEventListener('click',()=>run(async()=>{const data=await api('/api/verify',{id:state.index,text:$('claims').value});$('verification').replaceChildren(...data.map(c=>element('p',`${c.severity}: ${c.text} ${c.findings.map(f=>f.detail).join('; ')}`)));if(!data.length)$('verification').append(element('p','Метки кадров не найдены. Используй формат [MM:SS / fNNNN].'));}));
async function poll(){if(state.stopped)return;try{if(state.job||!$('library').hidden)await refreshJobs();if(!$('setup').hidden)await refreshInstall();}catch(error){status('Связь с хостом потеряна. Проверяем повторно… '+error.message);}finally{if(!state.stopped)setTimeout(poll,2000);}}
run(async()=>{const session=await api('/api/session');state.token=session.token;document.querySelectorAll('button[disabled]').forEach(b=>b.disabled=false);$('cancel-job').disabled=true;$('host').textContent=`Хост: ${session.hostname}`;$('storage').textContent=`Загрузки и результаты: ${session.data}`;status('Модели загружаются только во время обработки.');await checkSetup();poll();});

const $=id=>document.getElementById(id);
let connected=false;
async function api(url,opts={method:'POST'}){
  const r=await fetch(url,opts);
  if(!r.ok){let msg='Не удалось выполнить действие.';try{msg=(await r.json()).detail||msg}catch{}throw Error(msg)}
  return r.json();
}
function error(e){$('error').hidden=false;$('error').textContent=e.message||String(e)}
$('file').onchange=async e=>{
  const file=e.target.files[0];if(!file)return;
  $('uploadLabel').classList.add('busy');$('error').hidden=true;
  try{
    const data=new FormData();data.append('file',file);
    await api('/api/upload',{method:'POST',body:data});
    $('stream').src='/api/stream?'+Date.now();connected=true;
  }catch(err){error(err)}finally{$('uploadLabel').classList.remove('busy');$('file').value='';refresh()}
};
$('modelDownload').onclick=async()=>{try{await api('/api/model/download')}catch(e){error(e)}refresh()};
$('modelCheck').onclick=async()=>{try{await api('/api/model/check')}catch(e){error(e)}refresh()};
async function refresh(){
  try{
    const response=await fetch('/api/status',{cache:'no-store'});
    if(!response.ok)throw Error('Нет связи с программой.');
    const d=await response.json(),m=d.model,s=d.state,v=d.video;
    $('modelBox').hidden=m.ready || (!m.downloading && !m.status.startsWith('Модель недоступна:') && !m.status.startsWith('Ошибка загрузки модели:'));
    $('modelStatus').textContent=m.status;
    $('modelDownload').disabled=m.downloading||s.running;
    $('modelCheck').disabled=m.downloading||s.running;
    $('downloadProgress').textContent=m.downloading&&m.bytes?`${(m.bytes/1048576).toFixed(1)} из ${(d.model_size/1048576).toFixed(1)} МБ · ${(100*m.bytes/d.model_size).toFixed(1)}%`:'';
    $('resultSection').hidden=!v;
    if(v&&!connected){$('stream').src='/api/stream?'+Date.now();connected=true}
    if(!v)connected=false;
    const note=$('processingStatus');
    if(v && s.pending){note.hidden=false;note.textContent='Ожидаем готовности модели…'}
    else if(v && s.running && s.frame===0){note.hidden=false;note.textContent='Идёт поиск нор… На компьютере без видеокарты это может занять некоторое время.'}
    else if(v && !s.running && s.status==='Обработка завершена.' && s.maximum===0){note.hidden=false;note.textContent='Обработка завершена: норы не найдены.'}
    else {note.hidden=true;note.textContent=''}
    if(s.status.startsWith('Ошибка обработки:')) error(new Error(s.status));
  }catch(e){$('modelBox').hidden=false;$('modelStatus').textContent='Нет связи с программой. Проверьте окно запуска.'}
}
setInterval(refresh,700);refresh();

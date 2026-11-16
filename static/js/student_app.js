const tg=window.Telegram?.WebApp;
const maxApp=window.WebApp;
const vkParams=new URLSearchParams(window.location.search);
const vkSignedLaunch=vkParams.has('vk_user_id')&&vkParams.has('sign')?vkParams.toString():'';
const maxFragment=new URLSearchParams(window.location.hash.slice(1));
const maxSignedLaunch=maxApp?.initData||maxFragment.get('WebAppData')||'';

// Select responsive behavior by real viewport and browser capabilities, never by
// marketing model names. This works consistently across iPhone, iPad, Android,
// foldables, split-screen windows and messenger-hosted WebViews.
function configureStudentDeviceProfile(){
 const root=document.documentElement,body=document.body,ua=navigator.userAgent||'';
 if(!root||!body)return;
 const media=query=>{try{return Boolean(window.matchMedia&&window.matchMedia(query).matches)}catch(_){return false}};
 const touch=Boolean((navigator.maxTouchPoints||0)>0||media('(pointer: coarse)')||/Android|iPhone|iPad|iPod/i.test(ua));
 // iPadOS can advertise itself as macOS while retaining a multi-touch screen.
 const ipadOSDesktop=navigator.platform==='MacIntel'&&(navigator.maxTouchPoints||0)>1;
 const ios=/iPad|iPhone|iPod/i.test(ua)||ipadOSDesktop;
 const android=/Android/i.test(ua);
 const width=window.visualViewport?.width||window.innerWidth||root.clientWidth||0;
 const tablet=ipadOSDesktop||/iPad|Tablet/i.test(ua)||(android&&!/Mobile/i.test(ua))||(touch&&width>=700&&width<=1366);
 const iosBrowser=/CriOS|FxiOS|EdgiOS|OPiOS|Safari/i.test(ua);
 const iosEmbedded=ios&&!iosBrowser;
 const androidWebView=android&&(/;\s*wv\)/i.test(ua)||/Android.*Version\/[\d.]+.*Chrome\/[\d.]+.*Mobile Safari/i.test(ua));
 const runtime=tg?'telegram':maxApp?'max':androidWebView||iosEmbedded?'webview':'browser';
 const engine=/Gecko\//.test(ua)&&!/like Gecko/i.test(ua)?'gecko':/AppleWebKit\//.test(ua)&&(/iPhone|iPad|iPod|Macintosh/.test(ua))?'webkit':/AppleWebKit\//.test(ua)?'blink':'other';
 body.dataset.deviceFamily=ios?'ios':android?'android':'other';
 body.dataset.formFactor=tablet?'tablet':touch?'handset':'desktop';
 body.dataset.runtime=runtime;
 body.dataset.engine=engine;
 root.classList.toggle('student-capability-touch',touch);
 root.classList.toggle('student-capability-safe-area',Boolean(window.CSS?.supports?.('padding: env(safe-area-inset-top)')));
 root.classList.toggle('student-capability-dynamic-viewport',Boolean(window.CSS?.supports?.('height: 100dvh')));
 root.classList.toggle('student-capability-visual-viewport',Boolean(window.visualViewport));

 const viewport=window.visualViewport||null;
 const requestFrame=window.requestAnimationFrame?window.requestAnimationFrame.bind(window):callback=>window.setTimeout(callback,16);
 let scheduledFrame=0,editableFocus=false,focusBaseline=0,focusScrollDone=false;
 const isEditable=element=>Boolean(element&&element.matches&&element.matches('input:not([type="button"]):not([type="submit"]):not([type="checkbox"]):not([type="radio"]),textarea,select,[contenteditable="true"]'));
 const syncViewportNow=()=>{
  const layoutHeight=Math.round(window.innerHeight||root.clientHeight||0);
  const visualHeight=Math.round(viewport?.height||layoutHeight);
  const visualWidth=Math.round(viewport?.width||window.innerWidth||root.clientWidth||0);
  const offsetTop=Number(viewport?.offsetTop||0);
  if(visualHeight>0)root.style.setProperty('--student-visual-viewport-height',`${visualHeight}px`);
  if(visualWidth>0)root.style.setProperty('--student-visual-viewport-width',`${visualWidth}px`);
  root.style.setProperty('--student-visual-viewport-offset-top',`${Math.round(offsetTop)}px`);
  const active=document.activeElement;
  const editing=editableFocus&&isEditable(active);
  if(!editing)focusBaseline=0;
  const baseline=focusBaseline||Math.max(layoutHeight,visualHeight);
  const keyboardDelta=Math.max(0,baseline-layoutHeight,baseline-visualHeight);
  const keyboardOpen=Boolean(editing&&keyboardDelta>Math.max(110,baseline*.16));
  body.classList.toggle('student-keyboard-open',keyboardOpen);
  const responsiveWidth=visualWidth||layoutHeight;
  body.dataset.viewportProfile=responsiveWidth<360?'compact':responsiveWidth<760?'phone':responsiveWidth<1024?'tablet':'wide';
  body.dataset.orientation=media('(orientation: landscape)')?'landscape':'portrait';
  if(keyboardOpen&&!focusScrollDone&&active&&active.scrollIntoView){
   focusScrollDone=true;
   requestFrame(()=>{
    try{
     const rect=active.getBoundingClientRect();
     const visibleBottom=(viewport?.height||window.innerHeight)+Number(viewport?.offsetTop||0);
     if(rect.bottom>visibleBottom-16)active.scrollIntoView({block:'nearest',behavior:'auto'});
    }catch(_){/* Scrolling is an enhancement; form interaction remains available. */}
   });
  }
  if(!editing)focusScrollDone=false;
 };
 const scheduleViewportSync=()=>{
  if(scheduledFrame)return;
  scheduledFrame=requestFrame(()=>{scheduledFrame=0;syncViewportNow()});
 };
 syncViewportNow();
 window.addEventListener('resize',scheduleViewportSync,{passive:true});
 window.addEventListener('orientationchange',()=>{
  focusBaseline=0;
  scheduleViewportSync();
 },{passive:true});
 window.addEventListener('pageshow',scheduleViewportSync,{passive:true});
 viewport?.addEventListener('resize',scheduleViewportSync,{passive:true});
 viewport?.addEventListener('scroll',scheduleViewportSync,{passive:true});
 document.addEventListener('focusin',event=>{
  if(!isEditable(event.target))return;
  editableFocus=true;
  focusScrollDone=false;
  focusBaseline=Math.max(window.innerHeight||0,viewport?.height||0);
  scheduleViewportSync();
 },true);
 document.addEventListener('focusout',()=>{
  requestFrame(()=>{
   editableFocus=isEditable(document.activeElement);
   if(!editableFocus){focusBaseline=0;focusScrollDone=false}
   scheduleViewportSync();
  });
 },true);
}
configureStudentDeviceProfile();

function telegramSupportsBotApi(version){
  if(!tg)return false;
  try{if(typeof tg.isVersionAtLeast==='function')return Boolean(tg.isVersionAtLeast(version))}catch(_){/* fall through to the reported version */}
  const current=String(tg.version||'').split('.').map(part=>Number.parseInt(part,10));
  const target=String(version).split('.').map(part=>Number.parseInt(part,10));
  if(!current.length||current.some(value=>!Number.isFinite(value)))return false;
  for(let i=0;i<Math.max(current.length,target.length);i++){
    const a=current[i]||0,b=target[i]||0;
    if(a>b)return true;if(a<b)return false;
  }
  return true;
}
function applyTelegramTheme(){
  const params=tg?.themeParams||{};
  const validColor=value=>typeof value==='string'&&/^#[0-9a-f]{6}$/i.test(value);
  if(validColor(params.button_color))document.documentElement.style.setProperty('--tg-action-color',params.button_color);
  if(validColor(params.bg_color))document.documentElement.style.setProperty('--tg-surface-color',params.bg_color);
  // Header/background setters were introduced in Bot API 6.1. Calling them on
  // Telegram 6.0 causes native SDK warnings, so gate every call first.
  if(!telegramSupportsBotApi('6.1'))return;
  try{
    if(typeof tg?.setHeaderColor==='function'){
      // Custom HEX header colours are supported from Bot API 6.9; older clients
      // accept only theme colour keys.
      tg.setHeaderColor(telegramSupportsBotApi('6.9')?'#061321':'bg_color');
    }
  }catch(_){/* native theming is progressive enhancement */}
  try{if(typeof tg?.setBackgroundColor==='function')tg.setBackgroundColor('#061321')}catch(_){/* native theming is progressive enhancement */}
}
if(tg){try{tg.ready();tg.expand();applyTelegramTheme();if(typeof tg.onEvent==='function')tg.onEvent('themeChanged',applyTelegramTheme)}catch(_){ }}
// Same-origin theme editor broadcasts apply immediately across open tabs;
// the signed server revision remains the source of truth across devices.
(function connectLiveThemeChannel(){
 const apply=message=>{
  if(!message||message.type!=='theme-save'||!/^[-a-z0-9_]{1,48}$/i.test(message.theme||''))return;
  const valid=value=>typeof value==='string'&&/^#[0-9a-f]{6}$/i.test(value);
  const rgb=value=>valid(value)?[1,3,5].map(i=>parseInt(value.slice(i,i+2),16)).join(', '):null;
  const body=document.body;if(!body)return;
  body.dataset.season=message.theme;body.dataset.theme=message.theme;
  const vars={'--season-accent':message.accent,'--season-secondary':message.secondary,'--season-bg-c':message.depth,
   '--season-accent-rgb':rgb(message.accent),'--season-secondary-rgb':rgb(message.secondary)};
  Object.entries(vars).forEach(([name,value])=>{if(value)body.style.setProperty(name,value)});
  if(message.themeVars&&typeof message.themeVars==='object'&&!Array.isArray(message.themeVars)){
   Object.entries(message.themeVars).slice(0,32).forEach(([name,value])=>{
    if(!/^season-[a-z0-9-]{1,48}$/.test(name)||typeof value!=='string')return;
    if(/^#[0-9a-f]{3,8}$/i.test(value)||/^\d{1,3},\s*\d{1,3},\s*\d{1,3}$/.test(value))body.style.setProperty(`--${name}`,value);
   });
  }
  const meta=document.querySelector('meta[name="theme-color"]');const themeDepth=message.themeVars?.['season-bg-b']||message.depth;if(meta&&valid(themeDepth))meta.content=themeDepth;
  if(!window.matchMedia?.('(prefers-reduced-motion: reduce)').matches){
   body.classList.remove('theme-changing');void body.offsetWidth;body.classList.add('theme-changing');
   window.setTimeout(()=>body.classList.remove('theme-changing'),1100);
  }
 };
 try{const channel=new BroadcastChannel('student-council-theme-v60');window.__studentAppThemeChannel=channel;channel.addEventListener('message',event=>apply(event.data));}
 catch(_){window.addEventListener('storage',event=>{if(event.key==='student-council-theme-v60'&&event.newValue){try{apply(JSON.parse(event.newValue))}catch(__){}}});}
})();
let state=null,activeTab='home',registrationStarted=false,declineModalEventId=null,eventModalId=null,lessonModalId=null,studentAppDirty=false,noticeModalId=null,lastRenderedStudentTab=null;
// Directory data is loaded by its own endpoint, not by /api/me. Keep it outside
// the replaceable profile state so live refreshes cannot blank the leadership page.
let leadershipDirectoryCache=null, leadershipDirectoryLoadedAt=0, leadershipDirectoryBusy=false;
let accountState=null,accountStateLoadedAt=0,accountStateBusy=false,accountCodeResult=null;
const studentReduceEffects=Boolean(window.matchMedia&&window.matchMedia('(prefers-reduced-motion: reduce)').matches);
let schedulePeriod='upcoming', calendarCursor=new Date(new Date().getFullYear(),new Date().getMonth(),1), calendarChosen=new Date().toLocaleDateString('sv-SE'), calendarKind='all', lastDialogTrigger=null;
const DECLINE_REASONS=['Учёба или экзамены','Здоровье','Семейные обстоятельства','Изменились планы','Другая причина'];
function esc(v){return String(v??'').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]))}
function withoutRussianFlag(value){return String(value??'').replace(/\u{1F1F7}\u{1F1FA}/gu,'').replace(/\s{2,}/g,' ').trim()}
function topicIcon(value){return withoutRussianFlag(value)||'✦'}
async function api(path, opt = {}) {
 const method = String(opt.method || 'GET').toUpperCase();
 // GET requests are safe to cancel. Never auto-abort writes: the server may have
 // committed a mutation even when the client loses its connection.
 const timeoutMs = Number.isFinite(opt.timeoutMs)
  ? Math.max(0, opt.timeoutMs)
  : (method === 'GET' || method === 'HEAD' ? 15000 : 0);
 const { timeoutMs: _timeoutMs, ...requestOptions } = opt;
 const headers = {'Content-Type':'application/json'};
 if (tg?.initData) headers['X-Telegram-Init-Data'] = tg.initData;
 else if (maxSignedLaunch) headers['X-Max-Init-Data'] = maxSignedLaunch;
 else if (vkSignedLaunch) headers['X-VK-Launch-Params'] = vkSignedLaunch;

 const controller = typeof AbortController === 'function' ? new AbortController() : null;
 const externalSignal = requestOptions.signal;
 let timeoutId = null;
 let relayAbort = null;
 if (controller && externalSignal) {
  if (externalSignal.aborted) controller.abort();
  else {
   relayAbort = () => controller.abort();
   externalSignal.addEventListener('abort', relayAbort, {once:true});
  }
 }
 if (controller && timeoutMs > 0) {
  timeoutId = window.setTimeout(() => controller.abort(), timeoutMs);
 }

 try {
  const response = await fetch(path, {
   cache:'no-store', ...requestOptions,
   headers:{...headers, ...(requestOptions.headers || {})},
   ...(controller ? {signal:controller.signal} : {}),
  });
  const data = await response.json().catch(() => ({ok:false,error:'Некорректный ответ сервера'}));
  if (!response.ok || data.ok === false) {
   const fallback = response.status === 409
    ? 'Конфликт данных: возможно, действие уже выполнено. Обновите кабинет и проверьте статус.'
    : response.status === 401
     ? 'Не удалось подтвердить аккаунт мессенджера. Откройте приложение заново из бота.'
     : 'Ошибка запроса';
   const error = new Error(data.error || fallback);
   error.status = response.status;
   throw error;
  }
  return data;
 } catch (error) {
  if (controller?.signal.aborted && !externalSignal?.aborted && timeoutMs > 0) {
   const timeoutError = new Error('Сервер не ответил за отведённое время. Проверьте соединение и повторите запрос.');
   timeoutError.name = 'TimeoutError';
   throw timeoutError;
  }
  throw error;
 } finally {
  if (timeoutId !== null) window.clearTimeout(timeoutId);
  if (relayAbort) externalSignal.removeEventListener('abort', relayAbort);
 }
}
function toast(t){const e=document.getElementById('toast');e.textContent=t;e.classList.add('show');clearTimeout(window._tt);window._tt=setTimeout(()=>e.classList.remove('show'),2600)}
function shell(){
 const s=state.student||{};
 const names=[['home','Мой кабинет'],['calendar','Календарь'],['apps','Заявления'],['leadership','Руководство']];
 if(state.leadership?.length)names.push(['leader','Заявки команды']);
 const shortcuts=[['home','⌂','Главная'],['calendar','▦','Календарь'],['apps','◫','Заявления'],['more','☰','Ещё']];
 const currentBottom=['leadership','leader','more'].includes(activeTab)?'more':activeTab;
 return `<header class="hero glass"><div class="top"><div><div class="title">${esc(s.full_name||'Личный кабинет')}</div><div class="muted">${esc(s.education_label||'Студент')}${s.group?' · '+esc(s.group):''}</div></div><div class="mission-mark" role="img" aria-label="Орбитальная эмблема"><span></span><b></b><em></em></div></div></header>
 <nav class="nav" aria-label="Разделы студенческого кабинета">${names.map(([id,label])=>`<button type="button" class="${activeTab===id?'active':''}" aria-current="${activeTab===id?'page':'false'}" data-action="tab" data-tab="${id}">${label}</button>`).join('')}</nav>
 <nav class="mission-bottom-nav" aria-label="Главная навигация">${shortcuts.map(([id,symbol,label])=>`<button type="button" class="${currentBottom===id?'active':''}" data-action="tab" data-tab="${id}" aria-current="${currentBottom===id?'page':'false'}"><span aria-hidden="true">${symbol}</span><small>${label}</small></button>`).join('')}</nav>`;
}

function missionHighlights(){
 const events=Array.isArray(state?.events)?state.events:[];
 const saved=events.find(e=>(e.days||[]).some(d=>d.registered));
 const next=saved||events.find(e=>!e.declined&&(e.days||[]).length);
 const active=(state?.directions||[]).filter(d=>d.status==='active'||d.status==='approved');
 const awaiting=(state?.directions||[]).filter(d=>d.status==='pending'||d.status==='interview');
 const headline=next?esc(next.title):'Новые события впереди';
 const displayDay=(saved?.days||[]).find(d=>d.registered)||next?.days?.[0];
 const date=displayDay?.date_label?esc(displayDay.date_label):'Анонсы появятся в разделе мероприятий';
 const eventSummary=next?(saved?'Вы записаны · ':'Доступно для участия · ')+date:'Следите за новыми встречами и мероприятиями команды';
 return `<section class="command-next-row" aria-label="Ближайшие шаги">
 <article class="command-next-card command-next-event"><div class="command-next-top"><span class="command-next-index">СЛЕДУЮЩАЯ МИССИЯ</span><span class="command-next-mark" aria-hidden="true">✧</span></div><h3>${headline}</h3><p>${eventSummary}</p><button type="button" class="command-next-link" data-action="tab" data-tab="calendar">Открыть календарь <span aria-hidden="true">↗</span></button></article>
 <article class="command-next-card command-next-team"><div class="command-next-top"><span class="command-next-index">ТВОЙ ПУТЬ В КОМАНДЕ</span><span class="command-next-mark" aria-hidden="true">◈</span></div><div class="command-next-counter"><strong>${active.length}</strong><span>активных направлений</span></div><p>${awaiting.length?`${awaiting.length} ${awaiting.length===1?'заявка ожидает':'заявок ожидают'} решения`:'Новые направления открыты для заявлений'}</p><button type="button" class="command-next-link" data-action="tab" data-tab="apps">Мои направления <span aria-hidden="true">↗</span></button></article>
 </section>`;
}
function parseLessonDate(lesson){
 const parts=String(lesson.date||'').split('.');
 if(parts.length!==3)return null;
 const date=new Date(Number(parts[2]),Number(parts[1])-1,Number(parts[0]));
 return Number.isNaN(date.getTime())?null:date;
}
function studentTodayPanel(){
 const lessons=(state.lessons||[]).slice().sort((a,b)=>(parseLessonDate(a)?.getTime()||Infinity)-(parseLessonDate(b)?.getTime()||Infinity));
 const startOfToday=new Date(new Date().getFullYear(),new Date().getMonth(),new Date().getDate());
 const nextLesson=lessons.find(l=>(parseLessonDate(l)?.getTime()||0)>=startOfToday.getTime());
 const applied=(state.directions||[]).filter(d=>['pending','interview'].includes(d.status));
 const upcoming=(state.events||[]).flatMap(e=>(e.days||[]).map(d=>({...d,title:e.title,eventId:e.id}))).sort((a,b)=>String(a.date||'').localeCompare(String(b.date||'')))[0];
 const label=upcoming?`${esc(upcoming.date_label||upcoming.date)} · ${esc(upcoming.title)}`:'Новых дат пока нет';
 return `<section class="mission-student-today" aria-labelledby="mission-student-today-title"><div class="mission-today-heading"><span class="command-kicker">ТВОЯ ОРБИТА СЕГОДНЯ</span><h2 id="mission-student-today-title">Что важно сейчас</h2></div><div class="mission-today-grid">
  <button class="mission-today-tile mission-today-tile--calendar" data-action="tab" data-tab="calendar"><span>▦ Единый календарь</span><strong>Занятия и мероприятия</strong><span class="mission-combined-items"><span>✧ <b>Мероприятие:</b> ${label}</span><span>◷ <b>Занятие:</b> ${nextLesson?esc(nextLesson.title)+' · '+esc(nextLesson.date):'Пока не назначено'}</span></span><small>Открыть календарь ↗</small></button>
  <button class="mission-today-tile" data-action="tab" data-tab="apps"><span>◫ Мои заявления</span><strong>${applied.length?`${applied.length} на рассмотрении`:'Нет ожидающих заявлений'}</strong><small>Проверить статусы ↗</small></button>
  <button class="mission-today-tile" data-action="tab" data-tab="apps"><span>◈ Направления</span><strong>Мои участия и заявки</strong><small>Открыть список ↗</small></button>
 </div></section>`;
}
function more(){
 const rows=[['leadership','♙','Руководство','Должности и публичные контакты']];
 if(state.leadership?.length)rows.push(['leader','☆','Заявки команды','Рассмотрение заявлений']);
 return `<section class="mission-more"><div class="section-title"><div><h2>Ещё</h2><span>Разделы и настройки твоего кабинета</span></div></div><div class="mission-more-list">${rows.map(([id,ico,label,desc])=>`<button data-action="tab" data-tab="${id}"><span aria-hidden="true">${ico}</span><span><strong>${label}</strong><small>${desc}</small></span><b aria-hidden="true">↗</b></button>`).join('')}<button data-action="open-home-section" data-target="my-profile"><span aria-hidden="true">◎</span><span><strong>Мой профиль</strong><small>Учёба, контакты и мои направления</small></span><b aria-hidden="true">↗</b></button><button data-action="open-home-section" data-target="my-connected-accounts"><span aria-hidden="true">⛓</span><span><strong>Привязанные аккаунты</strong><small>Telegram, ВКонтакте и MAX в одном профиле</small></span><b aria-hidden="true">↗</b></button></div></section>`;
}

const ACCOUNT_PLATFORMS=[
 {id:'telegram',label:'Telegram',symbol:'✈',description:'Основной профиль или подключение Telegram'},
 {id:'vk',label:'ВКонтакте',symbol:'ᴠκ',description:'VK ID и бот ВКонтакте'},
 {id:'max',label:'MAX',symbol:'M',description:'MAX ID и бот MAX'}
];
function accountSettings(forceRefresh=false){
 if(forceRefresh&&(!accountState||Date.now()-accountStateLoadedAt>45000)&&!accountStateBusy)loadAccountSettings();
 const accounts=accountState?.accounts||{};
 const current=accountState?.current_platform||'standalone';
 const canLink=Boolean(accountState?.link_allowed);
 const tiles=ACCOUNT_PLATFORMS.map(meta=>{
  const status=accounts[meta.id]||{connected:false,primary:false};
  const connected=Boolean(status.connected),isCurrent=current===meta.id;
  let controls='';
  const botAvailable=accountState?.platforms_available?.[meta.id]!==false;
  if(!connected&&botAvailable){
   controls=`<form class="account-connect-form" data-submit="account-generate"><input type="hidden" name="platform" value="${meta.id}"><label class="account-handle-label" for="account-handle-${meta.id}">${meta.id==='vk'?'VK ID (можно оставить пустым)':meta.id==='max'?'Username MAX (необязательно)':'Username Telegram (необязательно)'}</label><input class="account-handle-input" id="account-handle-${meta.id}" name="handle" autocomplete="off" maxlength="100" ${!canLink?'disabled':''} placeholder="${meta.id==='vk'?'Например, 123456789':meta.id==='max'?'@username':'@username'}"><button class="btn primary account-connect-button" type="submit" ${!canLink?'disabled':''}><span aria-hidden="true">⛓</span> Привязать ${meta.label}</button></form>`;
  }else if(!connected&&!botAvailable){
   const missing=meta.id==='vk'?'VK_BOT_TOKEN и VK_GROUP_ID':meta.id==='max'?'MAX_BOT_TOKEN':'BOT_TOKEN';
   controls=`<div class="account-controls-connected"><span class="account-note">Бот временно недоступен. Администратору нужно настроить <code>${missing}</code> в <code>.env</code> и перезапустить сервер.</span></div>`;
  }else if(meta.id!=='telegram'&&!isCurrent){
   controls=`<div class="account-controls-connected"><span class="account-note">Аккаунт подтверждён и связан с вашим профилем.</span><button class="btn danger account-connect-button" type="button" data-action="account-confirm-unlink" data-platform="${meta.id}">ОТВЯЗАТЬ ${meta.label.toUpperCase()}</button></div>`;
  }else{
   controls=`<div class="account-controls-connected"><span class="account-note">${isCurrent?'Вы сейчас вошли через эту платформу.':'Этот способ входа сохранён в профиле.'}</span></div>`;
  }
  return `<article class="account-tile account-tile-${meta.id} glass"><div class="account-heading"><span class="account-logo account-logo-${meta.id}" aria-hidden="true">${meta.symbol}</span><div class="account-heading-text"><h3>${meta.label}</h3><span class="muted">${meta.description}</span></div><span class="badge account-chip ${connected?'success':'muted'}">${connected?'Подключён':'Не подключён'}</span></div><div class="account-controls">${controls}</div></article>`;
 }).join('');
 const pending=accountState?.pending||[];
 const pendingMarkup=pending.length?`<section class="account-pending"><div class="section-title"><div><h3>Запросы на подтверждение</h3><span>Новые аккаунты не подключатся без вашего решения.</span></div><span class="badge">${pending.length}</span></div>${pending.map(item=>{const label=ACCOUNT_PLATFORMS.find(p=>p.id===item.platform)?.label||item.platform.toUpperCase();return `<article class="account-journey-step glass"><div><strong>${esc(label)} · ${esc(item.handle||'Аккаунт')}</strong><p class="muted">Запрос №${Number(item.id)} · истекает ${esc(String(item.expires_at||'').replace('T',' ').replace('Z',' UTC'))}</p></div><div class="actions"><button type="button" class="btn success" data-action="account-review" data-request-id="${Number(item.id)}" data-approve="true">Подтвердить</button><button type="button" class="btn danger" data-action="account-review" data-request-id="${Number(item.id)}" data-approve="false">Отклонить</button></div></article>`}).join('')}</section>`:'<div class="empty account-empty">Нет ожидающих запросов. После ввода кода в боте новый запрос появится здесь.</div>';
 const codeMarkup=accountCodeResult?`<div class="account-code-result glass" role="status"><strong>Одноразовый код · ${esc(ACCOUNT_PLATFORMS.find(p=>p.id===accountCodeResult.platform)?.label||accountCodeResult.platform)}</strong><code>${esc(accountCodeResult.code)}</code><p>${esc(accountCodeResult.message)}</p><button type="button" class="btn" data-action="account-copy-code">Копировать код</button></div>`:'';
 const statusMarkup=!accountState?`<div class="loading account-loading">Проверяем привязки по подтверждённой сессии…</div>`:accountState.error?`<div class="notice account-unavailable" role="status">${esc(accountState.error)} ${accountState.link_allowed?'':'Откройте приложение через бота, чтобы подтвердить личность.'}</div>`:``;
 return `<section id="my-connected-accounts" class="mission-connected-accounts"><div class="section-title"><div><span class="command-kicker">КОНТУР ИДЕНТИФИКАЦИИ</span><h2>Привязанные аккаунты</h2><span>Один профиль студента · три мессенджера</span></div><button class="btn" type="button" data-action="account-refresh">↻ Обновить</button></div>${statusMarkup}<div class="accounts-grid">${tiles}</div>${codeMarkup}<section class="account-pending-wrap">${pendingMarkup}</section><p class="account-footnote">${canLink?'Не передавайте коды посторонним. Подтверждайте только собственные аккаунты.':'Откройте Student App из Telegram, VK или MAX, чтобы управлять привязками. Обычный браузер/демо-режим не может подтвердить личность мессенджера.'}</p></section>`;
}
async function loadAccountSettings(force=false){
 if(accountStateBusy)return;
 if(!force&&accountState&&Date.now()-accountStateLoadedAt<45000)return;
 accountStateBusy=true;
 try{accountState=await api('/student-app/api/accounts');accountStateLoadedAt=Date.now();}
 catch(e){accountState={ok:false,link_allowed:false,current_platform:'standalone',accounts:{},pending:[],error:e.message};accountStateLoadedAt=Date.now();}
 finally{accountStateBusy=false;}
 if(['home','more'].includes(activeTab)&&state){const y=window.scrollY;render({motion:false});window.scrollTo(0,y);}
}
async function generateAccountLink(ev){
 ev.preventDefault();const form=ev.target;const data=new FormData(form);const button=form.querySelector('button[type="submit"]');if(button?.disabled)return;if(button)button.disabled=true;
 try{const result=await api('/student-app/api/accounts/code',{method:'POST',body:JSON.stringify({platform:String(data.get('platform')||''),handle:String(data.get('handle')||'').trim()})});accountCodeResult=result;toast('Код создан. Продолжите в личном чате бота выбранной платформы.');await loadAccountSettings(true);}
 catch(e){toast(e.message)}finally{if(button&&button.isConnected)button.disabled=false;}
}
async function reviewAccountLink(id,approve){
 const action=approve?'подключить этот аккаунт':'отклонить запрос';if(approve&&!confirm(`Подтвердить и ${action}? Убедитесь, что это ваш аккаунт.`))return;
 try{const result=await api(`/student-app/api/accounts/${id}/review`,{method:'POST',body:JSON.stringify({approve})});accountState={...accountState,...result};accountStateLoadedAt=Date.now();toast(result.message||'Решение сохранено.');render({motion:false});}
 catch(e){toast(e.message);await loadAccountSettings(true)}
}
async function unlinkAccount(platform){
 const label=ACCOUNT_PLATFORMS.find(p=>p.id===platform)?.label||platform.toUpperCase();
 if(!confirm(`Отвязать ${label}? Заявки, направления и профиль сохранятся, но вход через этот мессенджер прекратится.`))return;
 try{const result=await api(`/student-app/api/accounts/${encodeURIComponent(platform)}`,{method:'DELETE',body:'{}'});accountState={...accountState,...result};accountStateLoadedAt=Date.now();accountCodeResult=null;toast(result.message||'Аккаунт отвязан.');render({motion:false});}
 catch(e){toast(e.message)}
}
function studentAnnouncements(){
 const list=(Array.isArray(state?.announcements)?state.announcements:[]).filter(n=>n.category!=='science'&&(!n.expires_at||Date.parse(n.expires_at)>Date.now()));
 const labels={system:'Объявление',events:'Мероприятие',lessons:'Занятие',applications:'Заявление'};
 return `<section class="student-announcements" aria-labelledby="student-announcements-title">
   <div class="section-title"><div><h2 id="student-announcements-title">Уведомления команды</h2><span>Объявления и обновления ваших направлений</span></div><span class="badge">${list.length}</span></div>
   <div class="student-announcements-list" aria-live="polite">${list.length?list.slice(0,12).map(n=>`<article class="student-announcement glass"><div class="student-announcement-heading"><span>${esc(labels[n.category]||'Новость')}</span><time>${esc(n.date)}</time></div><button type="button" class="student-announcement-open" data-action="notice-open" data-id="${Number(n.id)}"><strong>${esc(n.title)}</strong><small>Открыть сообщение ↗</small></button></article>`).join(''):'<div class="glass card empty">Здесь появятся сообщения руководителей и объявления о занятиях и событиях.</div>'}</div>
 ${noticeModalId!==null&&list.some(n=>Number(n.id)===noticeModalId)?(()=>{const n=list.find(n=>Number(n.id)===noticeModalId);return `<div class="student-notice-backdrop" data-action="notice-close"><section role="dialog" aria-modal="true" aria-label="Уведомление" class="glass card student-notice-modal"><button class="btn" data-action="notice-close">× Закрыть</button><small>${esc(n.date)}</small><h2>${esc(n.title)}</h2><p>${esc(n.body)}</p></section></div>`})():''}
 </section>`;
}
function home(){
 const student=state.student||{};
 const firstName=String(student.full_name||'').trim().split(/\s+/)[1]||String(student.full_name||'').trim().split(/\s+/)[0]||'студент';
 const directions=state.directions||[];
 const activeDirections=directions.filter(d=>['active','approved'].includes(d.status));
 const pendingDirections=directions.filter(d=>['pending','interview'].includes(d.status));
 const upcomingCount=(state.events||[]).filter(e=>(e.days||[]).some(d=>!d.declined)).length;
 const todayName=esc(firstName);
 return `<div class="command-dashboard">
   <section class="command-hero" aria-labelledby="command-welcome-heading">
     <div class="command-hero-stars" aria-hidden="true"></div>
     <div class="command-hero-copy">
       
       <h1 id="command-welcome-heading">Привет, ${todayName} <span aria-hidden="true">✦</span></h1>
       <p>Профиль, заявления, направления и расписание — в одном рабочем пространстве.</p>
       <div class="command-hero-actions">
         <button class="btn primary" type="button" data-action="tab" data-tab="apps">Мои заявления <span aria-hidden="true">↗</span></button>
         <button class="btn command-btn-glass" type="button" data-action="tab" data-tab="calendar">Открыть календарь ↗</button>
       </div>
     </div>
     <div class="command-world" aria-hidden="true"><div class="command-world-halo"></div><div class="command-depth-track command-depth-track--far"></div><div class="command-world-planet"></div><div class="command-depth-atmosphere"></div><div class="command-world-orbit"></div><div class="command-depth-track command-depth-track--near"></div><div class="command-depth-moon"></div><span class="command-world-spark">✧</span></div>
   </section>
   <section class="command-metrics" aria-label="Состояние кабинета">
     <article class="command-metric"><span class="command-metric-icon" aria-hidden="true">✦</span><div><span class="command-metric-label">Направления</span><strong>${activeDirections.length}</strong><small>Активных</small></div></article>
     <article class="command-metric"><span class="command-metric-icon" aria-hidden="true">◷</span><div><span class="command-metric-label">Заявления</span><strong>${pendingDirections.length}</strong><small>Ожидают решения</small></div></article>
     <article class="command-metric"><span class="command-metric-icon" aria-hidden="true">✧</span><div><span class="command-metric-label">События</span><strong>${upcomingCount}</strong><small>В календаре</small></div></article>
   </section>
   ${studentTodayPanel()}
   ${studentAnnouncements()}
   ${missionHighlights()}
   <div class="mission-student-settings-heading"><span class="command-kicker">МОЙ ПРОФИЛЬ</span><h2>Всё в одном кабинете</h2><p>Личные данные и настройки всегда под рукой.</p></div>
   <details id="my-profile" class="mission-student-disclosure"><summary><span><b>Личные данные</b><small>Группа, контакты и роли в команде</small></span><span aria-hidden="true">⌄</span></summary><div class="mission-student-disclosure-body">${profile()}</div></details>
 </div>`;
}
function statusText(s){return {pending:'На рассмотрении',interview:'Собеседование',approved:'Активно',active:'Активно',rejected:'Отклонено'}[s]||String(s??'—')}
function statusClass(s){return s==='active'||s==='approved'?'ok':s==='rejected'?'red':'warn'}
function apps(){const own=state.directions.map(d=>`<div class="glass card"><div class="row space"><div class="row"><div class="icon">${esc(topicIcon(d.icon))}</div><div><b>${esc(withoutRussianFlag(d.name))}</b><div class="muted" style="font-size:9px">${esc(d.description||'')}</div></div></div><span class="badge ${statusClass(d.status)}">${esc(statusText(d.status))}</span></div>${d.status==='rejected'&&d.rejection_reason?`<div class="muted" style="font-size:10px;margin-top:8px">Причина отказа: ${esc(d.rejection_reason)}${d.blocked_until?`<br>Повторная подача после: ${esc(new Date(d.blocked_until).toLocaleString('ru-RU'))}`:' — повторная подача доступна'}</div>`:''}${d.removable?`<div class="actions"><button class="btn danger" data-action="remove-app" data-id="${d.id}">${d.status==='active'?'Покинуть направление':'Удалить заявку'}</button></div>`:''}</div>`).join('');const available=state.available_directions.map(d=>`<div class="dir-option"><div class="icon">${esc(topicIcon(d.icon))}</div><div class="grow"><b>${esc(withoutRussianFlag(d.name))}</b><small>${esc(d.description||'')}</small></div><button class="btn primary" data-action="apply-dir" data-id="${d.id}">Подать</button></div>`).join('');return `${activeBlocksPanel()}<div class="section-title"><div><h2>Мои заявки</h2><span>Общая база профилей</span></div></div>${own||'<div class="glass card empty">Заявок пока нет.</div>'}<div class="section-title"><div><h2>Новое направление</h2><span>Выберите любое доступное направление; можно подать заявления в несколько направлений</span></div></div><div class="glass card">${available||'<div class="empty">Все доступные направления уже выбраны.</div>'}</div>`}
function displayDateTime(value){if(!value)return 'Срок не указан';let raw=String(value);if(!/[zZ]|[+-]\d\d:\d\d$/.test(raw))raw+='Z';const date=new Date(raw);return Number.isNaN(date.getTime())?esc(value):date.toLocaleString('ru-RU',{day:'2-digit',month:'long',year:'numeric',hour:'2-digit',minute:'2-digit'})}
function activeBlocksPanel(){const blocks=state?.active_blocks||[];return `<section class="blocks-section ${blocks.length?'has-active-blocks':'no-active-blocks'}"><div class="section-title"><div><h2>Активные блокировки</h2><span>Ограничения на повторную подачу заявлений</span></div><span class="badge ${blocks.length?'red':'ok'}">${blocks.length?`${blocks.length} активно`:'Нет активных'}</span></div>${blocks.length?`<div class="active-blocks-list">${blocks.map(block=>`<article class="active-block-card"><div class="block-icon">!</div><div class="active-block-copy"><div class="active-block-kicker">ВРЕМЕННОЕ ОГРАНИЧЕНИЕ</div><h3>${esc(withoutRussianFlag(block.direction_name))}</h3><p>${esc(block.reason||'Причина не указана')}</p><div class="block-expiry"><span>Повторная подача доступна</span><b>${displayDateTime(block.blocked_until)}</b></div></div></article>`).join('')}</div>`:'<div class="block-clear-state"><span class="block-clear-check">✓</span><div><b>Всё в порядке</b><p>Сейчас нет действующих ограничений на подачу заявлений.</p></div></div>'}</section>`}

function visitedEventsBlock(){
 const visited=state?.attended_events||[];
 return `<section class="visited-events-section"><div class="section-title"><div><h2>Посещённые мероприятия</h2><span>История подтверждённой явки</span></div><span class="badge ok">${visited.length}</span></div>${visited.length?`<div class="visited-events-list">${visited.map(e=>`<article class="visited-event-row"><span class="visited-event-mark">✓</span><div class="grow"><b>${esc(e.title)}</b><div class="muted">${esc(e.location||'Место не указано')}</div><small>Посещено: ${esc((e.dates||[]).join(', ')||e.last_visit||'—')}</small></div><span class="badge ok">Посещено</span></article>`).join('')}</div>`:'<div class="glass card empty visited-empty">Вы пока не посещали мероприятия с подтверждённой отметкой. После отметки организатора они появятся здесь.</div>'}</section>`;
}
function events(){
 const active=state.events?.length?state.events.map(e=>{
  const hasRegistered=(e.days||[]).some(d=>d.registered);
  const next=(e.days||[])[0];
  return `<article class="event event-preview" role="button" tabindex="0" data-action="open-event" data-id="${e.id}" aria-label="Подробнее о мероприятии ${esc(e.title)}"><div class="event-heading"><div><div class="eyebrow">МЕРОПРИЯТИЕ / ${e.declined?'ОТКАЗ':hasRegistered?'ВЫ ЗАПИСАНЫ':'ДОСТУПНО'}</div><h3>${esc(e.title)}</h3></div>${e.declined?'<span class="badge red">Отказ</span>':hasRegistered?'<span class="badge ok">Записаны</span>':'<span class="badge">Подробнее</span>'}</div><p>${esc(e.description||'Без описания')}</p><div class="meta"><span>📍 ${esc(e.location||'Место уточняется')}</span>${e.time?`<span>🕒 ${esc(e.time)}</span>`:''}${next?`<span>📅 ${esc(next.date_label)}</span>`:''}</div><div class="event-preview-footer"><span>${hasRegistered?'Есть активная запись':e.declined?'Вы оформили отказ':`${(e.days||[]).length} дат доступно`}</span><b>Открыть карточку ↗</b></div></article>`;
 }).join(''):'<div class="glass card empty">Сейчас нет активных мероприятий для ваших направлений.</div>';
 return `<div class="section-title"><div><h2>Мероприятия</h2><span>Нажмите на карточку, чтобы увидеть подробности и запись</span></div></div><div class="event-card-list">${active}</div>${visitedEventsBlock()}`;
}
function eventModalMarkup(){
 if(!eventModalId)return '';
 const e=(state?.events||[]).find(item=>item.id===eventModalId);
 if(!e){
  const past=(state?.calendar||[]).find(item=>item.kind==='event'&&item.event_id===eventModalId);
  if(!past)return '';
  return `<div class="event-modal-backdrop" data-action="close-event-modal"><section class="event-modal" role="dialog" aria-modal="true" aria-labelledby="event-modal-title"><button class="event-modal-close" type="button" aria-label="Закрыть" data-action="close-event-modal">×</button><div class="eyebrow">КАЛЕНДАРЬ · АРХИВ МЕРОПРИЯТИЙ</div><h2 id="event-modal-title">${esc(past.title)}</h2><p>${esc(past.description||'')}</p><div class="meta"><span>Дата: ${esc(past.date)}</span><span>Время: ${esc(past.time||'уточняется')}</span><span>Место: ${esc(past.room||'уточняется')}</span></div><div class="event-modal-bottom"><button class="btn" type="button" data-action="close-event-modal">Закрыть</button></div></section></div>`;
 }
 const hasRegistered=(e.days||[]).some(d=>d.registered);
 const days=(e.days||[]).length?`<div class="event-modal-subtitle">Даты и регистрация</div><div class="event-days">${e.days.map(d=>`<div class="event-date-row"><div class="event-date-info"><b>${esc(d.date_label)}</b><small>${esc(d.weekday||'')}</small></div><span class="badge ${d.registered?'ok':''}">${d.registered?'Вы записаны':`Свободно мест: ${d.places}`}</span>${d.registered?'':`<button class="btn success" ${d.places<=0?'disabled':''} data-action="join-event" data-quota-id="${e.id}" data-day-id="${d.id}">Записаться</button>`}</div>`).join('')}</div>`:'<div class="empty">Доступных дат для записи сейчас нет.</div>';
 const status=e.declined?`<div class="decline-status"><div class="decline-status-icon">↩</div><div class="grow"><b>Отказ оформлен</b><p>${esc(e.decline_reason||'Причина не указана')}</p><small>${esc(e.declined_at||'')}</small></div></div><div class="actions"><button class="btn primary" data-action="return-event" data-id="${e.id}">Вернуться к мероприятию</button></div>`:hasRegistered?`<div class="event-modal-refusal"><span>Вы записаны на это мероприятие.</span><button class="btn danger" data-action="decline-event" data-id="${e.id}">Отказаться от мероприятия</button></div>`:'<p class="event-modal-note">Отказ доступен только после записи хотя бы на одну дату мероприятия.</p>';
 return `<div class="event-modal-backdrop" data-action="close-event-modal"><section class="event-modal" role="dialog" aria-modal="true" aria-labelledby="event-modal-title"><button class="event-modal-close" type="button" aria-label="Закрыть" data-action="close-event-modal">×</button><div class="event-modal-topline"><span class="event-modal-symbol">✦</span><div><div class="eyebrow">КАРТОЧКА МЕРОПРИЯТИЯ</div><h2 id="event-modal-title">${esc(e.title)}</h2></div>${e.declined?'<span class="badge red">Отказ</span>':hasRegistered?'<span class="badge ok">Записаны</span>':''}</div><p class="event-modal-description">${esc(e.description||'Без дополнительного описания.')}</p><div class="event-modal-meta"><span>📍 ${esc(e.location||'Место уточняется')}</span>${e.time?`<span>🕒 ${esc(e.time)}</span>`:''}${e.leader?`<span>👑 ${esc(e.leader.name)}${e.leader.position?` · ${esc(e.leader.position)}`:''}</span>`:''}</div>${e.dress_code?`<div class="event-modal-detail"><small>Дресс-код</small><span>${esc(e.dress_code)}</span></div>`:''}${e.functionality?`<div class="event-modal-detail"><small>Дополнительная информация</small><span>${esc(e.functionality)}</span></div>`:''}${e.declined?'':days}${status}<div class="event-modal-bottom"><button class="btn" type="button" data-action="close-event-modal">Закрыть</button></div></section></div>`;
}
function declineModalMarkup(){
 if(!declineModalEventId)return '';
 const e=(state?.events||[]).find(item=>item.id===declineModalEventId);
 if(!e)return '';
 return `<div class="decline-modal-backdrop" data-action="close-decline-modal"><section class="decline-modal" role="dialog" aria-modal="true" aria-labelledby="decline-modal-title"><button class="decline-modal-close" type="button" aria-label="Закрыть" data-action="close-decline-modal">×</button><div class="decline-modal-orbit">↗</div><div class="eyebrow">УЧАСТИЕ В МЕРОПРИЯТИИ</div><h2 id="decline-modal-title">Почему вы хотите отказаться?</h2><p class="muted">${esc(e.title)}. Укажите причину — она будет сохранена в статистике для организаторов.</p><form class="form" data-submit="decline-reason"><div class="decline-reason-options">${DECLINE_REASONS.map(reason=>`<label class="decline-reason-option"><input type="radio" name="reason_category" value="${esc(reason)}" required><span class="reason-radio-dot"></span><span>${esc(reason)}</span></label>`).join('')}</div><div class="field"><label for="decline-details">Комментарий <span>(необязательно)</span></label><textarea class="input decline-details" id="decline-details" name="details" rows="3" maxlength="1800" placeholder="Добавьте подробности, если это необходимо"></textarea><small class="decline-help">Для варианта «Другая причина» напишите хотя бы 5 символов.</small></div><div class="decline-modal-actions"><button class="btn" type="button" data-action="close-decline-modal">Оставить запись</button><button class="btn danger" type="submit">Подтвердить отказ</button></div></form></section></div>`
}
// Unified data feed. The list is intentionally the primary mobile view;
// lessons and events always come from the same persisted Student App API.
function studentTimelineItems(){
 const isoDate=value=>{
  const v=String(value||'').trim();
  if(/^\d{4}-\d{2}-\d{2}/.test(v))return v.slice(0,10);
  const m=v.match(/^(\d{2})\.(\d{2})\.(\d{4})$/);
  return m?`${m[3]}-${m[2]}-${m[1]}`:'';
 };
 const result=[],seen=new Set();
 const add=item=>{
  const date=isoDate(item.date);
  if(!date)return;
  const kind=item.kind==='lesson'?'lesson':'event';
  const id=kind==='lesson'?item.id:(item.event_id||item.eventId||item.id);
  const key=`${kind}:${id}:${date}`;
  if(seen.has(key))return;
  seen.add(key);
  result.push({...item,kind,date});
 };
 (state.calendar||[]).forEach(add);
 (state.lessons||[]).forEach(item=>add({...item,kind:'lesson'}));
 (state.events||[]).forEach(event=>(event.days||[]).forEach(day=>add({
  ...day,kind:'event',event_id:event.id,title:event.title,
  description:event.description||'',room:event.location||'',time:event.time||'',
  registered:day.registered,
 })));
 return result.sort((a,b)=>a.date.localeCompare(b.date)||String(a.time||'').localeCompare(String(b.time||'')));
}
function lessonDetail(){
 if(lessonModalId===null)return '';
 const lesson=studentTimelineItems().find(item=>item.kind==='lesson'&&String(item.id)===String(lessonModalId));
 if(!lesson)return '';
 const formatted=lesson.date.slice(8,10)+'.'+lesson.date.slice(5,7)+'.'+lesson.date.slice(0,4);
 const meta=[
  ['Календарная дата',formatted],
  ['Время',`${lesson.time||'Уточняется'}${lesson.end_time?' — '+lesson.end_time:''}`],
  ['Место / аудитория',lesson.room||'Уточняется'],
  ['Преподаватель / ведущий',lesson.teacher||'Не указан'],
  ['Направление',String(lesson.direction_name||'').replace(/\u{1F1F7}\u{1F1FA}/gu,'').trim()||'Студенческий совет'],
  ['Продолжительность',lesson.duration_minutes?`${lesson.duration_minutes} минут`:null],
 ].filter(x=>x[1]);
 return `<div class="event-modal-backdrop" data-action="close-lesson-modal"><section class="event-modal lesson-detail-dialog" role="dialog" aria-modal="true" aria-labelledby="lesson-modal-title"><button class="event-modal-close" type="button" aria-label="Закрыть карточку занятия" data-action="close-lesson-modal">×</button><div class="event-modal-topline"><span class="event-modal-symbol">◷</span><div><div class="eyebrow">КАРТОЧКА ЗАНЯТИЯ</div><h2 id="lesson-modal-title">${esc(lesson.title||'Занятие')}</h2></div><span class="badge">Занятие</span></div><p class="event-modal-description">${esc(lesson.description||'Дополнительное описание пока не добавлено организатором.')}</p><dl class="lesson-detail-grid">${meta.map(([name,value])=>`<div><dt>${esc(name)}</dt><dd>${esc(value)}</dd></div>`).join('')}</dl><div class="event-modal-bottom"><button class="btn" type="button" data-action="close-lesson-modal">Закрыть</button><button class="btn primary" type="button" data-action="download-lesson" data-lesson-id="${esc(lesson.id)}">Добавить в календарь ↗</button></div></section></div>`;
}
function schedule(){
 const today=new Date().toLocaleDateString('sv-SE');
 const endWeek=new Date();endWeek.setDate(endWeek.getDate()+7);
 const weekUntil=endWeek.toLocaleDateString('sv-SE');
 const month=today.slice(0,7);
 const period=schedulePeriod;
 const kind=calendarKind;
 const records=studentTimelineItems();
 const filtered=records.filter(item=>{
  if(kind!=='all'&&item.kind!==kind)return false;
  if(period==='upcoming')return item.date>=today;
  if(period==='week')return item.date>=today&&item.date<=weekUntil;
  if(period==='month')return item.date.slice(0,7)===month;
  return true;
 });
 const lessonCount=filtered.filter(x=>x.kind==='lesson').length;
 const eventCount=filtered.filter(x=>x.kind==='event').length;
 const cards=filtered.map(item=>{
  const label=item.date.slice(8,10)+'.'+item.date.slice(5,7)+'.'+item.date.slice(0,4);
  const isLesson=item.kind==='lesson';
  return `<article class="mission-lesson mission-list-card ${isLesson?'mission-list-lesson':'mission-list-event'}"><div class="mission-lesson-date"><strong>${esc(label)}</strong><span>${esc(item.time||'Время уточняется')}</span></div><div class="mission-lesson-details"><span class="mission-list-kicker">${isLesson?'◷ ЗАНЯТИЕ':'✦ МЕРОПРИЯТИЕ'}${item.direction_name?' · '+esc(String(item.direction_name).replace(/\u{1F1F7}\u{1F1FA}/gu,'').trim()):''}</span><h3>${esc(item.title||'Без названия')}</h3>${item.description?`<p>${esc(item.description)}</p>`:''}<div class="meta">${item.room?`<span>⌖ ${esc(item.room)}</span>`:''}${isLesson&&item.teacher?`<span>👤 ${esc(item.teacher)}</span>`:''}${item.registered?'<span>✓ Вы записаны</span>':''}</div></div><button type="button" class="btn mission-list-more" data-action="${isLesson?'open-lesson':'open-event'}" data-id="${esc(isLesson?item.id:(item.event_id||item.eventId))}">Подробнее ↗</button></article>`;
 }).join('');
 const typeButtons=[['all','Все'],['lesson','Занятия'],['event','Мероприятия']].map(([id,label])=>`<button type="button" data-action="calendar-type" data-kind="${id}" class="${kind===id?'is-active':''}" aria-pressed="${kind===id}">${label}</button>`).join('');
 const periodButtons=[['upcoming','Предстоящие'],['week','7 дней'],['month','Этот месяц'],['all','Все даты']].map(([id,label])=>`<button type="button" data-action="schedule-period" data-period="${id}" class="${period===id?'is-active':''}" aria-pressed="${period===id}">${label}</button>`).join('');
 return `<section class="student-calendar-shell mission-list-schedule"><header class="sc-heading"><div><div class="eyebrow">МОЁ РАСПИСАНИЕ · ОДНА ЛЕНТА</div><h1>Занятия и мероприятия</h1><p>Все события твоих направлений собраны в понятный список. Нажми «Подробнее», чтобы открыть полную карточку.</p></div><div class="sc-counts"><span><i class="sc-dot sc-dot-lesson"></i> Занятий <b>${lessonCount}</b></span><span><i class="sc-dot sc-dot-event"></i> Мероприятий <b>${eventCount}</b></span></div></header><div class="mission-list-toolbar glass"><div class="mission-list-selector" role="group" aria-label="Тип записи">${typeButtons}</div><div class="mission-list-selector" role="group" aria-label="Период">${periodButtons}</div></div><div class="mission-list-feed">${cards||'<div class="glass card empty">Записей за выбранный период пока нет. Попробуй «Все даты».</div>'}</div><details class="glass sc-visited"><summary>История посещённых мероприятий</summary>${typeof visitedEventsBlock==='function'?visitedEventsBlock():''}</details></section>`;
}
function saveLessonCalendar(lessonId){
 const l=studentTimelineItems().find(x=>x.kind==='lesson'&&Number(x.id)===lessonId);if(!l)return;
 const day=new Date(String(l.date)+'T00:00:00');if(Number.isNaN(day.getTime()))return;
 const parts=String(l.time||'00:00').split(':');day.setHours(Number(parts[0])||0,Number(parts[1])||0);
 const end=new Date(day.getTime()+(Number(l.duration_minutes)||90)*60000);
 const stamp=d=>`${d.getFullYear()}${String(d.getMonth()+1).padStart(2,'0')}${String(d.getDate()).padStart(2,'0')}T${String(d.getHours()).padStart(2,'0')}${String(d.getMinutes()).padStart(2,'0')}00`;
 const escapeIcs=s=>String(s||'').replace(/\\/g,'\\\\').replace(/\n/g,'\\n').replace(/[,;]/g,m=>'\\'+m);
 const ics=`BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//Student Council//RU\r\nBEGIN:VEVENT\r\nUID:lesson-${l.id}@galaxy-student\r\nDTSTAMP:${new Date().toISOString().replace(/[-:]/g,'').replace(/\.\d{3}/,'')}\r\nDTSTART:${stamp(day)}\r\nDTEND:${stamp(end)}\r\nSUMMARY:${escapeIcs(l.title)}\r\nLOCATION:${escapeIcs(l.room)}\r\nDESCRIPTION:${escapeIcs(l.direction_name)}\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n`;
 const url=URL.createObjectURL(new Blob([ics],{type:'text/calendar;charset=utf-8'}));
 const a=document.createElement('a');a.href=url;a.download=`galaxy-lesson-${l.id}.ics`;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
}

function profile(){
 const s=state.student||{};
 const initial=String(s.full_name||'С').trim().split(/\s+/).map(x=>x[0]||'').slice(0,2).join('').toUpperCase();
 const roleHtml=(state.leadership||[]).length?`<div class="command-roles"><div class="command-card-label">Твои роли в студсовете</div>${state.leadership.map(r=>`<span class="role-pill">✦ ${esc(r.position)} · ${esc(withoutRussianFlag(r.direction_name))}</span>`).join('')}</div>`:'';
 return `<div class="command-profile-grid">
   <article class="glass command-identity-card"><div class="command-card-label">УЧЁТНАЯ ЗАПИСЬ</div><div class="command-identity-person"><span class="command-avatar" aria-hidden="true">${esc(initial)}</span><div><h3>${esc(s.full_name||'Студент')}</h3><p>${esc(s.education_label||'Студент')}</p></div></div><div class="command-identity-details"><div><span>Группа</span><strong>${esc(s.group||'Не указана')}</strong></div><div><span>Направления</span><strong>${(state.directions||[]).length}</strong></div></div>${roleHtml}</article>
   <article class="glass command-edit-card"><div class="command-card-label">НАСТРОЙКИ ПРОФИЛЯ</div><h3>Контактные данные</h3><p class="command-subtitle">Актуализируй данные, чтобы организаторы могли связаться с тобой.</p><form class="form command-profile-form" data-submit="save-profile"><div class="field"><label for="command-group">Учебная группа</label><input id="command-group" class="input" name="group" value="${esc(s.group||'')}" autocomplete="organization"></div><div class="field"><label for="command-phone">Номер телефона</label><input id="command-phone" class="input" name="phone" type="tel" value="${esc(s.phone||'')}" autocomplete="tel"></div><button class="btn primary command-save" type="submit">Сохранить изменения <span aria-hidden="true">↗</span></button></form></article>
 </div>${accountSettings(true)}`;
}
function leadershipDirectory(){
 const people=Array.isArray(leadershipDirectoryCache)
   ? leadershipDirectoryCache
   : (Array.isArray(state?.leadership_directory)?state.leadership_directory:[]);
 const cards=people.map((person,index)=>{
   const initials=esc((person.full_name||'Р').trim().split(/\s+/).map(x=>x[0]||'').slice(0,2).join('').toUpperCase());
   const links=(person.links||[]).map(x=>`<a class="leader-contact leader-contact--${esc(x.platform)}" href="${esc(x.url)}" target="_blank" rel="noopener noreferrer" aria-label="Открыть ${esc(x.label)} ${esc(x.handle)}"><span class="leader-contact-symbol">${esc(x.symbol)}</span><span class="leader-contact-copy"><strong>${esc(x.label)}</strong><small>${esc(x.handle)}</small></span><span aria-hidden="true">↗</span></a>`).join('');
   return `<article class="leader-person-card"><div class="leader-person-card-top"><span class="leader-avatar leader-avatar--${index%4}">${initials}</span><span class="leader-card-spark">✦</span></div><div class="leader-role-label">${esc(person.position)}</div><h3>${esc(person.full_name)}${person.student_id===state.student.id?'<span class="you-label">Это вы</span>':''}</h3><p class="leader-direction-label">${esc(withoutRussianFlag(person.direction_name))}</p>${person.group?`<div class="leader-group-label">Учебная группа · ${esc(person.group)}</div>`:''}<div class="leader-contacts">${links||'<div class="leader-no-contact">Публичные контакты не подключены</div>'}</div></article>`;
 }).join('');
 return `<section class="page-intro"><div class="eyebrow">PEOPLE & SUPPORT</div><h1>Руководство студсовета</h1><p>Председатель студсовета, заместители по колледжу и институту, главы направлений и их заместители. Только подтверждённые контакты.</p></section>${cards?`<div class="leadership-directory-grid">${cards}</div>`:'<div class="empty state-empty"><b>Руководство пока не назначено</b></div>'}`;
}
async function fetchLeadershipDirectory({silent=false}={}){
 if(leadershipDirectoryBusy)return;
 leadershipDirectoryBusy=true;
 try{
  const d=await api('/student-app/api/leadership-directory');
  // A transient malformed response must not erase a previously loaded roster.
  if(Array.isArray(d.cards)){
   leadershipDirectoryCache=d.cards;
   leadershipDirectoryLoadedAt=Date.now();
   if(state)state.leadership_directory=leadershipDirectoryCache;
   if(activeTab==='leadership')render();
  }
 }catch(e){if(!silent)toast(e.message)}
 finally{leadershipDirectoryBusy=false;}
}

function leader(){return '<div id="leader-box" class="glass card"><div class="loading">Загружаем заявки…</div></div>'}
function registration(){
 if(registrationStarted)return `<div class="registration"><div class="glass card"><div class="eyebrow">STUDENT COUNCIL · КОМАНДА</div><h1>Создайте профиль</h1><p class="muted">Один кабинет для ваших направлений, заявлений и расписания.</p><form class="form" data-submit="register"><div class="field"><label>Учебный контур</label><select class="select" name="education_type"><option value="institute">Институт</option><option value="college">Колледж</option></select></div><div class="field"><label>ФИО</label><input class="input" name="full_name" placeholder="Иванов Иван Иванович" required></div><div class="field"><label>Учебная группа</label><input class="input" name="group" placeholder="ИВТ-21" required></div><div class="field"><label>Телефон</label><input class="input" name="phone" placeholder="+7 900 000-00-00" required></div><div class="notice">Заполните данные профиля, чтобы выбрать направления и подать заявление.</div><div class="actions"><button class="btn" type="button" data-action="back-registration">‹ Назад</button><button class="btn primary" style="flex:1" type="submit">Создать профиль</button></div></form></div></div>`;
 return `<div class="registration"><div class="glass card"><div class="eyebrow">STUDENT COUNCIL · WELCOME ABOARD</div><h1>Добро пожаловать!</h1><p class="muted">Ваш личный кабинет объединяет профиль, направления, заявления и расписание.</p><button class="btn primary full" data-action="start-registration">🏛 Создать профиль студсовета</button></div></div>`;
}
function updateStudentNav(){
 const app=document.getElementById('app');if(!app)return;
 const student=state?.student||{};
 const headerTitle=app.querySelector('.hero .title');
 const headerSubtitle=headerTitle?.parentElement?.querySelector('.muted');
 if(headerTitle)headerTitle.textContent=student.full_name||'Личный кабинет';
 if(headerSubtitle)headerSubtitle.textContent=(student.education_label||'Студент')+(student.group?' · '+student.group:'');
 const topNav=app.querySelector('.nav');
 const showLeaderTab=Boolean(state?.leadership?.length);
 const existingLeaderTab=topNav?.querySelector('[data-tab="leader"]');
 if(showLeaderTab&&topNav&&!existingLeaderTab){
  const button=document.createElement('button');button.type='button';button.dataset.action='tab';button.dataset.tab='leader';button.textContent='Заявки команды';topNav.appendChild(button);
 }else if(!showLeaderTab&&existingLeaderTab){existingLeaderTab.remove()}
 const bottomTab=['leadership','leader','more'].includes(activeTab)?'more':activeTab;
 app.querySelectorAll('.nav [data-action="tab"]').forEach(button=>{
  const active=button.dataset.tab===activeTab;
  button.classList.toggle('active',active);
  button.setAttribute('aria-current',active?'page':'false');
 });
 app.querySelectorAll('.mission-bottom-nav [data-action="tab"]').forEach(button=>{
  const active=button.dataset.tab===bottomTab;
  button.classList.toggle('active',active);
  button.setAttribute('aria-current',active?'page':'false');
 });
}
function animateStudentContent(container){
 if(!container||studentReduceEffects)return;
 let nodes=[...container.children];
 // On overview/calendar views, stagger the meaningful work panels rather than fading one huge wrapper.
 if(nodes.length===1&&nodes[0].matches('.command-dashboard,.student-calendar-shell,.registration'))nodes=[...nodes[0].children];
 nodes=nodes.slice(0,8);
 nodes.forEach(node=>{node.classList.remove('student-content-arrival');node.style.removeProperty('--student-arrival-delay')});
 void container.offsetWidth;
 nodes.forEach((node,index)=>{
  node.style.setProperty('--student-arrival-delay',`${Math.min(index,5)*54}ms`);
  const done=event=>{
   if(event.target!==node||event.animationName!=='student-content-arrival')return;
   node.classList.remove('student-content-arrival');node.style.removeProperty('--student-arrival-delay');node.removeEventListener('animationend',done);
  };
  node.addEventListener('animationend',done);
  node.classList.add('student-content-arrival');
 });
}
function render(options={}){
 const app=document.getElementById('app');if(!state||!app)return;
 studentAppDirty=false;
 if(!state.registered){
  declineModalEventId=null;eventModalId=null;lessonModalId=null;lastRenderedStudentTab=null;
  app.innerHTML=`<div class="student-registration-view">${registration()}</div>`;
  if(options.motion!==false)animateStudentContent(app.querySelector('.student-registration-view'));
  return;
 }
 const shouldAnimate=typeof options.motion==='boolean'?options.motion:lastRenderedStudentTab!==activeTab;
 const previousMain=app.querySelector('#student-main');
 const openDetails=[...(previousMain||app).querySelectorAll('details.mission-student-disclosure[open]')].map(x=>x.id);
 const views={home,apps,calendar:schedule,events:schedule,schedule,more,leadership:leadershipDirectory,leader};
 const view=views[activeTab]||home;
 const content=view();
 // Keep the header, both navigation bars and root node alive between tabs. Only the view body changes.
 if(!previousMain){
  app.innerHTML=shell()+`<main class="student-main" id="student-main" tabindex="-1"></main><div id="student-overlays"></div>`;
 }
 const main=app.querySelector('#student-main');
 main.innerHTML=content;
 let overlays=app.querySelector('#student-overlays');
 if(!overlays){overlays=document.createElement('div');overlays.id='student-overlays';app.appendChild(overlays)}
 overlays.innerHTML=eventModalMarkup()+lessonDetail()+declineModalMarkup();
 updateStudentNav();
 openDetails.forEach(id=>{const el=document.getElementById(id);if(el)el.open=true;});
 document.body.classList.toggle('mission-modal-open',Boolean(eventModalId||lessonModalId!==null||declineModalEventId));
 if(eventModalId||lessonModalId!==null||declineModalEventId){const dialog=app.querySelector('[role=dialog]');if(dialog){dialog.setAttribute('tabindex','-1');dialog.focus({preventScroll:true})}}
 if(shouldAnimate)animateStudentContent(main);
 lastRenderedStudentTab=activeTab;
 if(activeTab==='leader')loadLeadershipPanel();
}
function setTab(t){activeTab=(t==='events'||t==='schedule'?'calendar':t);render();window.scrollTo({top:0,behavior:'instant'});if(activeTab==='leadership')fetchLeadershipDirectory();if(activeTab==='more')loadAccountSettings()}
function openHomeSection(id){activeTab='home';render({motion:false});const target=document.getElementById(id);const disclosure=target?.closest('details');if(disclosure)disclosure.open=true;if(target){requestAnimationFrame(()=>target.scrollIntoView({block:'start',behavior:studentReduceEffects?'instant':'smooth'}))}}
async function reload(msg){state=await api('/student-app/api/me');if(msg)toast(msg);render()}
async function register(ev){ev.preventDefault();const f=new FormData(ev.target);try{const x=await api('/student-app/api/register',{method:'POST',body:JSON.stringify({education_type:f.get('education_type'),full_name:f.get('full_name'),group:f.get('group'),phone:f.get('phone')})});activeTab='apps';await reload(x.message);render()}catch(e){toast(e.message)}}
async function applyDir(id){try{const x=await api('/student-app/api/applications',{method:'POST',body:JSON.stringify({direction_id:id})});await reload(x.message);activeTab='apps';render()}catch(e){toast(e.message)}}
async function removeApp(id){const d=state.directions.find(x=>x.id===id);const active=d?.status==='active';const promptText=active?`Покинуть направление «${d?.name||''}»? Ваше активное участие будет прекращено.`:'Отозвать заявку на участие?';if(!confirm(promptText))return;try{const x=await api(`/student-app/api/applications/${id}`,{method:'DELETE'});await reload(x.message);activeTab='apps';render()}catch(e){toast(e.message)}}
async function saveProfile(ev){ev.preventDefault();const f=new FormData(ev.target);try{const x=await api('/student-app/api/profile',{method:'PATCH',body:JSON.stringify({group:f.get('group'),phone:f.get('phone')})});await reload(x.message);activeTab='home';render()}catch(e){toast(e.message)}}
async function joinEvent(q,d){try{const x=await api(`/student-app/api/events/${q}/days/${d}`,{method:'POST',body:'{}'});await reload(x.message);activeTab='calendar';render()}catch(e){toast(e.message)}}
function declineEvent(id){const e=(state?.events||[]).find(item=>item.id===id);if(!e||e.declined)return;if(!(e.days||[]).some(d=>d.registered)){toast('Сначала запишитесь хотя бы на одну дату мероприятия');return}declineModalEventId=id;render()}
async function submitDecline(ev){ev.preventDefault();const form=ev.target;const data=new FormData(form);const category=String(data.get('reason_category')||'').trim();const details=String(data.get('details')||'').trim();if(!category){toast('Выберите причину отказа');return}if(category==='Другая причина'&&details.length<5){toast('Опишите причину минимум пятью символами');form.querySelector('[name="details"]').focus();return}const reason=details?`${category}: ${details}`:category;try{const x=await api(`/student-app/api/events/${declineModalEventId}/decline`,{method:'POST',body:JSON.stringify({reason})});declineModalEventId=null;activeTab='calendar';await reload(x.message)}catch(e){toast(e.message)}}
async function returnToEvent(id){try{const x=await api(`/student-app/api/events/${id}/return`,{method:'POST',body:'{}'});declineModalEventId=null;activeTab='calendar';await reload(x.message)}catch(e){toast(e.message)}}
async function loadLeadershipPanel(){const box=document.getElementById('leader-box');if(!box)return;try{const d=await api('/student-app/api/leadership');if(!d.authorized){box.innerHTML='<div class="empty">Раздел недоступен.</div>';return}let h='<div class="section-title" style="margin-top:0"><h2>Заявки на рассмотрение</h2><span>'+d.applications.length+'</span></div>';if(!d.applications.length)h+='<div class="empty">Новых заявок нет.</div>';else d.applications.forEach(x=>h+=`<div class="glass card"><div class="row space"><div><b>${esc(x.full_name)}</b><div class="muted" style="font-size:9px">${esc(x.direction)} · ${esc(x.group||'Группа не указана')}</div></div><span class="badge warn">${esc(statusText(x.status))}</span></div><div class="actions"><button class="btn success" data-action="decision" data-student-id="${x.student_id}" data-direction-id="${x.direction_id}" data-decision="approve">Принять и активировать</button><button class="btn danger" data-action="decision" data-student-id="${x.student_id}" data-direction-id="${x.direction_id}" data-decision="reject">Отклонить</button></div></div>`);box.innerHTML=h}catch(e){box.innerHTML='<div class="error">'+esc(e.message)+'</div>'}}
async function decision(student,direction,action){let reason;if(action==='reject'){reason=window.prompt('Укажите причину отказа (не менее 5 символов):');if(reason===null)return;reason=reason.trim();if(reason.length<5){toast('Причина отказа должна содержать не менее 5 символов');return}}try{const x=await api(`/student-app/api/leadership/${student}/${direction}`,{method:'POST',body:JSON.stringify({action,reason})});toast(x.message);render()}catch(e){toast(e.message)}}
let initialLoadId=0;
async function load(attempt=0){
 if(attempt>0&&studentAppDirty)return; // Do not erase a partly completed form.
 const current=++initialLoadId;
 try{
  const fresh=await api('/student-app/api/me');
  if(attempt>0&&studentAppDirty)return;
  state=fresh;
  render();
  if(studentSavedScrollY!==null){const y=studentSavedScrollY;studentSavedScrollY=null;window.requestAnimationFrame(()=>window.scrollTo(0,y))}
  
 }catch(e){
  if(current!==initialLoadId)return;
  const appRoot=document.getElementById('app');
  if(appRoot)appRoot.innerHTML='<div class="glass error" role="alert"><h2>Не удалось загрузить кабинет</h2><p>'+esc(e.message)+'</p><p class="muted">Проверьте соединение. Заявления и события остаются на сервере.</p><button type="button" class="btn primary" data-pro-retry-load>Повторить загрузку</button></div>';
  // Repeat only the initial safe GET request; never replay form submissions.
  if(attempt<2)window.setTimeout(()=>{
   if(current===initialLoadId&&!studentAppDirty&&navigator.onLine!==false&&!document.hidden)load(attempt+1);
  },attempt===0?2500:6500);
 }
}
function bindDelegatedHandlers(){const app=document.getElementById('app');if(!app||app.dataset.handlersBound)return;app.dataset.handlersBound='1';app.addEventListener('input',event=>{if(event.target.closest('form'))studentAppDirty=true});app.addEventListener('change',event=>{if(event.target.closest('form'))studentAppDirty=true});app.addEventListener('click',event=>{const el=event.target.closest('[data-action]');if(!el||!app.contains(el))return;const d=el.dataset;switch(d.action){case'tab':setTab(d.tab);break;case'open-home-section':openHomeSection(d.target);break;case'schedule-period':schedulePeriod=d.period;render();break;case'calendar-prev':calendarCursor=new Date(calendarCursor.getFullYear(),calendarCursor.getMonth()-1,1);calendarChosen=`${calendarCursor.getFullYear()}-${String(calendarCursor.getMonth()+1).padStart(2,'0')}-01`;schedulePeriod='month';render();break;case'calendar-next':calendarCursor=new Date(calendarCursor.getFullYear(),calendarCursor.getMonth()+1,1);calendarChosen=`${calendarCursor.getFullYear()}-${String(calendarCursor.getMonth()+1).padStart(2,'0')}-01`;schedulePeriod='month';render();break;case'calendar-today':calendarCursor=new Date(new Date().getFullYear(),new Date().getMonth(),1);calendarChosen=new Date().toLocaleDateString('sv-SE');schedulePeriod='month';render();break;case'calendar-day':calendarChosen=d.date;calendarCursor=new Date(Number(d.date.slice(0,4)),Number(d.date.slice(5,7))-1,1);schedulePeriod='month';render();break;case'calendar-type':calendarKind=d.kind;render();break;case'notice-open':noticeModalId=Number(d.id);render();break;case'notice-close':if(el===event.target||event.target.closest('button')){noticeModalId=null;render()}break;case'download-lesson':saveLessonCalendar(Number(d.lessonId));break;case'open-lesson':lessonModalId=Number(d.id);render();break;case'close-lesson-modal':if(event.target===el||el.classList.contains('event-modal-close')||el.closest('.event-modal-bottom')){lessonModalId=null;render()}break;case'scroll-section':{const target=document.getElementById(d.target);if(target){target.scrollIntoView({behavior:window.matchMedia?.('(prefers-reduced-motion: reduce)').matches?'auto':'smooth',block:'start'})}break;}case'remove-app':removeApp(Number(d.id));break;case'apply-dir':applyDir(Number(d.id));break;case'open-event':eventModalId=Number(d.id);render();break;case'close-event-modal':if(event.target===el||el.classList.contains('event-modal-close')||el.closest('.event-modal-bottom')){eventModalId=null;declineModalEventId=null;render()}break;case'join-event':joinEvent(Number(d.quotaId),Number(d.dayId));break;case'decline-event':declineEvent(Number(d.id));break;case'return-event':returnToEvent(Number(d.id));break;case'close-decline-modal':if(event.target===el||el.classList.contains('decline-modal-close')||el.closest('.decline-modal-actions')){declineModalEventId=null;render()}break;case'start-registration':activeTab='home';registrationStarted=true;render();break;case'back-registration':registrationStarted=false;render();break;case'decision':decision(Number(d.studentId),Number(d.directionId),d.decision);break;case'account-refresh':loadAccountSettings(true);break;case'account-review':reviewAccountLink(Number(d.requestId),d.approve==='true');break;case'account-confirm-unlink':unlinkAccount(d.platform);break;case'account-copy-code':if(accountCodeResult?.code){if(navigator.clipboard?.writeText)navigator.clipboard.writeText(accountCodeResult.code).then(()=>toast('Код скопирован')).catch(()=>toast('Не удалось скопировать — выделите код вручную'));else toast('Выделите и скопируйте код вручную')}break;}});app.addEventListener('keydown',event=>{if((event.key==='Enter'||event.key===' ')&&event.target.matches('.event-preview')){event.preventDefault();eventModalId=Number(event.target.dataset.id);render()}});app.addEventListener('submit',event=>{const form=event.target.closest('form[data-submit]');if(!form||!app.contains(form))return;switch(form.dataset.submit){case'register':register(event);break;case'save-profile':saveProfile(event);break;case'decline-reason':submitDecline(event);break;case'account-generate':generateAccountLink(event);break;}})}
// Live sync: monitor a cheap, privacy-safe server revision every 5 seconds.
// Fetch the full profile only after a change; never interrupt editing or dialogs.
let studentSyncRevision=null, studentSyncBusy=false, studentSyncLastFull=Date.now();
const STUDENT_SYNC_INTERVAL=5000, STUDENT_SYNC_FALLBACK=60000;
let studentSyncTimer=0;
function scheduleStudentSync(delay=STUDENT_SYNC_INTERVAL){
 if(studentSyncTimer)window.clearTimeout(studentSyncTimer);
 studentSyncTimer=0;
 if(document.visibilityState!=='visible')return;
 studentSyncTimer=window.setTimeout(async()=>{
  studentSyncTimer=0;
  await syncStudentApp();
  scheduleStudentSync(STUDENT_SYNC_INTERVAL);
 },Math.max(0,delay));
}
function canApplyStudentUpdate(){
  if(document.visibilityState!=='visible'||!navigator.onLine||studentAppDirty)return false;
  if(eventModalId!==null||lessonModalId!==null||declineModalEventId!==null)return false;
  const active=document.activeElement;
  return !(active&&active.matches('input,textarea,select,[contenteditable="true"]'));
}
function preserveStudentView(){
  try{sessionStorage.setItem('student-app-live-view',JSON.stringify({tab:activeTab,period:schedulePeriod,
    chosen:calendarChosen,scroll:window.scrollY,at:Date.now()}));}catch(_){/* optional */}
}
let studentSavedScrollY=null;
function restoreStudentView(){
  try{
    const raw=sessionStorage.getItem('student-app-live-view');
    if(!raw)return;
    sessionStorage.removeItem('student-app-live-view');
    const saved=JSON.parse(raw);
    if(Date.now()-saved.at>30000)return;
    if(['home','calendar','apps','leadership','leader','more'].includes(saved.tab))activeTab=saved.tab;
    if(['upcoming','month'].includes(saved.period))schedulePeriod=saved.period;
    if(/^\d{4}-\d{2}-\d{2}$/.test(saved.chosen||''))calendarChosen=saved.chosen;
    studentSavedScrollY=Number(saved.scroll)||0;
  }catch(_){/* optional */}
}
async function syncStudentApp(){
  if(!state||document.visibilityState!=='visible'||!navigator.onLine||studentSyncBusy)return;
  studentSyncBusy=true;
  try{
    const signal=await api('/student-app/api/sync-state');
    if(!signal.revision)return;
    const revisionChanged=studentSyncRevision!==signal.revision;
    // Visual settings are safe to apply even while a form is open; only profile refreshes wait for a safe screen.
// Apply visual settings even during editing; profile replacement still waits for a safe screen.
    // Compare the variables as well as the theme key so same-theme palette edits propagate live.
    let visualThemeChanged=false;
    if(signal.season&&signal.season!==document.body.dataset.season){
      document.body.dataset.season=signal.season;
      document.body.dataset.theme=signal.season;
      visualThemeChanged=true;
    }
    if(signal.theme_vars&&typeof signal.theme_vars==='object'){
      Object.entries(signal.theme_vars).forEach(([name,value])=>{
        if(!/^[a-z0-9-]+$/.test(name)||typeof value!=='string')return;
        const safeColor=/^#[0-9a-f]{3,8}$/i.test(value);
        const safeRgb=/^\d{1,3},\s*\d{1,3},\s*\d{1,3}$/.test(value);
        if(!safeColor&&!safeRgb)return;
        if(document.body.style.getPropertyValue(`--${name}`).trim()!==value.trim())visualThemeChanged=true;
        document.body.style.setProperty(`--${name}`,value);
      });
      const meta=document.querySelector('meta[name="theme-color"]');
      if(meta&&signal.theme_vars['season-bg-b'])meta.content=signal.theme_vars['season-bg-b'];
    }
    if(visualThemeChanged&&!window.matchMedia?.('(prefers-reduced-motion: reduce)').matches){
      document.body.classList.remove('theme-changing'); void document.body.offsetWidth; document.body.classList.add('theme-changing');
      window.setTimeout(()=>document.body.classList.remove('theme-changing'),1400);
    }
    // Keep the visible leadership directory fresh without coupling it to /api/me.
    // A failed refresh leaves the last known-good roster in the independent cache.
    if(activeTab==='leadership'&&canApplyStudentUpdate()&&Date.now()-leadershipDirectoryLoadedAt>=60000){
      void fetchLeadershipDirectory({silent:true});
    }
    // Continue below: the same signal may also contain a new membership decision.
    if(!canApplyStudentUpdate()||noticeModalId!==null)return; // Don't replace an open dialog or draft.
    if(signal.build&&signal.build!==document.body.dataset.build){
      // Do not discard a draft: canApplyStudentUpdate() has already confirmed
      // there are no open dialogs, focused fields or unsaved form edits.
      preserveStudentView();
      const reloadKey='student-app-build-v61:'+signal.build;
      try{sessionStorage.setItem(reloadKey,'1')}catch(_){/* reload remains safe */}
      window.location.reload();
      return;
    }
    if(!revisionChanged&&Date.now()-studentSyncLastFull<STUDENT_SYNC_FALLBACK)return;
    const fresh=await api('/student-app/api/me');
    if(!canApplyStudentUpdate())return;
    studentSyncRevision=signal.revision;
    studentSyncLastFull=Date.now();
    const oldStatuses=new Map((state?.directions||[]).map(item=>[Number(item.id),String(item.status||'')]));
    const newlyActivated=(fresh?.directions||[]).filter(item=>
      ['active','approved'].includes(String(item.status||''))&&
      ['pending','interview'].includes(oldStatuses.get(Number(item.id))||'')
    );
    if(newlyActivated.length){activeTab='home';registrationStarted=false;}
    if(JSON.stringify(fresh)!==JSON.stringify(state)){
      const y=newlyActivated.length?0:window.scrollY;
      state=fresh;render({motion:false});window.scrollTo(0,y);
      if(newlyActivated.length){
        const names=newlyActivated.map(item=>item.name||item.direction_name||'направление').slice(0,2).join(', ');
        toast('Заявка принята и активирована'+(names?' · '+names:'')+'. Добро пожаловать в личный кабинет!');
      }
    }
  }catch(_){/* Network errors are nonfatal; retry after reconnection. */}
  finally{studentSyncBusy=false;}
}

bindDelegatedHandlers();
document.addEventListener('keydown',event=>{
 if(event.key==='Tab'){const dialog=document.querySelector('.student-app-body [role=dialog]');if(dialog){const elements=[...dialog.querySelectorAll('button:not([disabled]),a[href],input:not([disabled]),select:not([disabled]),textarea:not([disabled])')];if(elements.length){const first=elements[0],last=elements[elements.length-1];if(event.shiftKey&&document.activeElement===first){event.preventDefault();last.focus()}else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first.focus()}}}return}
 if(event.key!=='Escape')return;
 if(declineModalEventId!==null){declineModalEventId=null;render();return}
 if(lessonModalId!==null){lessonModalId=null;render();return}
 if(eventModalId!==null){eventModalId=null;render()}
});
restoreStudentView();
document.addEventListener('click', event => {
 if(event.target.closest('[data-pro-retry-load]'))load();
});
load().finally(()=>scheduleStudentSync(0));
document.addEventListener('visibilitychange',()=>{
 if(document.visibilityState==='hidden'){if(studentSyncTimer)window.clearTimeout(studentSyncTimer);studentSyncTimer=0;}
 else scheduleStudentSync(0);
});
window.addEventListener('pageshow',()=>scheduleStudentSync(0),{passive:true});
window.addEventListener('online',()=>{if(!state)load().finally(()=>scheduleStudentSync(0));else scheduleStudentSync(0);});

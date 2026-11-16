"use strict";
const $ = id => document.getElementById(id);
const SUBJECTS = {
  math:{label:"الرياضيات",icon:"√x",note:"الجبر والتفاضل"},
  physics:{label:"الفيزياء",icon:"⚛",note:"قوانين الطبيعة"},
  software:{label:"هندسة البرمجيات",icon:"⌘",note:"الكود والخوارزميات"},
  electronics:{label:"هندسة الإلكترونيات",icon:"▣",note:"الدوائر والمتحكمات"}
};
const LEVELS={beginner:"مبتدئ",intermediate:"متوسط",highschool:"ثانوي",university:"جامعي"};
const PAGES={home:"الرئيسية",chat:"المحادثة الهندسية",curriculum:"مسار التعلم",quiz:"التمارين والاختبارات",projects:"المشاريع العملية",tools:"المختبر والأدوات",datasets:"إدارة بيانات التدريب",progress:"التقدم والإعدادات"};
const appState={profile:null,catalog:null,model:null,loading:false,view:"home"};
const mk = (tag,className,text) => {
  const el=document.createElement(tag);
  if(className)el.className=className;
  if(text!==undefined)el.textContent=String(text);
  return el;
};
async function api(path,options={}){
  const response=await fetch("/api/"+path,{credentials:"same-origin",headers:{"Content-Type":"application/json"},...options});
  const data=await response.json().catch(()=>({}));
  if(!response.ok) throw Error(typeof data.detail==="string"?data.detail:"تعذر تنفيذ العملية");
  return data;
}
let toastTimer;
function toast(message){
  const el=$("toast");
  el.textContent=message;
  el.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer=setTimeout(()=>el.classList.remove("show"),3900);
}
function go(view){
  if(!PAGES[view])return;
  appState.view=view;
  for(const page of Object.keys(PAGES)){
    $("view-"+page).classList.toggle("hidden",page!==view);
  }
  for(const el of document.querySelectorAll("[data-view]")){
    const active=el.dataset.view===view;
    el.classList.toggle("active",active);
    if(active)el.setAttribute("aria-current","page");
    else el.removeAttribute("aria-current");
  }
  $("page-title").textContent=PAGES[view];
  $("hero").classList.toggle("hidden",view!=="home");
  if(view==="progress")loadProgress();
  if(view==="datasets")loadExamples();
  if(view==="chat")loadHistory();
  window.scrollTo({top:0,behavior:"smooth"});
}
function subjectButton(subject,small=false){
  const meta=SUBJECTS[subject];
  const el=mk("button",small?"subject-option":"subject-card");
  el.type="button";
  el.dataset.subject=subject;
  el.classList.toggle("selected",appState.profile?.subject===subject);
  el.append(mk("span","",meta.icon),mk("strong","",meta.label));
  if(!small)el.append(mk("small","",meta.note));
  el.addEventListener("click",async()=>{await updateProfile({subject});});
  return el;
}
function renderSubjects(){
  for(const id of ["subject-picker","home-subjects"]){
    const el=$(id);el.replaceChildren();
    for(const key of Object.keys(SUBJECTS)) el.append(subjectButton(key,id==="subject-picker"));
  }
}
function updateStats(p){
  const attempted=Number(p.attempted||0),correct=Number(p.correct||0);
  const percent=attempted?Math.round(100*correct/attempted):0;
  $("attempted").textContent=attempted;
  $("correct").textContent=correct;
  $("accuracy").textContent=attempted?percent+"%":"—";
  $("rail-percent").textContent=percent+"%";
  $("progress-ring").style.setProperty("--percent",percent+"%");
  $("rail-questions").textContent=attempted;
  $("rail-correct").textContent=correct;
  $("rail-level").textContent=LEVELS[p.level]||"—";
}
async function loadProfile(){
  appState.profile=await api("profile");
  $("level").value=appState.profile.level;
  renderSubjects();
  updateStats(appState.profile);
}
async function updateProfile(update){
  if(!appState.profile)return;
  const next={subject:update.subject||appState.profile.subject,level:update.level||appState.profile.level};
  try{
    appState.profile=await api("profile",{method:"PUT",body:JSON.stringify(next)});
    $("level").value=appState.profile.level;
    renderSubjects();updateStats(appState.profile);
    $("messages").replaceChildren();
    toast("تم تغيير مجال الدراسة وتحديث إعدادات التعلم");
  }catch(e){toast(e.message);$("level").value=appState.profile.level;}
}
function addMessage(role,text){
  const list=$("messages");
  const empty=list.querySelector(".chat-empty");if(empty)empty.remove();
  const bubble=mk("div","bubble "+(role==="user"?"user":"assistant"));
  bubble.append(mk("small","",role==="user"?"أنت":"المحرك الهندسي التجريبي"),mk("div","",text));
  list.append(bubble);
  list.scrollTop=list.scrollHeight;
  return bubble;
}
function chatPlaceholder(){
  const empty=mk("div","chat-empty");
  empty.append(mk("span","","✦"),mk("strong","","ما المسألة التي تريد استكشافها؟"),mk("p","","اسأل عن قانون أوم أو خوارزمية أو مشكلة رياضية."));
  $("messages").append(empty);
}
async function loadHistory(){
  if(appState.loading)return;
  try{
    const data=await api("history");
    $("messages").replaceChildren();
    for(const m of data.messages)addMessage(m.role,m.content);
    if(!data.messages.length)chatPlaceholder();
  }catch(e){toast(e.message);}
}
async function loadProgress(){
  try{await loadProfile();}catch(e){toast(e.message);}
}
async function loadModel(){
  try{
    const m=await api("model/status");
    appState.model=m;
    const ready=Boolean(m.checkpoint_available);
    $("rail-model").textContent=ready?"أوزان متاحة • تجريبية":"لا توجد أوزان مدرّبة";
    $("model-state-label").textContent=ready?"الأوزان جاهزة للاستدلال (غير موثوقة)":"لم يتم تدريب النموذج بعد";
    $("checkpoint-badge").textContent=ready?"أوزان تجريبية متاحة":"التدريب مطلوب";
    $("model-dot").classList.toggle("ready",ready);
  }catch(e){$("rail-model").textContent="حالة النموذج غير متاحة";toast(e.message);}
}
function renderCourses(){
  const root=$("curriculum-content");root.replaceChildren();
  const subjects=appState.catalog?.curriculum||{};
  for(const [subject,courses] of Object.entries(subjects)){
    for(const c of courses){
      const card=mk("article","learning-card");
      card.append(mk("div","course-icon",SUBJECTS[subject].icon),mk("h3","",c.title),mk("p","",c.description),
                  mk("div","meta",SUBJECTS[subject].label+" • "+(LEVELS[c.level]||c.level)));
      const btn=mk("button","ghost-btn","ناقش هذا الدرس ←");
      btn.addEventListener("click",async()=>{await updateProfile({subject});go("chat");$("question").value="اشرح درس "+c.title+" بأسلوب تعليمي خطوة بخطوة";$("question").focus();});
      card.append(btn);root.append(card);
    }
  }
}
function renderProjects(projects){
  const root=$("projects-content");root.replaceChildren();
  for(const p of projects){
    const card=mk("article","learning-card");
    card.append(mk("div","course-icon",SUBJECTS[p.subject]?.icon||"✦"),mk("h3","",p.title),mk("p","",p.description),
                mk("div","meta",(SUBJECTS[p.subject]?.label||p.subject)+" • "+p.difficulty));
    const btn=mk("button","ghost-btn","استكشف المشروع ←");
    btn.addEventListener("click",async()=>{await updateProfile({subject:p.subject});go("chat");$("question").value="ساعدني في فهم وتنفيذ مشروع: "+p.title+". ابدأ بخطة تعليمية بسيطة."; $("question").focus();});
    card.append(btn);root.append(card);
  }
}
async function loadCatalog(){
  try{appState.catalog=await api("catalog");renderCourses();renderProjects(appState.catalog.projects);}
  catch(e){toast("تعذر تحميل المسارات: "+e.message);}
}
async function startQuiz(){
  const root=$("quiz-content");
  root.replaceChildren(mk("div","empty-state","جارٍ تحميل السؤال..."));
  try{
    const q=await api("quiz");
    root.replaceChildren();
    if(!q.available){root.append(mk("div","empty-state",q.message));return;}
    root.append(mk("div","overline",SUBJECTS[q.subject]?.label||q.subject),mk("h3","",q.prompt));
    for(let i=0;i<q.options.length;i++){
      const b=mk("button","option",String(i+1)+" · "+q.options[i]);b.type="button";
      b.addEventListener("click",async()=>{
        root.querySelectorAll(".option").forEach(el=>el.disabled=true);
        try{
          const result=await api("quiz/answer",{method:"POST",body:JSON.stringify({question_id:q.id,choice:i})});
          const box=mk("div","answer-result"+(result.correct?"":" incorrect"));
          box.textContent=(result.correct?"✓ إجابة صحيحة":"✕ إجابة غير صحيحة")+
            "\nالإجابة الصحيحة: "+q.options[result.correct_choice]+"\n"+result.explanation;
          root.append(box);
          await loadProfile();
        }catch(e){root.append(mk("div","answer-result incorrect",e.message));}
      });
      root.append(b);
    }
  }catch(e){root.replaceChildren(mk("div","empty-state",e.message));}
}
function renderExamples(items){
  const root=$("dataset-list");root.replaceChildren();
  $("dataset-count").textContent=items.length;
  if(!items.length){
    root.append(mk("div","empty-state","لا توجد أمثلة محفوظة في هذه الجلسة. أضف مثالًا أولًا، ثم راجعه قبل استخدامه في التدريب."));
    return;
  }
  for(const item of items){
    const article=mk("article","dataset-item");
    article.append(mk("h3","",(SUBJECTS[item.subject]?.label||item.subject)+" · "+item.question));
    article.append(mk("p","",item.answer));
    const foot=mk("div","item-footer");
    foot.append(mk("span","","مسودة مراجعة · "+new Date(item.created_at).toLocaleDateString("ar")));
    const del=mk("button","","حذف المثال");del.type="button";
    del.addEventListener("click",async()=>{
      if(!confirm("هل تريد حذف هذا المثال من مسودات التدريب؟"))return;
      try{await api("datasets/"+item.id,{method:"DELETE"});toast("تم حذف المثال");await loadExamples();}
      catch(e){toast(e.message)}
    });foot.append(del);article.append(foot);root.append(article);
  }
}
async function loadExamples(){
  try{const data=await api("datasets");renderExamples(data.examples);}
  catch(e){toast("تعذر تحميل مسودات التدريب: "+e.message);}
}
async function sendChat(e){
  e.preventDefault();
  if(appState.loading)return;
  const input=$("question"),q=input.value.trim();
  if(!q)return;
  const btn=$("send");
  appState.loading=true;btn.disabled=true;
  addMessage("user",q);input.value="";
  const pending=addMessage("assistant","جارٍ محاولة التوليد من النموذج المحلي...");
  try{
    const result=await api("chat",{method:"POST",body:JSON.stringify({question:q})});
    pending.lastChild.textContent=result.answer+"\n\nتنبيه: "+result.notice;
  }catch(err){
    pending.lastChild.textContent="لم تتوفر إجابة من النموذج: "+err.message+"\nيمكنك استخدام الاختبارات والحاسبة ومسودات البيانات دون أوزان مدرّبة.";
  }finally{appState.loading=false;btn.disabled=false;input.focus();}
}
function calculateOhm(e){
  e.preventDefault();
  const v=Number($("voltage").value),r=Number($("resistance").value);
  if(!Number.isFinite(v)||!Number.isFinite(r)||r<=0){$("ohm-result").textContent="أدخل قيمًا صحيحة؛ يجب أن تكون المقاومة أكبر من صفر.";return;}
  const i=v/r,p=v*i;
  const fmt=n=>new Intl.NumberFormat("en",{maximumSignificantDigits:6}).format(n);
  $("ohm-result").textContent="I = "+fmt(i)+" A    |    P = "+fmt(p)+" W";
}
function findLocal(query){
  const text=query.toLowerCase().trim();
  if(!text)return;
  const courses=Object.entries(appState.catalog?.curriculum||{}).flatMap(([subject,items])=>items.map(item=>({...item,subject})));
  const projects=appState.catalog?.projects||[];
  const lesson=courses.find(c=>(c.title+" "+c.description).toLowerCase().includes(text));
  const project=projects.find(p=>(p.title+" "+p.description).toLowerCase().includes(text));
  if(lesson){go("curriculum");toast("الدرس المطابق: "+lesson.title);}
  else if(project){go("projects");toast("المشروع المطابق: "+project.title);}
  else toast("لا توجد نتيجة في فهرس الدروس والمشاريع الحالي");
}
function initBindings(){
  document.querySelectorAll("[data-view]").forEach(el=>el.addEventListener("click",()=>go(el.dataset.view)));
  document.querySelectorAll("[data-go]").forEach(el=>el.addEventListener("click",()=>go(el.dataset.go)));
  $("level").addEventListener("change",e=>updateProfile({level:e.target.value}));
  $("chat-form").addEventListener("submit",sendChat);
  $("question").addEventListener("keydown",e=>{if(e.key==="Enter"&&!e.shiftKey){e.preventDefault();$("chat-form").requestSubmit();}});
  $("clear-history").addEventListener("click",async()=>{if(!confirm("مسح المحادثة الحالية؟"))return;try{await api("history",{method:"DELETE"});$("messages").replaceChildren();chatPlaceholder();toast("تم مسح المحادثة");}catch(e){toast(e.message);}});
  $("new-quiz").addEventListener("click",startQuiz);
  $("ohm-form").addEventListener("submit",calculateOhm);
  $("site-search").addEventListener("keydown",e=>{if(e.key==="Enter"){e.preventDefault();findLocal(e.target.value);}});
  document.addEventListener("keydown",e=>{if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==="k"){e.preventDefault();$("site-search").focus();}});
  $("dataset-form").addEventListener("submit",async e=>{
    e.preventDefault();
    const btn=$("save-example");
    btn.disabled=true;
    try{
      await api("datasets",{method:"POST",body:JSON.stringify({subject:$("dataset-subject").value,question:$("dataset-question").value.trim(),answer:$("dataset-answer").value.trim()})});
      $("dataset-question").value="";$("dataset-answer").value="";
      toast("تم حفظ المثال كمسودة؛ لم يتم تدريب النموذج");
      await loadExamples();
    }catch(err){toast(err.message);}
    finally{btn.disabled=false;}
  });
  $("delete-account").addEventListener("click",async()=>{
    if(!confirm("سيتم حذف بيانات هذه الجلسة ومحادثاتها ومسوداتها نهائيًا. هل تؤكد؟"))return;
    try{await api("account",{method:"DELETE"});window.location.reload();}catch(e){toast(e.message);}
  });
  $("theme-toggle").addEventListener("click",()=>{
    const light=document.documentElement.dataset.theme!=="light";
    document.documentElement.dataset.theme=light?"light":"dark";
    $("theme-toggle").textContent=light?"☀":"☾";
  });
}
async function init(){
  initBindings();go("home");
  const results=await Promise.allSettled([loadProfile(),loadCatalog(),loadModel()]);
  for(const r of results){if(r.status==="rejected")toast(r.reason?.message||"تعذر الاتصال بخادم المشروع");}
}
init();

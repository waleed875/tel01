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
let csrfToken="";
const mk = (tag,className,text) => {
  const el=document.createElement(tag);
  if(className)el.className=className;
  if(text!==undefined)el.textContent=String(text);
  return el;
};
async function api(path,options={}){
  const response=await fetch("/api/"+path,{credentials:"same-origin",headers:{"Content-Type":"application/json",...(csrfToken?{"X-CSRF-Token":csrfToken}:{})},...options});
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
  if(view==="projects"){projectStatus();loadRepositories();}
  if(view==="datasets"){loadExamples();renderTrainingJobs();}
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
    $("checkpoint-badge").textContent=m.active_job_id?"إصدار نشط #"+m.active_job_id:(ready?"أوزان تجريبية متاحة":"التدريب مطلوب");
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
const repoState={id:null,title:"",sha:null,path:"",folder:""};
function bytesToBase64(bytes){
  let parts=[];
  for(let i=0;i<bytes.length;i+=8192)parts.push(String.fromCharCode(...bytes.subarray(i,i+8192)));
  return btoa(parts.join(""));
}
async function projectStatus(){
  const state=$("gitea-state");
  try{
    const info=await api("gitea/status");
    state.textContent=info.configured?"Gitea مهيأ على الخادم":"يحتاج إعداد GITEA_OWNER وGITEA_API_TOKEN";
  }catch(e){state.textContent=e.message;}
}
async function loadRepositories(){
  try{
    const data=await api("projects");
    const root=$("repo-list");root.replaceChildren();
    if(!data.projects.length){
      root.append(mk("p","help-text","لم تُنشأ مستودعات مشاريع بعد. أنشئ مشروعك الأول محليًا."));
      return;
    }
    for(const project of data.projects){
      const box=mk("div","repo-card");
      const state=project.deletion_state||"active";
      const pending=state==="deleting"||state==="archiving"||state==="restoring";
      const button=mk("button","repo-row",project.title);
      button.type="button";button.disabled=pending;
      button.append(mk("small","",pending?"عملية غير مكتملة":state==="archived"?"مؤرشف • قراءة فقط":(SUBJECTS[project.kind]?.label||project.kind)));
      button.addEventListener("click",()=>openProject(project));
      const remove=mk("button","repo-delete",pending?"إعادة محاولة الحذف":"حذف المستودع");
      remove.type="button";
      remove.addEventListener("click",async()=>{
        if(!confirm("سيتم حذف مستودع Git للمشروع «"+project.title+"» مع جميع ملفاته وتاريخه. هل تؤكد؟"))return;
        remove.disabled=true;
        try{
          await api("projects/"+project.id,{method:"DELETE"});
          toast("تم حذف المستودع وسجل ربط المشروع");
          if(repoState.id===project.id){
            repoState.id=null;$("project-explorer").classList.add("hidden");
          }
        }catch(err){toast("لم يكتمل الحذف: "+err.message);}
        finally{await loadRepositories();}
      });
      const archive=mk("button","ghost-btn archive-control",state==="archived"||state==="restoring"?"استعادة المشروع":"أرشفة المشروع");
      archive.type="button";archive.disabled=state==="deleting";
      archive.addEventListener("click",async()=>{
        const restore=state==="archived"||state==="restoring";
        if(!confirm(restore?"استعادة المشروع للسماح بالتعديل؟":"أرشفة المشروع وجعله للقراءة فقط مع الاحتفاظ بجميع ملفات Git؟"))return;
        archive.disabled=true;
        try{
          await api("projects/"+project.id+"/"+(restore?"restore":"archive"),{method:"POST"});
          toast(restore?"تمت استعادة المشروع":"تمت أرشفة المشروع");
        }catch(err){toast("تعذر إكمال العملية: "+err.message);}
        finally{await loadRepositories();}
      });
      box.append(button,archive,remove);root.append(box);
    }
  }catch(e){toast(e.message);}
}
async function openProject(item){
  repoState.id=item.id;repoState.title=item.title;repoState.folder="";
  repoState.readOnly=item.deletion_state==="archived";
  for(const id of ["save-file","delete-file","rename-file","upload-btn"]){$(id).disabled=repoState.readOnly;}
  $("editor-revision").textContent=repoState.readOnly?"مؤرشف: القراءة والمعاينة فقط":"ملف نشط";
  $("project-explorer").classList.remove("hidden");
  $("explorer-title").textContent="ملفات "+item.title;
  $("folder-path").value="";
  $("project-file-search").value="";
  $("project-search-results").classList.add("hidden");
  resetEditor();
  await browseProject("");
  $("project-explorer").scrollIntoView({behavior:"smooth",block:"start"});
}
function resetEditor(){
  repoState.sha=null;
  repoState.path="";
  $("file-editor").value="";
  $("editor-filepath").value="";
  $("rename-destination").value="";
  $("editor-revision").textContent="ملف جديد: لن يتم تعديل ملف موجود دون اختيار إصداره.";
}
async function browseProject(path){
  if(repoState.id===null)return;
  try{
    const result=await api("projects/"+repoState.id+"/files?path="+encodeURIComponent(path));
    repoState.folder=path;
    $("folder-path").value=path;
    const root=$("project-files");root.replaceChildren();
    const parent=path.split("/").slice(0,-1).join("/");
    if(path){
      const back=mk("button","file-row","↰ المجلد الأعلى");
      back.type="button";back.addEventListener("click",()=>browseProject(parent));
      root.append(back);
    }
    for(const entry of result.files){
      const file=mk("div","file-row");
      const btn=mk("button","file-name",(entry.type==="dir"?"📁 ":"📄 ")+entry.name);
      btn.type="button";
      btn.addEventListener("click",()=>entry.type==="dir"?browseProject(entry.path):selectProjectFile(entry.path));
      file.append(btn);
      if(entry.type==="file"){
        const dl=mk("button","file-download","تنزيل");
        dl.addEventListener("click",()=>downloadFile(entry.path));file.append(dl);
      }
      root.append(file);
    }
    if(!result.files.length)root.append(mk("p","help-text","هذا المجلد فارغ."));
  }catch(e){toast("تعذر استعراض المجلد: "+e.message);}
}
async function searchProjectFiles(){
  if(repoState.id===null)return;
  const q=$("project-file-search").value.trim();
  if(q.length<2){toast("اكتب حرفين على الأقل للبحث");return;}
  const root=$("project-search-results");
  root.classList.remove("hidden");
  root.replaceChildren(mk("p","help-text","جارٍ البحث في ملفات المستودع..."));
  try{
    const result=await api("projects/"+repoState.id+"/search?query="+encodeURIComponent(q));
    root.replaceChildren();
    const status=mk("p","help-text",result.matches.length+" نتيجة"+(result.complete?"":" • النتائج جزئية: البحث محدود بحجم المستودع"));
    root.append(status);
    for(const item of result.matches){
      const row=mk("button","file-name", "📄 "+item.path);
      row.type="button";
      row.addEventListener("click",()=>selectProjectFile(item.path));
      root.append(row);
    }
  }catch(e){root.replaceChildren(mk("p","help-text",e.message));}
}

function isPreviewable(path){
  return /\.(?:pdf|png|jpe?g|gif|webp|md|markdown|txt)$/i.test(path);
}
function renderMarkdownSafely(raw){
  // Deliberately use textContent only: embedded HTML must never execute.
  const container=mk("div","preview-markdown formatted-markdown");
  let code=null;
  for(const line of raw.split("\n")){
    if(/^\s*```/.test(line)){
      if(code){code=null;}else{code=mk("pre","markdown-code");container.append(code);}
      continue;
    }
    if(code){code.append(mk("div","",line));continue;}
    const heading=line.match(/^(#{1,5})\s+(.+)$/);
    if(heading){
      const level=Math.min(heading[1].length+1,6);
      container.append(mk("h"+level,"",heading[2]));
    }else if(/^\s*[-*+]\s+/.test(line)){
      container.append(mk("div","markdown-list","• "+line.replace(/^\s*[-*+]\s+/,"")));
    }else if(!line.trim()){
      container.append(mk("div","markdown-blank",""));
    }else{
      container.append(mk("p","",line));
    }
  }
  return container;
}
function clearPreview(){
  const container=$("file-preview-content");
  container.replaceChildren();
  $("file-preview-description").textContent="حدد ملف صورة أو PDF أو Markdown لمعاينته.";
}
async function previewFile(path){
  const description=$("file-preview-description");
  const holder=$("file-preview-content");
  holder.replaceChildren();
  description.textContent="معاينة "+path;
  const url="/api/projects/"+repoState.id+"/preview?path="+encodeURIComponent(path);
  try{
    const response=await fetch(url,{credentials:"same-origin"});
    if(!response.ok){
      const error=await response.json().catch(()=>({}));
      throw Error(error.detail||"هذا الملف غير قابل للمعاينة.");
    }
    const type=response.headers.get("Content-Type")||"";
    if(type.startsWith("image/")){
      const img=mk("img","preview-image");
      const objectUrl=URL.createObjectURL(await response.blob());
      img.src=objectUrl;img.alt="معاينة "+path;
      img.onload=()=>URL.revokeObjectURL(objectUrl);
      img.onerror=()=>URL.revokeObjectURL(objectUrl);
      holder.append(img);
    }else if(type.includes("application/pdf")){
      const frame=mk("iframe","preview-pdf");
      frame.src=url;
      frame.title="معاينة PDF "+path;
      frame.setAttribute("sandbox","allow-scripts");
      frame.referrerPolicy="no-referrer";
      holder.append(frame);
      holder.append(mk("p","help-text","قد لا تدعم بعض المتصفحات عرض PDF في إطار محمي. استخدم التنزيل عند الحاجة."));
    }else{
      holder.append(renderMarkdownSafely(await response.text()));
    }
  }catch(e){holder.replaceChildren(mk("p","help-text","فشلت المعاينة: "+e.message));}
}
async function selectProjectFile(path){
  repoState.path=path;
  repoState.sha=null;
  $("editor-filepath").value=path;
  $("rename-destination").value=path;
  try{
    const info=await api("projects/"+repoState.id+"/file-metadata?path="+encodeURIComponent(path));
    repoState.sha=info.sha;
    $("editor-revision").textContent="إصدار SHA: "+info.sha;
    if(isPreviewable(path))await previewFile(path);
    else clearPreview();
    if(/\.(?:pdf|png|jpe?g|gif|webp)$/i.test(path)){
      $("file-editor").value="";
      $("editor-revision").textContent="ملف ثنائي: يمكن معاينته أو نقله أو تنزيله، وليس تحريره كنص.";
      return;
    }
    await loadProjectFile(path);
  }catch(e){toast("تعذر اختيار الملف: "+e.message);}
}
async function renameProjectFile(){
  if(repoState.id===null||!repoState.sha||!repoState.path){
    toast("اختر ملفًا موجودًا من المشروع أولًا");return;
  }
  const newPath=$("rename-destination").value.trim();
  if(!newPath||newPath===repoState.path){toast("أدخل اسمًا أو مسارًا جديدًا");return;}
  if(!confirm("هل تريد نقل "+repoState.path+" إلى "+newPath+" عبر Git Commit واحد؟"))return;
  const btn=$("rename-file");btn.disabled=true;
  try{
    const previous=repoState.path;
    await api("projects/"+repoState.id+"/rename",{
      method:"POST",body:JSON.stringify({from_path:previous,to_path:newPath,
      sha:repoState.sha,message:"Rename "+previous+" to "+newPath})
    });
    toast("تم نقل الملف بعملية Git واحدة");
    clearPreview();
    resetEditor();
    const folder=newPath.includes("/")?newPath.split("/").slice(0,-1).join("/"):"";
    await browseProject(folder);
    await selectProjectFile(newPath);
  }catch(e){toast("تعذر نقل الملف: "+e.message+"؛ أعد تحميله عند تعارض الإصدار.");}
  finally{btn.disabled=false;}
}

async function loadProjectFile(path){
  try{
    const result=await api("projects/"+repoState.id+"/file?path="+encodeURIComponent(path));
    repoState.sha=result.sha;repoState.path=path;
    $("editor-filepath").value=path;
    $("file-editor").value=result.content;
    $("editor-revision").textContent="إصدار SHA: "+result.sha+" • أي تعارض يتطلب إعادة تحميل الملف.";
    $("file-editor").focus();
  }catch(e){toast(e.message+" يمكن تنزيل الملفات الثنائية من قائمة الملفات.")}
}
async function downloadFile(path){
  try{
    const response=await fetch("/api/projects/"+repoState.id+"/download?path="+encodeURIComponent(path),{credentials:"same-origin"});
    if(!response.ok){const detail=await response.json();throw Error(detail.detail||"فشل التنزيل");}
    const blob=await response.blob();
    const url=URL.createObjectURL(blob);
    const link=document.createElement("a");
    link.href=url;link.download=path.split("/").pop();link.click();
    URL.revokeObjectURL(url);
  }catch(e){toast(e.message)}
}
async function saveProjectFile(){
  const path=$("editor-filepath").value.trim();
  const content=$("file-editor").value;
  if(!path){toast("اكتب مسار الملف");return}
  if(repoState.path&&repoState.path!==path&&repoState.sha){
    toast("لتغيير المسار اختر ملفًا جديدًا أو احتفظ بمسار الملف الحالي");return;
  }
  const btn=$("save-file");btn.disabled=true;
  try{
    const data=bytesToBase64(new TextEncoder().encode(content));
    const result=await api("projects/"+repoState.id+"/file",{
      method:"POST",body:JSON.stringify({path,content_base64:data,sha:repoState.sha,
        message:(repoState.sha?"Update ":"Create ")+path})
    });
    toast("حُفظ الملف داخل Git Commit بنجاح");
    repoState.sha=result.sha||null;repoState.path=path;
    $("editor-revision").textContent="تم الحفظ؛ SHA: "+(result.sha||"قم بتحديث الملف");
    await browseProject(path.includes("/")?path.split("/").slice(0,-1).join("/"):"");
  }catch(e){toast("تعذر الحفظ: "+e.message);}
  finally{btn.disabled=false}
}
async function deleteProjectFile(){
  if(!repoState.sha||!repoState.path){toast("اختر ملفًا موجودًا قبل الحذف");return;}
  if(!confirm("هل تريد حذف "+repoState.path+" في Git Commit جديد؟"))return;
  try{
    await api("projects/"+repoState.id+"/file",{method:"DELETE",
      body:JSON.stringify({path:repoState.path,sha:repoState.sha,message:"Delete "+repoState.path})});
    toast("حُذف الملف، ويمكن استعادته من سجل Git");
    const folder=repoState.folder;resetEditor();await browseProject(folder);
  }catch(e){toast(e.message)}
}
async function showProjectCommits(){
  const list=$("commit-list");list.classList.remove("hidden");
  try{
    const r=await api("projects/"+repoState.id+"/commits");
    list.replaceChildren();
    for(const item of r.commits){
      const commit=mk("div","commit-row",item.sha?.slice(0,10)+" · "+item.message);
      list.append(commit);
    }
    if(!r.commits.length)list.append(mk("p","help-text","لا توجد إصدارات ظاهرة."));
  }catch(e){toast(e.message)}
}
async function uploadProjectFile(event){
  event.preventDefault();
  if(repoState.id===null)return;
  const file=$("upload-file").files?.[0],path=$("upload-path").value.trim();
  if(!file||!path){toast("حدد ملفًا ومسارًا");return;}
  if(file.size>2*1024*1024){toast("حجم الملف يتجاوز 2 ميغابايت");return;}
  const btn=$("upload-btn");btn.disabled=true;
  try{
    const data=bytesToBase64(new Uint8Array(await file.arrayBuffer()));
    await api("projects/"+repoState.id+"/file",{method:"POST",
      body:JSON.stringify({path,content_base64:data,sha:null,message:"Upload "+path})});
    toast("تم رفع الملف وإنشاء Git Commit");
    $("file-upload-form").reset();
    await browseProject(repoState.folder);
  }catch(e){toast(e.message);}
  finally{btn.disabled=false}
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
  const approved=items.filter(item=>item.status==="approved").length;
  const stats=$("dataset-stats");
  if(stats) stats.textContent=approved+" معتمد • "+(items.length-approved)+" مسودة";
  if(!items.length){
    const stats=$("dataset-stats");if(stats)stats.textContent="0 معتمد • 0 مسودة";
    root.append(mk("div","empty-state","لا توجد أمثلة محفوظة في هذه الجلسة. أضف مثالًا أولًا، ثم راجعه قبل استخدامه في التدريب."));
    return;
  }
  for(const item of items){
    const article=mk("article","dataset-item");
    article.append(mk("h3","",(SUBJECTS[item.subject]?.label||item.subject)+" · "+item.question));
    article.append(mk("p","",item.answer));
    const foot=mk("div","item-footer");
    foot.append(mk("span","",(item.status==="approved"?"معتمد للتدريب":"مسودة للمراجعة")+" · "+new Date(item.created_at).toLocaleDateString("ar")));
    const review=mk("button","review-btn",item.status==="approved"?"إلغاء الاعتماد":"اعتماد للتدريب");
    review.type="button";
    review.addEventListener("click",async()=>{
      try{
        await api("datasets/"+item.id+"/review",{method:"PATCH",
          body:JSON.stringify({approved:item.status!=="approved"})});
        toast(item.status==="approved"?"تم سحب الاعتماد":"تم اعتماد المثال للمجموعة التدريبية");
        await loadExamples();
      }catch(e){toast(e.message)}
    });
    foot.append(review);
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
const TRAIN_STATES={queued:"في الانتظار",running:"قيد التدريب",completed:"اكتمل",failed:"فشل"};
async function renderTrainingJobs(){
  const root=$("training-jobs");
  if(!root)return;
  try{
    const result=await api("training/jobs");
    root.replaceChildren();
    if(!result.jobs.length){
      root.append(mk("div","empty-state","لا توجد تجارب تدريب حتى الآن. اعتمد بيانات التدريب أولًا."));
      return;
    }
    for(const job of result.jobs){
      const el=mk("article","dataset-item train-run");
      const title=mk("h3","", "تجربة #"+job.id+" · "+(TRAIN_STATES[job.state]||job.state));
      const details=mk("p","","خطوات: "+job.steps+"  •  أمثلة التدريب: "+job.training_count+
        "  •  أمثلة التحقق: "+job.validation_count+"\n"+
        "البذرة: "+job.seed+"  •  بصمة البيانات: "+job.snapshot_sha256.slice(0,12));
      el.append(title,details);
      if(job.heldout_loss!==null&&job.heldout_loss!==undefined){
        el.append(mk("p","metric-text","خسارة بيانات التقييم المحجوزة: "+Number(job.heldout_loss).toFixed(4)+
           " (مقياس لغوي فقط، ليس نسبة صحة الإجابات)"));
      }
      if(job.state==="completed"){
        const activate=mk("button","ghost-btn","تفعيل هذا الإصدار في المحادثة");
        activate.type="button";
        activate.addEventListener("click",async()=>{
          try{
            await api("training/jobs/"+job.id+"/activate",{method:"POST"});
            toast("تم اختيار الإصدار #"+job.id+" للمحادثة. لا تعتمد على مخرجاته علميًا.");
            await loadModel();
          }catch(err){toast(err.message)}
        });
        el.append(activate);
      }
      if(job.train_loss!==null&&job.train_loss!==undefined){
        el.append(mk("p","metric-text","خسارة التدريب: "+Number(job.train_loss).toFixed(4)+
          "   •   خسارة التحقق: "+Number(job.validation_loss).toFixed(4)));
      }
      if(job.error)el.append(mk("p","training-error","الخطأ: "+job.error));
      const more=mk("button","ghost-btn","عرض القياسات");more.type="button";
      more.addEventListener("click",async()=>{
        try{
          const result=await api("training/jobs/"+job.id);
          const metrics=result.metrics;
          const detail=el.querySelector(".metric-list")||mk("div","metric-list");
          detail.replaceChildren();
          if(!metrics.length)detail.append(mk("p","","لم تُسجّل خسارة بعد؛ قد تكون المهمة قيد التحضير."));
          else {
            for(const m of metrics)detail.append(
              mk("div","metric-row","خطوة "+m.step+"  |  تدريب "+Number(m.train_loss).toFixed(4)+
                "  |  تحقق "+Number(m.validation_loss).toFixed(4))
            );
          }
          if(!detail.parentNode)el.append(detail);
        }catch(err){toast(err.message)}
      });el.append(more);root.append(el);
    }
  }catch(err){root.replaceChildren(mk("div","empty-state",err.message));}
}
async function startTraining(e){
  e.preventDefault();
  const btn=$("start-training");btn.disabled=true;
  try{
    const steps=Number($("training-steps").value);
    const seed=Number($("training-seed").value);
    if(!Number.isInteger(steps)||steps<50||steps>300||!Number.isInteger(seed)||seed<0){
      throw Error("راجع عدد الخطوات والبذرة العشوائية");
    }
    const job=await api("training/jobs",{method:"POST",body:JSON.stringify({steps,seed})});
    toast("أُضيفت تجربة التدريب #"+job.id+" إلى قائمة الانتظار");
    await renderTrainingJobs();
  }catch(err){toast(err.message);}
  finally{btn.disabled=false;}
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
async function loadAuthenticatedWorkspace(){
  $("auth-gate").classList.add("hidden");
  $("auth-error").textContent="";
  const results=await Promise.allSettled([loadProfile(),loadCatalog(),loadModel()]);
  for(const r of results)if(r.status==="rejected")toast(r.reason?.message||"تعذر الاتصال بالخادم");
}
async function checkAuth(){
  try{
    const state=await api("auth/state");
    if(!state.authenticated){
      csrfToken="";
      $("auth-gate").classList.remove("hidden");
      $("legacy-claim-banner").classList.add("hidden");
      return;
    }
    csrfToken=state.csrf;
    $("logged-user").textContent=state.username.slice(0,2).toUpperCase();
    $("logged-user").title="حساب "+state.username;
    if(state.legacy_available)$("legacy-claim-banner").classList.remove("hidden");
    else $("legacy-claim-banner").classList.add("hidden");
    await loadAuthenticatedWorkspace();
  }catch(error){
    $("auth-error").textContent=error.message;
    $("auth-gate").classList.remove("hidden");
  }
}
function clearPrivateWorkspace(){
  appState.profile=null;
  repoState.id=null;
  repoState.sha=null;
  repoState.path="";
  repoState.title="";
  repoState.folder="";
  for(const id of ["messages","repo-list","project-files","project-search-results",
                    "commit-list","dataset-list","training-jobs","curriculum-content",
                    "projects-content","file-preview-content"]){
    const node=$(id);
    if(node)node.replaceChildren();
  }
  for(const id of ["file-editor","editor-filepath","rename-destination","question",
                   "project-file-search","folder-path"]){
    const node=$(id);if(node)node.value="";
  }
  $("project-explorer").classList.add("hidden");
  $("project-search-results").classList.add("hidden");
  $("legacy-claim-banner").classList.add("hidden");
}
async function logoutAuth(){
  try{await api("auth/logout",{method:"POST"});}
  catch(e){toast(e.message);return;}
  csrfToken="";
  clearPrivateWorkspace();
  $("auth-gate").classList.remove("hidden");
  $("legacy-claim-banner").classList.add("hidden");
  $("auth-password").value="";
  go("home");
}
async function claimLegacy(){
  if(!confirm("سيتم نقل المشاريع وبيانات التدريب القديمة إلى حسابك الحالي. لا يمكن عكس هذه العملية. هل تؤكد؟"))return;
  try{
    await api("auth/claim-legacy",{method:"POST"});
    $("legacy-claim-banner").classList.add("hidden");
    toast("تم نقل بيانات الجلسة القديمة إلى الحساب بنجاح");
    await loadProfile();
  }catch(e){toast(e.message);}
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
  $("project-create-form").addEventListener("submit",async e=>{
    e.preventDefault();const btn=$("project-create-btn");btn.disabled=true;
    try{
      const payload={title:$("project-title").value.trim(),kind:$("project-kind").value};
      const project=await api("projects",{method:"POST",body:JSON.stringify(payload)});
      toast("تم إنشاء مستودع Git خاص للمشروع");
      $("project-create-form").reset();
      await loadRepositories();await openProject(project);
    }catch(err){toast(err.message)}finally{btn.disabled=false}
  });
  $("browse-folder").addEventListener("click",()=>browseProject($("folder-path").value.trim()));
  $("explorer-back").addEventListener("click",()=>{
    repoState.id=null;$("project-explorer").classList.add("hidden");loadRepositories();
  });
  $("show-commits").addEventListener("click",showProjectCommits);
  $("search-project-files").addEventListener("click",searchProjectFiles);
  $("project-file-search").addEventListener("keydown",ev=>{
    if(ev.key==="Enter"){ev.preventDefault();searchProjectFiles();}
  });
  $("save-file").addEventListener("click",saveProjectFile);
  $("new-file").addEventListener("click",resetEditor);
  $("delete-file").addEventListener("click",deleteProjectFile);
  $("rename-file").addEventListener("click",renameProjectFile);
  $("close-file-preview").addEventListener("click",clearPreview);
  $("file-upload-form").addEventListener("submit",uploadProjectFile);
  $("site-search").addEventListener("keydown",e=>{if(e.key==="Enter"){e.preventDefault();findLocal(e.target.value);}});
  document.addEventListener("keydown",e=>{if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==="k"){e.preventDefault();$("site-search").focus();}});
  $("training-form").addEventListener("submit",startTraining);
  $("refresh-training").addEventListener("click",renderTrainingJobs);
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
  $("delete-account").addEventListener("click",logoutAuth);
  $("logout-button").addEventListener("click",logoutAuth);
  $("claim-legacy").addEventListener("click",claimLegacy);
  $("dismiss-legacy").addEventListener("click",()=>$("legacy-claim-banner").classList.add("hidden"));
  $("auth-form").addEventListener("submit",async event=>{
    event.preventDefault();
    const btn=$("auth-submit");
    btn.disabled=true;
    $("auth-error").textContent="";
    try{
      await api("auth/login",{method:"POST",body:JSON.stringify({
        username:$("auth-username").value.trim(),password:$("auth-password").value
      })});
      $("auth-password").value="";
      await checkAuth();
    }catch(e){$("auth-error").textContent=e.message;}
    finally{btn.disabled=false;}
  });
  $("theme-toggle").addEventListener("click",()=>{
    const light=document.documentElement.dataset.theme!=="light";
    document.documentElement.dataset.theme=light?"light":"dark";
    $("theme-toggle").textContent=light?"☀":"☾";
  });
}
async function init(){
  initBindings();
  go("home");
  await checkAuth();
}
init();

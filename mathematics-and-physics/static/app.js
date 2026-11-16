"use strict";
const $ = id => document.getElementById(id);
const views = ["chat","quiz","progress"];
let profile = null;
let waiting = false;
async function api(path, options={}) {
  const response = await fetch("/api/"+path, {credentials:"same-origin", headers:{"Content-Type":"application/json"}, ...options});
  const data = await response.json();
  if (!response.ok) throw new Error(typeof data.detail==="string"?data.detail:"حدث خطأ في الاتصال");
  return data;
}
function bubble(role, content) {
  const div=document.createElement("div");
  div.className="bubble "+role;
  const caption=document.createElement("small");
  caption.textContent=role==="user"?"سؤالك":"المحرك المحلي";
  const text=document.createElement("div");
  text.textContent=content;
  div.append(caption,text);
  $("messages").append(div);
  div.scrollIntoView({block:"nearest",behavior:"smooth"});
}
function error(message){const d=document.createElement("div");d.className="result";d.textContent=message;return d}
function view(name){
  for(const n of views){
    $("view-"+n).classList.toggle("hidden",n!==name);
    $("nav-"+n).classList.toggle("active",n===name);
  }
  $("page-title").textContent={chat:"المحادثة العلمية",quiz:"الاختبارات والتطبيق",progress:"تقدمي الدراسي"}[name];
  if(name==="progress") loadProgress();
}
async function loadProgress(){
  try{
    profile=await api("profile");
    $("attempted").textContent=profile.attempted;
    $("correct").textContent=profile.correct;
    $("accuracy").textContent=profile.attempted?Math.round(profile.correct/profile.attempted*100)+"%":"—";
  }catch(e){$("accuracy").textContent=e.message}
}
async function init(){
  for(const n of views) $("nav-"+n).addEventListener("click",()=>view(n));
  try{
    profile=await api("profile");
    $("subject").value=profile.subject;
    $("level").value=profile.level;
    const history=await api("history");
    for(const m of history.messages)bubble(m.role,m.content);
  }catch(e){$("messages").append(error(e.message))}
}
async function updateProfile(){
  try{
    profile=await api("profile",{method:"PUT",body:JSON.stringify({subject:$("subject").value,level:$("level").value})});
    $("messages").replaceChildren();
    view("chat");
  }catch(e){alert(e.message)}
}
$("subject").addEventListener("change",updateProfile);
$("level").addEventListener("change",updateProfile);
$("chat-form").addEventListener("submit",async ev=>{
  ev.preventDefault();
  if(waiting)return;
  const question=$("question").value.trim();
  if(!question)return;
  bubble("user",question);
  $("question").value="";
  waiting=true;$("send").disabled=true;
  try{
    const data=await api("chat",{method:"POST",body:JSON.stringify({question})});
    bubble("assistant",data.answer+"\n\n⚠ "+data.notice);
  }catch(e){bubble("assistant","تعذر توليد الإجابة: "+e.message)}
  finally{waiting=false;$("send").disabled=false}
});
$("question").addEventListener("keydown",ev=>{if(ev.key==="Enter"&&!ev.shiftKey){ev.preventDefault();$("chat-form").requestSubmit()}});
$("clear-history").addEventListener("click",async()=>{
 if(!confirm("هل تريد مسح المحادثة؟"))return;
 try{await api("history",{method:"DELETE"});$("messages").replaceChildren()}catch(e){alert(e.message)}
});
$("new-quiz").addEventListener("click",async()=>{
 const target=$("quiz-content");target.replaceChildren();
 try{
  const q=await api("quiz");
  if(!q.available){target.append(error(q.message));return}
  const heading=document.createElement("h3");heading.textContent=q.prompt;target.append(heading);
  for(let i=0;i<q.options.length;i++){
    const btn=document.createElement("button");btn.className="option";btn.textContent=(i+1)+". "+q.options[i];
    btn.addEventListener("click",async()=>{
      target.querySelectorAll("button").forEach(x=>x.disabled=true);
      try{const res=await api("quiz/answer",{method:"POST",body:JSON.stringify({question_id:q.id,choice:i})});
        target.append(error((res.correct?"✓ إجابة صحيحة":"✕ إجابة غير صحيحة")+"\n"+res.explanation));
      }catch(e){target.append(error(e.message))}
      const again=document.createElement("button");again.textContent="سؤال آخر";again.className="option";again.addEventListener("click",()=>{$("new-quiz").click()});target.append(again);
    });target.append(btn)
  }
 }catch(e){target.append(error(e.message))}
});
$("delete-account").addEventListener("click",async()=>{
 if(!confirm("سيتم حذف بيانات هذه الجلسة نهائيًا. هل أنت متأكد؟"))return;
 try{await api("account",{method:"DELETE"});location.reload()}catch(e){alert(e.message)}
});
init();
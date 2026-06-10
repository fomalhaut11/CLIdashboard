// ===== 通用 =====
function toast(t){ const e=document.getElementById("toast"); e.textContent=t; e.style.display="block"; }
async function jget(u){ return (await fetch(u)).json(); }
async function jpost(u,b){ return (await fetch(u,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(b)})).json(); }
function esc(s){ return (s||"").replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;"); }

// ===== 标签页 =====
document.querySelectorAll(".tab").forEach(t=>t.onclick=()=>{
  document.querySelectorAll(".tab").forEach(x=>x.classList.remove("active"));
  document.querySelectorAll(".panel").forEach(x=>x.classList.remove("active"));
  t.classList.add("active");
  document.getElementById("tab-"+t.dataset.tab).classList.add("active");
  if(t.dataset.tab==="registry") loadRegistry();
  if(t.dataset.tab==="procs") loadProcs();
  if(t.dataset.tab==="data") loadData();
  if(t.dataset.tab==="agents") loadAgents();
  if(t.dataset.tab==="streams") fit.fit();
});

// ===== 终端 =====
const fit=new FitAddon.FitAddon();
const term=new Terminal({fontFamily:"Consolas, monospace",fontSize:13,theme:{background:"#000"},cursorBlink:true});
term.loadAddon(fit); term.open(document.getElementById("term")); fit.fit();
window.addEventListener("resize",()=>{fit.fit();sendResize();});
let ws=null, activePath=null, pendingCmd=null;
function sendResize(){ if(ws&&ws.readyState===1) ws.send(JSON.stringify({r:[term.cols,term.rows]})); }
function connect(path,cmd){
  if(ws){ws.onclose=null;ws.onmessage=null;try{ws.close()}catch(e){}}  // 切换=detach, 后端 PTY 不杀
  term.reset(); activePath=path; pendingCmd=cmd||null;
  document.getElementById("cwd").textContent="终端 @ "+path;
  const proto=location.protocol==="https:"?"wss":"ws";
  ws=new WebSocket(`${proto}://${location.host}/pty?cwd=${encodeURIComponent(path)}`);
  ws.onopen=()=>{sendResize();term.focus();loadPtys();   // 后端会回放该终端最近输出
    if(pendingCmd){const c=pendingCmd;pendingCmd=null;setTimeout(()=>{if(ws&&ws.readyState===1)ws.send(JSON.stringify({i:c+"\r"}));},700);}};
  ws.onmessage=e=>term.write(e.data);
  ws.onclose=()=>term.write("\r\n\x1b[33m[已断开此视图, 终端进程仍在后台存活]\x1b[0m\r\n");
  document.querySelectorAll(".card").forEach(c=>c.classList.toggle("active",c.dataset.path===path));
}
term.onData(d=>{ if(ws&&ws.readyState===1) ws.send(JSON.stringify({i:d})); });
function sendCmd(cmd){ if(!ws||ws.readyState!==1){toast("先点某 stream 的『终端』连接");return;} ws.send(JSON.stringify({i:cmd+"\r"})); term.focus(); }

// ===== 常驻终端列表 (多 CLI 并存; 切走不杀, 点 chip 切回) =====
function samePath(a,b){ return (a||"").replace(/\\/g,"/").toLowerCase()===(b||"").replace(/\\/g,"/").toLowerCase(); }
async function loadPtys(){
  let list; try{ list=await jget("/api/pty/list"); }catch(e){ return; }
  const bar=document.getElementById("ptybar"); if(!bar) return;
  if(!list.length){ bar.innerHTML="<span class='ptyhint'>无常驻终端 — 点某卡「终端」开一个</span>"; return; }
  bar.innerHTML="<span class='ptyhint'>常驻终端:</span>"+list.map(p=>{
    const active=samePath(p.cwd,activePath)?"active":"";
    const cwd=p.cwd.replace(/\\/g,"\\\\");
    return `<span class="ptychip ${active}">
      <span onclick="connect('${cwd}')" title="${esc(p.cwd)} (点击切回)">${p.alive?'●':'○'} ${esc(p.name)}${p.clients>1?' ·'+p.clients+'人':''}</span>
      <span class="x" onclick="killPty('${p.key}')" title="关闭此终端(结束里面的进程)">×</span></span>`;
  }).join("");
}
async function killPty(key){ if(!confirm("关闭这个终端? 里面在跑的进程会被结束。"))return;
  await jpost("/api/pty/kill",{key}); setTimeout(loadPtys,300); }

// ===== Streams =====
async function addWorktree(){
  const branch=prompt("新分支名 (建议 stream/xxx):","stream/"); if(!branch)return;
  const name=prompt("worktree 目录名:","wt-"+branch.replace(/^stream\//,"").replace(/[\\/]/g,"-")); if(!name)return;
  const j=await jpost("/api/worktree",{name,branch});
  toast((j.rc===0?"[OK] 已创建 "+name:"[rc="+j.rc+"]")+"\n\n"+(j.out||"")); refreshStreams();
}
async function gitOp(path,action){ const j=await jpost("/api/git",{path,action});
  toast((j.rc===0?"[OK] ":"[rc="+j.rc+"] ")+action+"\n\n"+(j.out||"(无输出)")); refreshStreams(); }
async function setStatus(branch,status){ await jpost("/api/stream_meta",{branch,status}); refreshStreams(); }

function guardHtml(g){
  if(!g.length) return '<div class="guard"><span class="g-ok">约定: 无越界</span></div>';
  const lines=g.map(x=>`<div class="g-${x.level}">${x.level==="violation"?"✗":"!"} ${esc(x.file)} <span style="color:#6e7681">— ${esc(x.msg)}</span></div>`).join("");
  return `<div class="guard has">约定: ${g.length} 处需注意<br>${lines}</div>`;
}
function statusSel(s){
  const opts=["ACTIVE","PARKED","BLOCKED"].map(o=>`<option ${s.meta.status===o?"selected":""}>${o}</option>`).join("");
  return `<select onchange="setStatus('${s.branch}',this.value)" ${s.branch==="main"?"disabled":""}>${opts}</select>`;
}
function card(s){
  const dirty=s.staged+s.unstaged+s.untracked;
  const clean=dirty===0?'<span class="badge clean">clean</span>':`<span class="badge dirty">脏 ${dirty}</span>`;
  const ahead=s.ahead?`<span class="badge ahead">领先 ${s.ahead}</span>`:"";
  const behind=s.behind?`<span class="badge behind">落后 ${s.behind}</span>`:"";
  const stb=s.branch==="main"?"":`<span class="badge st-${s.meta.status}">${s.meta.status}</span>`;
  const p=s.path.replace(/\\/g,"\\\\");
  return `<div class="card" data-path="${s.path}">
    <div class="row1"><span class="branch">${s.branch}</span><span class="name">${s.name}</span>${statusSel(s)}</div>
    <div class="badges">${clean}${ahead}${behind}${stb}</div>
    ${s.branch==="main"?"":guardHtml(s.guard)}
    <div class="commits">${s.commits.map(c=>"· "+esc(c)).join("<br>")}</div>
    <div class="actions">
      <button class="primary" onclick="connect('${p}')">终端</button>
      <button onclick="openSessions('${p}','${esc(s.branch)}')">会话</button>
      <button onclick="openDiff('${p}','${esc(s.branch)}')">改动${dirty?` (${dirty})`:""}</button>
      <button onclick="gitOp('${p}','fetch')">fetch</button>
      <button onclick="gitOp('${p}','pull')">pull</button>
      <button onclick="gitOp('${p}','log')">log</button>
    </div></div>`;
}
async function refreshStreams(){
  try{
    const d=await jget("/api/streams");
    document.getElementById("cards").innerHTML=d.streams.map(card).join("");
    const wb=document.getElementById("wipbar");
    wb.textContent=`活跃 stream (WIP): ${d.wip_active} / 建议 ≤2`;
    wb.className="wipbar"+(d.wip_active>2?" warn":"");
    document.getElementById("meta").textContent=d.streams.length+" worktree · "+new Date().toLocaleTimeString();
    if(activePath) document.querySelectorAll(".card").forEach(c=>c.classList.toggle("active",c.dataset.path===activePath));
    loadPtys();
  }catch(e){ document.getElementById("meta").textContent="刷新失败: "+e; }
}

// ===== diff 模态 =====
let diffPath=null, diffFiles=[];
async function openDiff(path,branch){
  diffPath=path;
  document.getElementById("difftitle").textContent="改动 @ "+branch;
  document.getElementById("diffmodal").style.display="flex";
  document.getElementById("diffpre").innerHTML=""; document.getElementById("commitmsg").value="";
  diffFiles=await jget("/api/changed?path="+encodeURIComponent(path));
  document.getElementById("filelist").innerHTML=diffFiles.map((f,i)=>
    `<div class="f" data-i="${i}" onclick="showFileDiff(${i})">
       <input type="checkbox" data-file="${esc(f.file)}" onclick="event.stopPropagation()">
       <span class="st">${f.x}${f.y}</span><span>${esc(f.file)}</span></div>`).join("")||"<div style='color:#6e7681;padding:8px'>无改动</div>";
}
function colorDiff(t){ return esc(t).split("\n").map(l=>{
  if(l.startsWith("+")&&!l.startsWith("+++")) return `<span class="diff-add">${l}</span>`;
  if(l.startsWith("-")&&!l.startsWith("---")) return `<span class="diff-del">${l}</span>`;
  if(l.startsWith("@@")||l.startsWith("diff")||l.startsWith("index")) return `<span class="diff-hd">${l}</span>`;
  return l; }).join("\n"); }
async function showFileDiff(i){
  document.querySelectorAll(".filelist .f").forEach(e=>e.classList.toggle("sel",+e.dataset.i===i));
  const f=diffFiles[i];
  const j=await jget(`/api/filediff?path=${encodeURIComponent(diffPath)}&file=${encodeURIComponent(f.file)}&staged=${f.staged?1:0}`);
  document.getElementById("diffpre").innerHTML=colorDiff(j.diff||"(无 diff)");
}
function checkedFiles(){ return [...document.querySelectorAll(".filelist input:checked")].map(c=>c.dataset.file); }
async function stageSelected(unstage){
  const files=checkedFiles(); if(!files.length){toast("先勾选文件");return;}
  const j=await jpost("/api/stage",{path:diffPath,files,unstage});
  toast(j.rc===0?(unstage?"已取消暂存":"已暂存")+" "+files.length+" 个":j.out); openDiff(diffPath,document.getElementById("difftitle").textContent.replace("改动 @ ",""));
}
async function commitSelected(){
  const files=checkedFiles(), msg=document.getElementById("commitmsg").value.trim();
  if(!msg){toast("填提交信息");return;}
  const j=await jpost("/api/commit",{path:diffPath,files,message:msg});
  toast((j.rc===0?"[OK] 已提交":"[rc="+j.rc+"]")+"\n\n"+(j.out||""));
  if(j.rc===0){ closeDiff(); refreshStreams(); }
}
function closeDiff(){ document.getElementById("diffmodal").style.display="none"; }

// ===== 实验注册表 =====
let regData=[];
async function loadRegistry(){ regData=await jget("/api/registry"); renderRegistry(); }
function renderRegistry(){
  const f=document.getElementById("regfilter").value;
  const tfe=document.getElementById("regtypefilter");
  const tf=tfe?tfe.value:"";
  const rows=regData.filter(e=>(!f||e.stream===f)&&(!tf||(e.type||"")===tf)).map(e=>`<tr>
    <td>${e.id}</td><td>${esc(e.type||"")}</td><td>${esc(e.stream)}</td>
    <td>${esc(e.hypothesis||"")}</td><td>${esc(e.next||"")}</td>
    <td><span class="st-pill st-${(e.status||"RUNNING").replace(" ","-")}">${esc(e.status||"RUNNING")}</span></td>
    <td>${["RUNNING","PASS","HONEST-FAIL"].map(s=>`<button onclick="regSet(${e.id},'${s}')">${s[0]}</button>`).join("")}
        <button onclick="regNext(${e.id})" title="更新下一步">→</button>
        <button onclick="regDel(${e.id})">×</button></td></tr>`).join("");
  document.getElementById("regtable").innerHTML=`<table><tr><th>id</th><th>类型</th><th>stream</th>
    <th>假设/目标</th><th>下一步</th><th>结论</th><th>操作</th></tr>${rows}</table>`;
}
function showRegForm(){
  const el=document.getElementById("regform");
  el.style.display=el.style.display==="none"?"grid":"none";
  el.innerHTML=`
    <label>类型<select id="rf_type"><option value="research">research</option><option value="dev">dev</option><option value="replication">replication</option></select></label>
    <label>stream<select id="rf_stream"><option>etf-timing</option><option>index-enhance</option><option>factor-replicate</option><option>regime-style</option><option>main/shared</option></select></label>
    <label>日期<input id="rf_date" value="${new Date().toISOString().slice(0,10)}"></label>
    <label class="full">假设/目标 (hypothesis)<input id="rf_hyp"></label>
    <label class="full">kill 准则 (research 用)<input id="rf_kill"></label>
    <label class="full">下一步 (next)<input id="rf_next"></label>
    <label>FactorStore 版本<input id="rf_ver"></label>
    <label>链接<input id="rf_link"></label>
    <div class="full"><button class="primary" onclick="regAdd()">保存</button></div>`;
}
async function regAdd(){
  const e={type:rf_type.value,stream:rf_stream.value,date:rf_date.value,hypothesis:rf_hyp.value,kill:rf_kill.value,
           next:rf_next.value,version:rf_ver.value,link:rf_link.value,status:"RUNNING"};
  if(!e.hypothesis){toast("填假设/目标");return;}
  await jpost("/api/registry",{op:"add",entry:e}); document.getElementById("regform").style.display="none"; loadRegistry();
}
async function regSet(id,status){ await jpost("/api/registry",{op:"update",id,fields:{status}}); loadRegistry(); }
async function regNext(id){ const cur=(regData.find(x=>x.id===id)||{}).next||"";
  const v=prompt("下一步:",cur); if(v===null)return;
  await jpost("/api/registry",{op:"update",id,fields:{next:v}}); loadRegistry(); }
async function regDel(id){ if(confirm("删除实验 "+id+"?")){ await jpost("/api/registry",{op:"delete",id}); loadRegistry(); } }

// ===== 进程 =====
let procSel=null, procTimer=null;
async function startJob(cmd,label){ const j=await jpost("/api/proc/start",{path:activePath,cmd,label}); if(j.id){procSel=j.id;} loadProcs(); }
async function startCustom(){ const cmd=document.getElementById("customcmd").value.trim(); if(!cmd)return;
  await jpost("/api/proc/start",{path:activePath,cmd,label:cmd}); document.getElementById("customcmd").value=""; loadProcs(); }
async function loadProcs(){
  const list=await jget("/api/proc/list");
  document.getElementById("proclist").innerHTML=list.map(p=>`
    <div class="procitem ${p.id===procSel?"sel":""}" onclick="selProc(${p.id})">
      <div class="lbl"><span class="dot ${p.status}"></span>${esc(p.label)} <span style="color:#6e7681">#${p.id}</span></div>
      <div class="sub">${p.status}${p.rc!==null?" rc="+p.rc:""} · ${p.started} · ${esc(p.path)}</div>
      ${p.status==="running"?`<button onclick="event.stopPropagation();stopProc(${p.id})">停止</button>`:""}
    </div>`).join("")||"<div style='color:#6e7681'>无进程</div>";
  if(procSel) showProcLog();
  if(procTimer) clearTimeout(procTimer);
  if(document.getElementById("tab-procs").classList.contains("active")) procTimer=setTimeout(loadProcs,2000);
}
function selProc(id){ procSel=id; loadProcs(); }
async function showProcLog(){ if(!procSel)return; const j=await jget("/api/proc/log?id="+procSel);
  const pre=document.getElementById("proclog"); const atBottom=pre.scrollHeight-pre.scrollTop-pre.clientHeight<40;
  pre.textContent=j.text||"(无输出)"; if(atBottom) pre.scrollTop=pre.scrollHeight; }
async function stopProc(id){ await jpost("/api/proc/stop",{id}); loadProcs(); }
async function clearProcs(){ await jpost("/api/proc/clear",{}); loadProcs(); }

// ===== 会话恢复 (窗口关了, 对话还在盘上; claude + codex 双源) =====
let sessPath=null;
function sessSection(title,list,kind){
  if(!list||!list.length)
    return `<div class="sesssec"><div class="sesshd">${title} (0)</div><div style="color:#6e7681;padding:6px">无</div></div>`;
  return `<div class="sesssec"><div class="sesshd">${title} (${list.length})</div>`+
    list.map(s=>`<div class="procitem">
      <div class="lbl">${esc(s.name||s.preview||"(无预览)")}</div>
      <div class="sub">${s.mtime} · ${s.size_kb} KB · ${esc(s.id)}</div>
      <div style="margin-top:6px;display:flex;gap:6px">
        <button class="primary" onclick="resumeSession('${kind}','${s.id}')">恢复</button>
        <button onclick="copyResume('${kind}','${s.id}')">复制命令</button>
      </div></div>`).join("")+`</div>`;
}
async function openSessions(path,branch){
  sessPath=path;
  document.getElementById("sesstitle").textContent="会话 @ "+branch+" — 点「恢复」在该 worktree 接回 (claude / codex)";
  document.getElementById("sessmodal").style.display="flex";
  document.getElementById("sesslist").innerHTML="加载中...";
  document.getElementById("sessdir").textContent="";
  const [cc,cx]=await Promise.all([
    jget("/api/sessions?path="+encodeURIComponent(path)),
    jget("/api/codex_sessions?path="+encodeURIComponent(path))
  ]);
  document.getElementById("sessdir").textContent="claude: "+(cc.dir||"-")+"   |   codex: "+(cx.dir||"-");
  document.getElementById("sesslist").innerHTML=
    sessSection("Claude 会话",cc.sessions,"claude")+sessSection("Codex 会话",cx.sessions,"codex");
}
function closeSess(){ document.getElementById("sessmodal").style.display="none"; }
function safeId(id){ return /^[0-9a-fA-F-]{8,64}$/.test(id||"") ? id : ""; }
function resumeCmd(kind,id){ id=safeId(id); if(!id){ toast("会话 id 非法, 拒绝"); return ""; }
  return kind==="codex" ? "codex resume "+id : "claude -r "+id; }
function resumeSession(kind,id){
  const cmd=resumeCmd(kind,id); if(!cmd) return;
  const path=sessPath; closeSess();
  document.querySelector('.tab[data-tab="streams"]').click();
  connect(path,cmd);
  toast("正在 "+path+" 恢复 "+kind+" 会话 "+id.slice(0,8)+" ...");
}
function copyResume(kind,id){ const c=resumeCmd(kind,id); if(!c) return;
  if(navigator.clipboard) navigator.clipboard.writeText(c); toast("已复制: "+c); }

// ===== 后台 Agent — 在跑 coding agent 的统一视图: 分支 + 最近在干啥 (8s 自动刷新) =====
let agentTimer=null;
function scheduleAgents(){
  if(agentTimer) clearTimeout(agentTimer);
  if(document.getElementById("tab-agents").classList.contains("active")) agentTimer=setTimeout(loadAgents,8000);
}
async function loadAgents(){
  const w=document.getElementById("agentwrap");
  let d; try{ d=await jget("/api/agents"); }catch(e){ w.innerHTML="<div style='color:#f85149'>请求失败</div>"; scheduleAgents(); return; }
  if(!d.ok){ w.innerHTML="<div style='color:#f85149'>读取失败: "+esc(d.error||"")+"</div>"; scheduleAgents(); return; }
  if(!d.agents.length){
    w.innerHTML="<div style='color:#6e7681'>当前无在跑 agent。"+(d.raw?"<pre class='proclog' style='margin-top:8px'>"+esc(d.raw)+"</pre>":"")+"</div>"; scheduleAgents(); return; }
  w.innerHTML=d.agents.map(a=>{
    const id=a.sessionId||a.id||"", st=a.status||"?";
    const dot=(st==="busy"||st==="running")?"running":"exited";
    const cwd=(a.cwd||"").replace(/\\/g,"\\\\");
    const br=a.branch?`<span class="badge ahead">${esc(a.branch)}</span>`:"";
    const wt=a.worktree?`<span style="color:#6e7681">${esc(a.worktree)}</span>`:"";
    const act=(a.last_user||a.last_asst)?
      `<div class="agentact">${a.last_user?`<div class="au">▶ ${esc(a.last_user)}</div>`:""}${a.last_asst?`<div class="aa">↳ ${esc(a.last_asst)}</div>`:""}</div>`:"";
    return `<div class="procitem">
      <div class="lbl"><span class="dot ${dot}"></span>${esc(a.kind||"agent")} · ${esc(st)} ${br} ${wt} <span style="color:#6e7681">pid ${a.pid||"?"}</span></div>
      <div class="sub">${esc(a.cwd||"")}</div>
      ${act}
      ${id&&cwd?`<div style="margin-top:6px"><button onclick="attachAgent('${cwd}','${id}')">在终端接入</button></div>`:""}
    </div>`; }).join("");
  scheduleAgents();
}
function attachAgent(cwd,id){
  id=safeId(id); if(!id){ toast("会话 id 非法, 拒绝"); return; }
  document.querySelector('.tab[data-tab="streams"]').click();
  connect(cwd,"claude -r "+id); toast("接入会话 "+id.slice(0,8)+" @ "+cwd);
}

// ===== 数据 =====
async function loadData(){
  const d=await jget("/api/data/overview");
  const counts=d.counts.map(c=>`<div class="datacard"><div class="k">${esc(c.label)}</div><div class="v">${c.count}</div></div>`).join("");
  const ver=`<div class="datacard"><div class="k">store_v2 激活版本</div><div class="v" style="font-size:14px">${esc(d.store_v2_version||"-")}</div></div>`;
  const rows=d.datasets.map(x=>{
    if(!x.exists) return `<tr><td>${esc(x.label)}</td><td class="missing">缺失</td><td>${esc(x.rel)}</td><td></td><td></td></tr>`;
    const cls=x.stale?"stale":"fresh";
    return `<tr><td>${esc(x.label)}</td><td class="${cls}">${x.stale?"过期":"新鲜"}</td>
      <td>${esc(x.rel)}</td><td>${x.mtime} (${x.age_days}d)</td><td>${x.size_mb} MB</td></tr>`;
  }).join("");
  document.getElementById("datawrap").innerHTML=`
    <div style="color:#8b949e;font-size:12px;margin-bottom:10px">data_root: ${esc(d.data_root)}</div>
    <div class="datacards">${ver}${counts}</div>
    <table><tr><th>数据集</th><th>状态</th><th>路径</th><th>最后更新</th><th>大小</th></tr>${rows}</table>`;
}

// ===== 启动 =====
function refreshAll(){ refreshStreams();
  if(document.getElementById("tab-procs").classList.contains("active")) loadProcs();
  if(document.getElementById("tab-data").classList.contains("active")) loadData(); }
refreshStreams();
setInterval(()=>{ if(document.getElementById("tab-streams").classList.contains("active")) refreshStreams(); },6000);

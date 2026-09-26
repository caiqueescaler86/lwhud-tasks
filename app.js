const cfg=window.LW_INTEL||{};
let rows=[],accessToken="",filter="all",now=Date.now();
const $=id=>document.getElementById(id);

function cutoff(){
  const n=new Date(),br=new Date(n.toLocaleString("en-US",{timeZone:"America/Sao_Paulo"}));
  br.setHours(23,0,0,0);
  if(new Date(n.toLocaleString("en-US",{timeZone:"America/Sao_Paulo"}))<br)br.setDate(br.getDate()-1);
  const offset=n.getTime()-new Date(n.toLocaleString("en-US",{timeZone:"America/Sao_Paulo"})).getTime();
  return new Date(br.getTime()+offset).toISOString();
}

async function token(){
  if(accessToken)return accessToken;
  const res=await fetch(cfg.url.replace(/\/$/,"")+"/auth/v1/signup",{
    method:"POST",
    headers:{apikey:cfg.key,"Content-Type":"application/json"},
    body:"{}"
  });
  if(!res.ok)throw Error("Auth HTTP "+res.status);
  const data=await res.json();
  accessToken=data.access_token||data.session?.access_token||"";
  if(!accessToken)throw Error("Supabase não retornou token");
  return accessToken;
}

async function request(url,retry=true){
  const res=await fetch(url,{headers:{apikey:cfg.key,Authorization:"Bearer "+await token()}});
  if(res.status===401&&retry){accessToken="";return request(url,false)}
  return res;
}

function readyTime(r){
  const t=new Date(r.payload?.ready_at_utc).getTime();
  return Number.isFinite(t)?t:Infinity;
}

function timing(value){
  if(!value)return {label:"SEM HORÁRIO",ready:false};
  const t=new Date(value).getTime();
  if(!Number.isFinite(t))return {label:"SEM HORÁRIO",ready:false};
  const delta=t-now;

  if(delta<=0){
    const min=Math.floor(Math.abs(delta)/60000);
    return {label:min<1?"PRONTA AGORA":`PRONTA HÁ ${min} min`,ready:true};
  }

  const sec=Math.ceil(delta/1000),min=Math.floor(sec/60),s=sec%60;
  return {
    label:min>99?`EM ${Math.ceil(min/60)}h`:`EM ${String(min).padStart(2,"0")}:${String(s).padStart(2,"0")}`,
    ready:false
  };
}

function ordered(){
  const RECENT=10*60*1000;
  return [...rows].sort((a,b)=>{
    const ta=readyTime(a),tb=readyTime(b);
    const ar=ta<=now&&now-ta<=RECENT,br=tb<=now&&now-tb<=RECENT;
    const af=ta>now,bf=tb>now;

    if(ar!==br)return ar?-1:1;
    if(ar&&br)return tb-ta;
    if(af!==bf)return af?-1:1;
    if(af&&bf)return ta-tb;
    return tb-ta;
  });
}

function visible(){
  const RECENT=10*60*1000;
  return ordered().filter(r=>{
    const t=readyTime(r);
    if(filter==="ready")return t<=now&&now-t<=RECENT;
    if(filter==="soon")return t>now&&Number.isFinite(t);
    return true;
  });
}

function render(){
  const data=visible();
  $("summary").textContent=`Servidor #${cfg.localServer||"?"} · ${rows.length} tarefas`;

  $("list").innerHTML=data.length?data.map(r=>{
    const p=r.payload||{},t=timing(p.ready_at_utc);
    const clock=p.ready_at_utc
      ?new Date(p.ready_at_utc).toLocaleTimeString("pt-BR",{hour:"2-digit",minute:"2-digit"})
      :"--:--";

    return `<article class="task ${t.ready?"ready":""}">
      <div class="top">
        <span class="server">#${p.server_id??"?"}</span>
        <span class="level">Nv. ${p.level??"?"}</span>
        <span class="timer">${t.label}</span>
      </div>
      <div class="xy">X:${p.x??"?"} · Y:${p.y??"?"}</div>
      <div class="meta">
        <span>Saques: ${p.steals_used??"?"}/${p.steals_max??3}</span>
        <span>${clock}</span>
      </div>
    </article>`;
  }).join(""):'<div class="empty">Nenhuma tarefa externa disponível.</div>';
}

async function load(){
  try{
    if(!cfg.url||!cfg.key)throw Error("Configure config.js");

    const u=new URL(cfg.url.replace(/\/$/,"")+"/rest/v1/lw_hud_records");
    u.searchParams.set("select","id,observed_at,entity_uid,payload");
    u.searchParams.set("kind","eq.task");
    u.searchParams.set("observed_at","gte."+cutoff());
    u.searchParams.set("order","observed_at.desc,id.desc");
    u.searchParams.set("limit","1000");

    const res=await request(u);
    if(!res.ok)throw Error("Supabase HTTP "+res.status);

    const raw=await res.json(),seen=new Set();
    rows=[];

    for(const r of raw){
      const p=r.payload||{},server=p.server_id,max=p.steals_max??3,used=p.steals_used;
      const cfgid=p.cfg_id??String(r.entity_uid||"").split(":").pop();
      const key=[server,p.task_uid??p.uid??p.point_id??r.entity_uid,cfgid].join("|");

      if(seen.has(key))continue;
      seen.add(key);
      if(server==null||String(server)===String(cfg.localServer)||(used!=null&&used>=max))continue;
      rows.push(r);
    }

    render();
  }catch(e){
    $("summary").innerHTML='<span class="err">'+e.message+"</span>";
    $("list").innerHTML='<div class="empty">Não foi possível carregar as tarefas.</div>';
  }
}

document.querySelectorAll(".chip").forEach(b=>{
  b.onclick=()=>{
    filter=b.dataset.filter;
    document.querySelectorAll(".chip").forEach(x=>x.classList.toggle("active",x===b));
    render();
  };
});

$("refresh").onclick=load;
load();
setInterval(load,15000);
setInterval(()=>{now=Date.now();render()},1000);

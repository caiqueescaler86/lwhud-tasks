"""Passive Desert Storm intelligence. Pure Python core, no LLM or game actions."""
from __future__ import annotations
import csv
import json
import os
import re
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

COMMANDS = {'dragon.assign.player.info', 'dragon.activity.info'}
# Classic map layout per Last War Tutorial and LastWarGame guides. Not world coordinates.
# Rates vary by version; use 75/80 for silo only after in-game confirmation.
BUILDINGS = {
    'L1': ('info', 10, 0), 'L2': ('refinery', 50, 0),
    'L3': ('hospital', 30, 0), 'L4': ('hospital', 30, 0),
    'R1': ('hospital', 30, 0), 'R2': ('hospital', 30, 0),
    'R3': ('refinery', 50, 0), 'R4': ('science', 10, 0),
    'C1': ('arsenal', 10, 10), 'C2': ('silo', 80, 10), 'C3': ('mercenary', 10, 10),
}
# These are priority weights, not simulated points or combat predictions.
PRIORITY = {'refinery': 100, 'hospital': 75, 'info': 90, 'science': 60,
            'silo': 110, 'arsenal': 85, 'mercenary': 85}
TEXT = {
 'en': dict(title='Desert Storm battle plan', team='Team', capture='Capture & hold', clear='Area clearance', support='Mobile support', reserve='Reserves', info='Info Center', refinery='Oil Refinery', hospital='Field Hospital', science='Science Hub', arsenal='Arsenal', silo='Nuclear Silo', mercenary='Mercenary Factory', closed='Opens at 10:00', blocked='Alternative objectives', generic='General plan | enemy roster unknown', partial='Potential threats only | enemy roster incomplete', worst='Worst-case roster hypothesis | not confirmed', instruction='Protect alliance scoring. Clear bases only to secure objectives. If overmatched, redirect to alternate targets.', late='Late phase: spare squads collect supply boxes and oil wells when available.', schematic='Schematic map, not to scale', empty='Unassigned', phase='Phase', active='Starters'),
 'pt': dict(title='Plano de batalha Desert Storm', team='Time', capture='Capturar e manter', clear='Limpeza de área', support='Apoio móvel', reserve='Reservas', info='Centro de informações', refinery='Refinaria de petróleo', hospital='Hospital de campanha', science='Centro científico', arsenal='Arsenal', silo='Silo nuclear', mercenary='Fábrica de mercenários', closed='Abre aos 10:00', blocked='Objetivos alternativos', generic='Plano geral | escalação rival desconhecida', partial='Ameaças potenciais | lista rival incompleta', worst='Hipótese de pior caso | não confirmada', instruction='Proteja a pontuação da aliança. Limpe bases apenas para garantir objetivos. Se houver desvantagem, redirecione.', late='Fase final: esquadrões livres coletam caixas de pontos e petróleo quando disponíveis.', schematic='Mapa esquemático, fora de escala', empty='Sem atribuição', phase='Fase', active='Titulares'),
 'tr': dict(title='Çöl Fırtınası savaş planı', team='Takım', capture='Ele geçir ve tut', clear='Bölge temizliği', support='Mobil destek', reserve='Yedekler', info='Bilgi merkezi', refinery='Petrol rafinerisi', hospital='Sahra hastanesi', science='Bilim merkezi', arsenal='Cephanelik', silo='Nükleer silo', mercenary='Paralı asker fabrikası', closed='10:00’da açılır', blocked='Alternatif hedefler', generic='Genel plan | rakip kadro bilinmiyor', partial='Olası tehditler | rakip liste eksik', worst='En kötü durum varsayımı | doğrulanmadı', instruction='İttifak puanını koruyun. Üsleri yalnızca hedefleri güvenceye almak için temizleyin. Gerekirse yön değiştirin.', late='Son aşama: boş birlikler uygun olduğunda puan kutuları ve petrol toplar.', schematic='Şematik harita, ölçekli değil', empty='Atanmamış', phase='Aşama', active='As oyuncular'),
 'zh': dict(title='沙漠风暴作战计划', team='队伍', capture='占领并坚守', clear='区域清剿', support='机动支援', reserve='替补', info='情报中心', refinery='炼油厂', hospital='野战医院', science='科研中心', arsenal='兵工厂', silo='核弹发射井', mercenary='雇佣兵工厂', closed='10:00开放', blocked='转向其他目标', generic='通用计划｜敌方阵容未知', partial='潜在威胁｜敌方名单不完整', worst='最坏情况假设｜未确认', instruction='优先保护联盟积分。仅为保障目标而攻击基地。遇到强敌时转向其他目标。', late='后期：空闲部队在开放后收集积分箱和油井资源。', schematic='示意图，非实际比例', empty='未分配', phase='阶段', active='首发'),
}

def integer(x):
    if isinstance(x, bool): return None
    try: return int(x) if x is not None else None
    except (ValueError, TypeError, OverflowError): return None

def parse_time(x):
    return datetime.fromisoformat(str(x).replace('Z','+00:00'))

def rank(rows):
    return sorted(rows, key=lambda p: (-(p.get('hero_power') or 0), -(p.get('army_power') or 0), p['uid']))

def _alliance(x):
    return {k: x.get(src) for k, src in {'alliance_id':'allianceId','group_id':'allianceGroupId','server_id':'serverId','tag':'abbr','name':'name','side':'side','strength':'strength','main_num':'mainNum','army_power':'armyPower','total_power':'power'}.items()}

def normalize(root):
    """Recognize only the verified named-object response envelope."""
    if not isinstance(root,dict): return None
    envelope=root.get('p',{})
    if not isinstance(envelope,dict): return None
    cmd, data=envelope.get('c'),envelope.get('p')
    if cmd not in COMMANDS or not isinstance(data,dict): return None
    if cmd=='dragon.assign.player.info':
        users=data.get('users')
        if not isinstance(users,list) or not users or len(users)>1000: return None
        rows={}
        for x in users:
            if not isinstance(x,dict) or not x.get('uid') or x.get('group') not in (0,1,2) or x.get('state') not in (0,1,2): return None
            uid=str(x['uid']); rows[uid]=dict(uid=uid,name=str(x.get('name') or uid),server_id=integer(x.get('serverId')),level=integer(x.get('lv')),group=x['group'],state=x['state'],hero_power=integer(x.get('heroPower')),army_power=integer(x.get('armyPower')),total_power=integer(x.get('power')),preferred_times=[v for v in x.get('chooseTimeList',[]) if isinstance(v,int)] if isinstance(x.get('chooseTimeList'),list) else [],commander=bool(x.get('commander')))
        return 'roster',list(rows.values())
    teams={}
    for group in (1,2):
        x=data.get('group'+str(group))
        if not isinstance(x,dict): continue
        a=x.get('vsInfoArr',[])
        if not isinstance(a,list): continue
        t=x.get('timeInfo') or {};t=t if isinstance(t,dict) else {}
        teams[str(group)]=dict(group=group,period=integer(x.get('battlePeriod')),start_ms=integer(t.get('battleOpenTime')),end_ms=integer(t.get('endTime')),prep_ms=integer(t.get('prepTime')),battle_server_id=integer(x.get('battleServerId')),world_id=integer(x.get('worldId')),assigned=x.get('assigned'),alliances=[_alliance(y) for y in a if isinstance(y,dict) and y.get('allianceId')])
    if not teams: return None
    return 'activity',dict(season=integer(data.get('season')),map_config_id=integer(data.get('battleFieldConfigId')),teams=teams)

class DSStore:
    def __init__(self, root, profile='default'):
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,48}',str(profile)): raise ValueError('Invalid profile')
        self.folder=Path(root)/'data'/'profiles'/str(profile).lower()/'ds_intel'
        self.path=self.folder/'latest.json'
    def read(self):
        try:
            obj=json.loads(self.path.read_text(encoding='utf-8')); return obj if isinstance(obj,dict) else {}
        except (OSError,ValueError): return {}
    def ingest_root(self, root, seen=None):
        normalized=normalize(root)
        if not normalized:return False
        kind, value=normalized; seen=seen or datetime.now(timezone.utc).isoformat(); obj=self.read()
        if obj.get(kind,{}).get('seen','')>seen: return False
        if obj.get(kind,{}).get('value') != value:
            history=obj.setdefault('history',{}).setdefault(kind,[])
            if kind in obj:history.append(obj[kind])
            del history[:-12]
        obj[kind]=dict(seen=seen,value=value); obj['version']=1
        self.folder.mkdir(parents=True,exist_ok=True)
        with tempfile.NamedTemporaryFile(mode='w',encoding='utf-8',dir=self.folder,delete=False) as f:
            json.dump(obj,f,ensure_ascii=False,separators=(',',':'));tmp=Path(f.name)
        try: os.replace(tmp,self.path)
        finally:
            if tmp.exists():tmp.unlink()
        return True
    def ingest(self, decoded, seen):
        if not any(c.encode() in decoded for c in COMMANDS):return False
        from lw_named_codec import decode_named_frame
        root=decode_named_frame(decoded)
        return self.ingest_root(root,seen) if root else False

def matchup(snapshot, group):
    roster=snapshot.get('roster',{}); activity=snapshot.get('activity',{}); rows=roster.get('value',[]); av=activity.get('value',{})
    players=[dict(p) for p in rows if p.get('group')==group and p.get('state') in (1,2)]
    team=dict(av.get('teams',{}).get(str(group),{}));own=enemy=None
    # No mixing captures from different days/weeks or unknown alliance identity.
    try: compatible=abs((parse_time(roster['seen'])-parse_time(activity['seen'])).total_seconds())<=86400
    except (ValueError,TypeError,KeyError):compatible=False
    if compatible and players and team:
        server=Counter(p['server_id'] for p in players if p.get('server_id') is not None).most_common(1)
        if server:
            candidates=[a for a in team['alliances'] if a.get('server_id')==server[0][0]]
            if len(candidates)==1:
                own=candidates[0]; rivals=[a for a in team['alliances'] if a.get('alliance_id')!=own['alliance_id']];enemy=rivals[0] if len(rivals)==1 else None
    return dict(group=group,team='A' if group==1 else 'B',roster_seen=roster.get('seen'),activity_seen=activity.get('seen'),season=av.get('season') if compatible else None,map_config_id=av.get('map_config_id') if compatible else None,match=team if compatible else {},own=own,enemy=enemy,starters=rank([p for p in players if p['state']==1]),reserves=rank([p for p in players if p['state']==2]))

def enemy_intel(match, data, whale_ratio=1.10):
    """Exact alliance ID join; unknown HP stays unknown. Roster is hypothetical."""
    rival=match.get('enemy') or {}; aid=rival.get('alliance_id'); result=dict(status='generic',known=0,observed=0,expected=None,top=[],threats=[])
    if not aid or not isinstance(data,dict):return result
    members={}
    for m in data.get('members',[]):
        if str(m.get('alliance_id') or m.get('alliance_key') or '')!=str(aid):continue
        uid=str(m.get('player_uid') or m.get('uid') or '')
        if not uid:continue
        members[uid]=dict(uid=uid,name=str(m.get('name') or m.get('player_name') or uid),hero_power=integer(m.get('hero_power')),army_power=integer(m.get('army_power')),total_power=integer(m.get('total_power')))
    alliance=next((a for a in data.get('alliances',[]) if str(a.get('alliance_id') or a.get('alliance_key') or '')==str(aid)),{})
    known=rank([p for p in members.values() if (p.get('hero_power') or 0)>0]);expected=integer(alliance.get('member_count'));n=integer(rival.get('main_num')) or 20;n=max(1,min(n,20))
    complete=bool(expected and len(members)==expected and len(known)==expected and len(known)>=n)
    result.update(status='worst' if complete else ('partial' if members else 'generic'),observed=len(members),known=len(known),expected=expected,top=known[:n])
    strongest=max((p.get('hero_power') or 0 for p in match['starters']),default=0)
    if strongest:result['threats']=[p for p in result['top'] if p['hero_power']>=strongest*whale_ratio]
    return result

def plan(match, intel=None, blocked=(), absent=()):
    """Conservative deterministic assignments, never combat outcomes.

    Blocked locations are explicit commander inputs, never inferred enemy locations.
    Reserves only replace explicitly absent starters. Remaining reserves not deployed.
    """
    intel=intel or {'status':'generic','threats':[]}; blocked=set(blocked); absent=set(absent)
    if not blocked<=BUILDINGS.keys():raise ValueError('Unknown objective')
    starters=[p for p in match['starters'] if p['uid'] not in absent]; substitutes=rank(match['reserves']); used=set()
    for p in substitutes:
        if len(starters)>=min(len(match['starters']),20):break
        starters.append(p);used.add(p['uid'])
    if len(starters)>20:raise ValueError('More than 20 active players')
    starters=rank(starters); phases=[]; previous={}
    for minute in (0,10):
        targets=sorted([k for k,v in BUILDINGS.items() if v[2]<=minute and k not in blocked],key=lambda k:(-PRIORITY[BUILDINGS[k][0]],k))
        n=len(starters);capt_n=min(len(targets),max(0,n-1)) if n>1 else min(len(targets),n)
        # For short rosters, retain one mobile/clearer per ~2 capturers.
        if n<16:capt_n=min(capt_n,max(1,(n*2)//3))
        chosen=targets[:capt_n];assigned={};pool={p['uid']:p for p in starters}
        def add(p,role,loc):
            assigned[p['uid']]=dict(uid=p['uid'],name=p['name'],role=role,target=loc,hero_power=p['hero_power']);pool.pop(p['uid'],None)
        clear_n=min(8 if minute==0 else 6,max(0,n-capt_n-(min(4 if minute==0 else 3,max(0,n-capt_n-1)))))
        if chosen and n>capt_n:clear_n=max(1,clear_n)
        # Select strongest for clearance; give first preference to regional high-value objectives.
        clearers=starters[:clear_n]
        if minute==0: zones=[[k] for k in chosen]
        else:
            zones=[[k for k in chosen if k in zone] for zone in [('C2',),('C1','C3'),('L1','L2'),('R3','R4'),('L3','L4'),('R1','R2')]]
            zones=[z for z in zones if z]
            if intel.get('status') == 'worst' and intel.get('threats'):
                # No speculative whale location: distribute coverage, prioritizing outer scoring.
                zones.sort(key=lambda z:(not any(k.startswith(('L','R')) for k in z),-sum(PRIORITY[BUILDINGS[k][0]] for k in z)))
        for i,p in enumerate(clearers):
            if zones:add(p,'clear','+'.join(zones[i%len(zones)]))
        # Keep capturers holding their existing objectives when possible.
        for k in chosen:
            old=next((p for p in pool.values() if previous.get(p['uid'],{}).get('role')=='capture' and previous[p['uid']]['target']==k),None)
            if old:add(old,'capture',k)
        for k in chosen:
            if any(a['role']=='capture' and a['target']==k for a in assigned.values()):continue
            if pool:add(rank(list(pool.values()))[0],'capture',k)
        for p in rank(list(pool.values())):add(p,'support','MOBILE')
        phase=list(assigned.values());phases.append(phase);previous=assigned
    result=dict(phases=phases,reserves=[p for p in substitutes if p['uid'] not in used],absent=sorted(absent),blocked=sorted(blocked),intel_status=intel['status'],team=match['team'])
    validate_plan(result,match)
    return result

def validate_plan(p,match):
    active={x['uid'] for x in match['starters']+match['reserves']}; actual=None
    expected={x['uid'] for x in match['starters'] if x['uid'] not in p.get('absent',[])}
    if len(p['phases']) != 2:raise ValueError('Exactly two phases required')
    for phase,rows in enumerate(p['phases']):
        ids=[r['uid'] for r in rows]
        if len(ids)>20 or len(ids)!=len(set(ids)) or not set(ids)<=active:raise ValueError('Invalid active roster')
        if actual is not None and set(ids)!=actual:raise ValueError('Active roster changed between phases')
        actual=set(ids); captures=set()
        if not expected<=actual or actual & set(p.get('absent',[])):raise ValueError('Absent or omitted starter')
        for r in rows:
            if r['role']=='support' and r['target']=='MOBILE':continue
            if r['role'] not in ('capture','clear'):raise ValueError('Invalid role/target')
            codes=r['target'].split('+')
            if any(k not in BUILDINGS or BUILDINGS[k][2]>phase*10 or k in p['blocked'] for k in codes):raise ValueError('Invalid/closed objective')
            if r['role']=='capture':
                if len(codes)!=1 or codes[0] in captures:raise ValueError('Duplicate capturer')
                captures.add(codes[0])
    if actual is not None and actual & {r['uid'] for r in p['reserves']}:raise ValueError('Reserve deployed twice')
    if {r['uid'] for r in p['reserves']} != ({r['uid'] for r in match['reserves']} - (actual or set())):raise ValueError('Invalid reserve list')
    return True

def export_csv(path,match,p,intel=None):
    intel=intel or {}; enemy=match.get('enemy') or {}; own=match.get('own') or {}; phases=[{x['uid']:x for x in a} for a in (p or {}).get('phases',[[],[]])]
    fields=['team','side','uid','name','status','hero_power','army_power','total_power','level','commander','preferred_times','assigned_period','alliance_id','alliance_tag','server_id','opponent_id','opponent_tag','opponent_server','opponent_total_power','opponent_army_power','opponent_strength','own_strength','match_start_ms','season','map_config_id','captured_at','intel_status','phase_1_role','phase_1_target','phase_2_role','phase_2_target']
    def safe(v):return "'"+v if isinstance(v,str) and v.startswith(('=','+','-','@','\t','\r')) else v
    with open(path,'w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fields);w.writeheader()
        for player,side,status in [(x,'own','starter') for x in match['starters']]+[(x,'own','reserve') for x in match['reserves']]+[(x,'rival','hypothetical') for x in intel.get('top',[])]:
            a=own if side=='own' else enemy;row={k:player.get(k) for k in fields if k in player};row.update(team=match['team'],side=side,status=status,alliance_id=a.get('alliance_id'),alliance_tag=a.get('tag'),server_id=a.get('server_id'),opponent_id=enemy.get('alliance_id'),opponent_tag=enemy.get('tag'),opponent_server=enemy.get('server_id'),opponent_total_power=enemy.get('total_power'),opponent_army_power=enemy.get('army_power'),opponent_strength=enemy.get('strength'),own_strength=own.get('strength'),assigned_period=match['match'].get('period'),match_start_ms=match['match'].get('start_ms'),season=match.get('season'),map_config_id=match.get('map_config_id'),captured_at=match.get('roster_seen') if side=='own' else None,intel_status=intel.get('status'),preferred_times=';'.join(map(str,player.get('preferred_times',[]))))
            for i, phase in enumerate(phases,1):
                v=phase.get(player['uid'],{}) if side=='own' else {};row[f'phase_{i}_role']=v.get('role');row[f'phase_{i}_target']=v.get('target')
            w.writerow({k:safe(v) for k,v in row.items()})

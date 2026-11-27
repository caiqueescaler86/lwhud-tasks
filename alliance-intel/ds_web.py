"""Private DS Intel portal, using only its scoped Supabase reader account."""
from __future__ import annotations
import copy
import hashlib
import hmac
import io
import json
import re
import tempfile
import threading
import time
from datetime import datetime, timezone, timedelta
from functools import lru_cache
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from ds_intel import BUILDINGS, TEXT, plan, validate_plan, export_csv
from ds_intel_render import render_png


class DSReader:
    def __init__(self, url, key, email, password, opener=urlopen):
        u=urlparse(url.rstrip('/'))
        if u.scheme!='https' or not re.fullmatch(r'[a-z0-9-]+\.supabase\.co',u.netloc) or u.path or u.query or u.fragment:
            raise ValueError('Invalid Supabase URL')
        if not key.startswith('sb_publishable_'):
            raise ValueError('DS requires a publishable key, not a secret key')
        if not email or not password:raise ValueError('Missing DS reader credentials')
        self.url,self.key,self.email,self.password=url.rstrip('/'),key,email,password
        self.opener=opener;self.lock=threading.RLock();self.token='';self.token_until=0;self.cached=None;self.cache_until=0
    def _post(self,path,body,token=''):
        headers={'apikey':self.key,'Content-Type':'application/json','Accept':'application/json'}
        if token:headers['Authorization']='Bearer '+token
        req=Request(self.url+path,data=json.dumps(body).encode(),headers=headers,method='POST')
        with self.opener(req,timeout=8) as res:
            raw=res.read(524289)
            if len(raw)>524288:raise ValueError('DS response too large')
        return json.loads(raw)
    def _login(self):
        obj=self._post('/auth/v1/token?grant_type=password',{'email':self.email,'password':self.password})
        token=obj.get('access_token')
        if not isinstance(token,str) or not token:raise ValueError('Invalid DS reader session')
        self.token=token;self.token_until=time.monotonic()+max(0,min(3600,int(obj.get('expires_in',3600)))-60)
    def read(self):
        with self.lock:
            if self.cached is not None and time.monotonic()<self.cache_until:return copy.deepcopy(self.cached)
            if not self.token or time.monotonic()>=self.token_until:self._login()
            try:rows=self._post('/rest/v1/rpc/lw_ds_read',{},self.token)
            except HTTPError as exc:
                if exc.code!=401:raise
                self._login();rows=self._post('/rest/v1/rpc/lw_ds_read',{},self.token)
            if not isinstance(rows,list) or len(rows)>8:raise ValueError('Invalid DS response')
            if any(not isinstance(x,dict) or not isinstance(x.get('match'),dict) for x in rows):raise ValueError('Invalid DS response')
            self.cached=copy.deepcopy(rows);self.cache_until=time.monotonic()+60
            return rows


@lru_cache(maxsize=2)
def reader(url,key,email,password):return DSReader(url,key,email,password)


class DSDatabaseReader:
    """Dedicated PostgreSQL login; queries only the RLS-protected DS match table."""
    def __init__(self, dsn, connector=None):
        u=urlparse(dsn)
        if (u.scheme not in ('postgresql','postgres') or not u.hostname
                or not re.fullmatch(r'[a-z0-9-]+\.pooler\.supabase\.com',u.hostname)
                or not re.fullmatch(r'lw_ds_streamlit_reader\.[a-z0-9]+',u.username or '')
                or not u.password or u.port != 5432 or u.path != '/postgres'
                or u.query or u.fragment):
            raise ValueError('Use the Supabase session pooler DS reader URI without query parameters')
        self.dsn=dsn;self.connector=connector
        self.lock=threading.RLock();self.cached=None;self.cache_until=0

    def read(self):
        with self.lock:
            if self.cached is not None and time.monotonic()<self.cache_until:
                return copy.deepcopy(self.cached)
            connector=self.connector
            if connector is None:
                import psycopg
                connector=psycopg.connect
            import certifi
            with connector(self.dsn, sslmode='verify-full',sslrootcert=certifi.where(),
                           connect_timeout=8,autocommit=True,prepare_threshold=None) as conn:
                with conn.cursor() as cur:
                    cur.execute("SET statement_timeout = '8s'")
                    cur.execute("""
                        SELECT jsonb_build_object(
                            'match',match_payload,'enemy',enemy_payload,
                            'enemy_seen',enemy_seen,'updated_at',updated_at,'ends_at',ends_at
                        )
                        FROM lw_ds_private.matches
                        WHERE ends_at > lw_ds_private.cutoff(now())
                        ORDER BY start_ms,group_id LIMIT 8
                    """)
                    rows=[r[0] for r in cur.fetchall()]
            if (len(rows)>8 or any(not isinstance(r,dict) or not isinstance(r.get('match'),dict) for r in rows)
                    or len(json.dumps(rows,ensure_ascii=False).encode())>524288):
                raise ValueError('Invalid DS response')
            self.cached=copy.deepcopy(rows);self.cache_until=time.monotonic()+60
            return rows


@lru_cache(maxsize=2)
def database_reader(dsn):return DSDatabaseReader(dsn)


def intelligence(row):
    intel=copy.deepcopy(row.get('enemy') or {})
    if intel.get('status') not in ('partial','worst'):return dict(status='generic',top=[],threats=[],known=0,expected=None)
    strongest=max((p.get('hero_power') or 0 for p in row['match']['starters']),default=0)
    intel['threats']=[p for p in intel.get('top',[]) if strongest and (p.get('hero_power') or 0)>=strongest*1.10]
    return intel


def csv_bytes(match, p, intel):
    with tempfile.TemporaryDirectory() as folder:
        path=Path(folder)/'ds.csv';export_csv(path,match,p,intel);return path.read_bytes()


def match_key(row):
    return hashlib.sha256(json.dumps(row,sort_keys=True,ensure_ascii=False).encode()).hexdigest()[:24]


def show_ds_intel(language,secret):
    import streamlit as st
    lang=language if language in TEXT else 'en';t=TEXT[lang]
    st.title('DS Intel')
    # Reuse the existing portal gate, including password rotation invalidation.
    # Check again defensively before constructing the server-side reader.
    password=secret('ACCESS_PASSWORD')
    digest=hashlib.sha256(password.encode('utf-8')).hexdigest()
    if (len(password)<12 or not st.session_state.get('access_granted')
            or not hmac.compare_digest(str(st.session_state.get('access_fingerprint','')),digest)):
        st.info('Sign in to the Alliance Intel portal first.');return
    if st.button('Sign out',key='ds_portal_logout'):
        st.session_state.access_granted=False
        st.session_state.access_fingerprint=''
        st.session_state.history=[]
        st.session_state.clear_admin_on_login=True
        for k in list(st.session_state):
            if str(k).startswith('ds_'):del st.session_state[k]
        st.rerun()
    try:
        dsn=secret('DS_DATABASE_URL')
        if dsn:
            rows=database_reader(dsn).read()
        else:
            cfg=[secret(k) for k in ('DS_SUPABASE_URL','DS_SUPABASE_PUBLISHABLE_KEY','DS_READ_EMAIL','DS_READ_PASSWORD')]
            rows=reader(*cfg).read()
    except Exception:
        st.warning('DS data is not available. Check Supabase setup, reader access and Streamlit secrets.');return
    st.caption('Weekly snapshots · refresh cache: 60 seconds · no Groq')
    if not rows:st.info('No Desert Storm matches published for this week. Open the DS screens in the HUD.');return
    def label(i):
        r=rows[i]['match'];opp=r.get('enemy') or {};own=r.get('own') or {}
        stamp=datetime.fromtimestamp(r['match']['start_ms']/1000,timezone(timedelta(hours=-3)))
        return f"{t['team']} {r['team']} | {own.get('tag','?')} vs {opp.get('tag','?')} #{opp.get('server_id','?')} | {stamp:%d/%m %H:%M} BRT"
    row=rows[st.selectbox('Match',range(len(rows)),format_func=label,key='ds_selected_match')];m=row['match'];intel=intelligence(row);key=match_key(row)
    st.caption(f"Roster: {m.get('roster_seen','—')} | Updated: {row.get('updated_at','—')}")
    a,b=st.columns(2);a.metric(t['active'],len(m['starters']));b.metric(t['reserve'],len(m['reserves']))
    def table(players):
        period=m['match'].get('period')
        return [{'Player':p['name'],'Hero Power':p.get('hero_power'),'Army Power':p.get('army_power'),'Total Power':p.get('total_power'),'Preferred periods':', '.join(map(str,p.get('preferred_times',[]))),'Assigned period':period} for p in players]
    st.subheader(t['active']);st.dataframe(table(m['starters']),hide_index=True,use_container_width=True)
    st.subheader(t['reserve']);st.dataframe(table(m['reserves']),hide_index=True,use_container_width=True)
    own=m.get('own') or {};opp=m.get('enemy') or {}
    st.subheader('Enemy Intel');st.dataframe([{'Alliance':p.get('tag'),'Server':p.get('server_id'),'Total Power':p.get('total_power'),'Army Power':p.get('army_power'),'Matchmaking Strength':p.get('strength')} for p in (own,opp)],hide_index=True,use_container_width=True)
    st.caption(t[intel['status']]);st.caption(f"Hero Power coverage: {intel.get('known',0)}/{intel.get('expected') or '?'}")
    if intel['top']:
        threat={p['uid'] for p in intel['threats']}
        st.dataframe([{'Player':p['name'],'Hero Power':p.get('hero_power'),'Potential threat':p['uid'] in threat} for p in intel['top']],hide_index=True,use_container_width=True)
    else:st.info(f"Capture the rival alliance {opp.get('tag','?')} on server {opp.get('server_id','?')} in Alliance Intel, then refresh enemy data in the HUD.")
    st.download_button('Export roster CSV',csv_bytes(m,None,intel),file_name=f"DS_{m['team']}_roster.csv",mime='text/csv',key='ds_roster_'+key)
    st.subheader(t['title']);st.caption('Personal draft, not shared or published as an official plan.')
    if st.session_state.get('ds_current_key')!=key:
        for k in list(st.session_state):
            if str(k).startswith(('ds_editor_','ds_absent_','ds_blocked_')):del st.session_state[k]
        st.session_state.ds_current_key=key;st.session_state.ds_plan=None;st.session_state.ds_revision=0
    names={p['uid']:p['name'] for p in m['starters']}
    absent=st.multiselect('Absent starters',list(names),format_func=names.get,key='ds_absent_'+key)
    blocked=st.multiselect('Contested objectives / alternative targets',list(BUILDINGS),format_func=lambda k:f"{k} · {t[BUILDINGS[k][0]]}",key='ds_blocked_'+key)
    if st.button('Generate plan',key='ds_generate_'+key):
        try:
            st.session_state.ds_plan=plan(m,intel,blocked,absent);st.session_state.ds_revision+=1
            for k in list(st.session_state):
                if str(k).startswith('ds_editor_'):del st.session_state[k]
        except ValueError as exc:st.error(str(exc))
    p=copy.deepcopy(st.session_state.get('ds_plan'))
    if not p:return
    if set(p['blocked'])!=set(blocked) or set(p['absent'])!=set(absent):st.info('Settings changed. Generate a new plan.');return
    roles={'capture':t['capture'],'clear':t['clear'],'support':t['support']};inverse={v:k for k,v in roles.items()}
    phases=[]
    for i,phase in enumerate(p['phases']):
        st.caption(f"{t['phase']} {i+1} · {'00:00–10:00' if i==0 else '10:00–30:00'}")
        view=[{'Player':r['name'],'Hero Power':r['hero_power'],'Role':roles[r['role']],'Target':r['target']} for r in phase]
        edited=st.data_editor(view,hide_index=True,num_rows='fixed',disabled=['Player','Hero Power'],use_container_width=True,column_config={'Role':st.column_config.SelectboxColumn('Role',options=list(roles.values()),required=True),'Target':st.column_config.TextColumn('Target',required=True)},key=f'ds_editor_{key}_{lang}_{st.session_state.ds_revision}_{i}')
        try:phases.append([dict(old,role=inverse[new['Role']],target=new['Target'].strip().upper()) for old,new in zip(phase,edited,strict=True)])
        except (KeyError,TypeError,ValueError,AttributeError):st.error('Invalid plan edit');return
    p['phases']=phases
    try:validate_plan(p,m)
    except ValueError as exc:st.error(str(exc));return
    st.download_button('Export plan CSV',csv_bytes(m,p,intel),file_name=f"DS_{m['team']}_plan.csv",mime='text/csv')
    # Render only on request; image bytes belong to the user's session.
    image_key=hashlib.sha256(json.dumps([p,lang,key],sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    if st.button('Preview / generate PNG'):
        try:
            out=io.BytesIO();render_png(out,m,p,lang);st.session_state.ds_image=(image_key,out.getvalue())
        except (OSError,RuntimeError,ValueError) as exc:st.error('PNG rendering unavailable. Check installed fonts and Pillow.')
    if st.session_state.get('ds_image',(None,))[0]==image_key:
        raw=st.session_state.ds_image[1];st.image(raw,use_container_width=True);st.download_button('Export PNG',raw,file_name=f"DS_{m['team']}_{lang}.png",mime='image/png')

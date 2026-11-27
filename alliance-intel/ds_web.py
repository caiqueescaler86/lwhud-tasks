"""Private DS Intel portal, using only its scoped Supabase reader account."""
from __future__ import annotations
import copy
import hashlib
import hmac
import io
import json
import re
import ssl
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
from ds_fonts import FontUnavailable
from ds_cache import SharedSnapshotCache, CacheUnavailable, MAX_BYTES
from ds_web_i18n import ui, validation_label, diagnostic_label


class DSReader:
    def __init__(self, url, key, email, password, opener=urlopen):
        u=urlparse(url.rstrip('/'))
        if u.scheme!='https' or not re.fullmatch(r'[a-z0-9-]+\.supabase\.co',u.netloc) or u.path or u.query or u.fragment:
            raise ValueError('Invalid Supabase URL')
        if not key.startswith('sb_publishable_'):
            raise ValueError('DS requires a publishable key, not a secret key')
        if not email or not password:raise ValueError('Missing DS reader credentials')
        self.url,self.key,self.email,self.password=url.rstrip('/'),key,email,password
        self.opener=opener;self.token='';self.token_until=0;self.cache=SharedSnapshotCache()
    def _post(self,path,body,token=''):
        headers={'apikey':self.key,'Content-Type':'application/json','Accept':'application/json'}
        if token:headers['Authorization']='Bearer '+token
        req=Request(self.url+path,data=json.dumps(body).encode(),headers=headers,method='POST')
        with self.opener(req,timeout=8) as res:
            raw=res.read(MAX_BYTES+1)
            if len(raw)>MAX_BYTES:raise CacheUnavailable('DS-TOO-LARGE')
        return json.loads(raw)
    def _login(self):
        obj=self._post('/auth/v1/token?grant_type=password',{'email':self.email,'password':self.password})
        token=obj.get('access_token')
        if not isinstance(token,str) or not token:raise ValueError('Invalid DS reader session')
        self.token=token;self.token_until=time.monotonic()+max(0,min(3600,int(obj.get('expires_in',3600)))-60)
    def _fetch(self):
        if not self.token or time.monotonic()>=self.token_until:self._login()
        try:return self._post('/rest/v1/rpc/lw_ds_read',{},self.token)
        except HTTPError as exc:
            if exc.code!=401:raise
            self._login()
            return self._post('/rest/v1/rpc/lw_ds_read',{},self.token)

    def read(self):
        return self.cache.read(self._fetch, classify_reader_error)


# Serialize factory cache misses, so concurrent first visitors share one budget.
READER_FACTORY_LOCK = threading.RLock()


@lru_cache(maxsize=2)
def _reader(url,key,email,password):return DSReader(url,key,email,password)


def reader(url,key,email,password):
    with READER_FACTORY_LOCK:return _reader(url,key,email,password)


# Official hosted CA URL from Supabase Studio's ssl:certificate_url.
# Bootstrap over ordinary authenticated HTTPS, then use the dedicated CA for PostgreSQL.
# This URL never receives the database DSN or credentials.
SUPABASE_CA_URL = 'https://supabase-downloads.s3-ap-southeast-1.amazonaws.com/prod/ssl/prod-ca-2021.crt'


@lru_cache(maxsize=1)
def supabase_ca_pem():
    import certifi
    try:
        context=ssl.create_default_context(cafile=certifi.where())
        with urlopen(Request(SUPABASE_CA_URL),timeout=8,context=context) as response:
            if response.geturl()!=SUPABASE_CA_URL:
                raise ValueError('Unexpected CA download redirect')
            raw=response.read(65537)
        if not raw or len(raw)>65536 or not raw.lstrip().startswith(b'-----BEGIN CERTIFICATE-----'):
            raise ValueError('Invalid CA download')
        # Ensure the payload parses as an X.509 certificate bundle.
        validator=ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        validator.load_verify_locations(cadata=raw.decode('ascii'))
        if not validator.cert_store_stats().get('x509_ca'):
            raise ValueError('Downloaded certificate bundle has no CA')
        return raw
    except (OSError,ValueError,UnicodeError) as exc:
        raise RuntimeError('Supabase CA certificate download or validation failed') from exc


class DSDatabaseReader:
    """Dedicated PostgreSQL login; queries only the RLS-protected DS match table."""
    def __init__(self, dsn, connector=None, ca_loader=None):
        u=urlparse(dsn)
        if (u.scheme not in ('postgresql','postgres') or not u.hostname
                or not re.fullmatch(r'[a-z0-9-]+\.pooler\.supabase\.com',u.hostname)
                or not re.fullmatch(r'lw_ds_streamlit_reader\.[a-z0-9]+',u.username or '')
                or not u.password or u.port != 5432 or u.path != '/postgres'
                or u.query or u.fragment):
            raise ValueError('Use the Supabase session pooler DS reader URI without query parameters')
        self.dsn=dsn;self.connector=connector
        self.ca_loader=ca_loader or supabase_ca_pem
        self.cache=SharedSnapshotCache()

    def _fetch(self):
        connector=self.connector
        if connector is None:
            import psycopg
            connector=psycopg.connect
        with tempfile.TemporaryDirectory(prefix='ds-ca-') as folder:
            ca_path=Path(folder)/'prod-ca-2021.crt'
            ca_path.write_bytes(self.ca_loader())
            with connector(self.dsn, sslmode='verify-full',sslrootcert=str(ca_path),
                           connect_timeout=8,autocommit=True,prepare_threshold=None) as conn:
                with conn.cursor() as cur:
                    cur.execute("SET statement_timeout = '8s'")
                    cur.execute(f"""
                        WITH selected AS MATERIALIZED (
                            SELECT match_payload,enemy_payload,enemy_seen,updated_at,ends_at,start_ms,group_id
                            FROM lw_ds_private.matches
                            WHERE ends_at > lw_ds_private.cutoff(now())
                            ORDER BY start_ms,group_id LIMIT 8
                        ), payload AS (
                            SELECT coalesce(jsonb_agg(jsonb_build_object(
                                'match',match_payload,'enemy',enemy_payload,
                                'enemy_seen',enemy_seen,'updated_at',updated_at,'ends_at',ends_at
                            ) ORDER BY start_ms,group_id),'[]'::jsonb) AS data
                            FROM selected
                        )
                        SELECT CASE WHEN octet_length(data::text) <= {MAX_BYTES}
                                    THEN data ELSE NULL END FROM payload
                    """)
                    row=cur.fetchone()
        if not row or row[0] is None:raise CacheUnavailable('DS-TOO-LARGE')
        return row[0]

    def read(self):
        return self.cache.read(self._fetch, classify_reader_error)


@lru_cache(maxsize=2)
def _database_reader(dsn):return DSDatabaseReader(dsn)


def database_reader(dsn):
    with READER_FACTORY_LOCK:return _database_reader(dsn)


def safe_reader_error(exc, configured):
    # Never return an exception message, DSN, connection host or credentials.
    if isinstance(exc,CacheUnavailable):return exc.code + ": reader refresh deferred."
    if not configured:
        return "DS-CONFIG-MISSING: configure DS_DATABASE_URL in Streamlit Secrets."
    if isinstance(exc, ImportError):
        return "DS-DRIVER: PostgreSQL driver unavailable; check deployment dependencies."
    if isinstance(exc, HTTPError):
        if exc.code in (401, 403):
            return "DS-AUTH: API authentication or authorization failed."
        return "DS-HTTP: reader API returned an error."
    state = str(getattr(exc, "sqlstate", "") or "")
    message = str(exc).lower()
    if state in ("28P01", "28000") or any(x in message for x in (
            "password authentication failed", "authentication failed",
            "tenant or user not found", "invalid password", "role does not exist",
            "user not found", "wrong password")):
        return "DS-AUTH: database reader login rejected. Check the reader password and role."
    if state == "42501" or "permission denied" in message:
        return "DS-PERMISSION: reader lacks access to the DS schema or table."
    if state in ("42P01", "3F000", "42883", "42703"):
        return "DS-SCHEMA: expected DS tables, columns or functions are missing."
    if any(x in message for x in ("certificate verify", "certificate validation",
                                  "certificate", "ssl error", "tls error")):
        return "DS-TLS: certificate verification failed; secure connection not established."
    if state.startswith("08") or any(x in message for x in (
            "timeout", "timed out", "connection refused", "could not translate host",
            "could not connect", "network is unreachable", "connection failed",
            "server closed the connection")):
        return "DS-NETWORK: could not establish a connection to the database."
    if state == "57014":
        return "DS-TIMEOUT: database query exceeded its time limit."
    if isinstance(exc, ValueError):
        return "DS-CONFIG-OR-RESPONSE: check the reader URI and database response format."
    return "DS-UNKNOWN: reader failed; check administrator diagnostics."


def classify_reader_error(exc):
    return safe_reader_error(exc,True).split(':',1)[0]


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
    L=lambda key,**kwargs:ui(lang,key,**kwargs)
    st.title(L('ds_module'))
    # Reuse the existing portal gate, including password rotation invalidation.
    # Check again defensively before constructing the server-side reader.
    password=secret('ACCESS_PASSWORD')
    digest=hashlib.sha256(password.encode('utf-8')).hexdigest()
    if (len(password)<12 or not st.session_state.get('access_granted')
            or not hmac.compare_digest(str(st.session_state.get('access_fingerprint','')),digest)):
        st.info(L('login'));return
    if st.button(L('signout'),key='ds_portal_logout'):
        st.session_state.access_granted=False
        st.session_state.access_fingerprint=''
        st.session_state.history=[]
        st.session_state.clear_admin_on_login=True
        for k in list(st.session_state):
            if str(k).startswith('ds_'):del st.session_state[k]
        st.rerun()
    configured=False
    try:
        dsn=secret('DS_DATABASE_URL')
        if dsn:
            configured=True
            active_reader=database_reader(dsn)
            rows=active_reader.read()
        else:
            cfg=[secret(k) for k in ('DS_SUPABASE_URL','DS_SUPABASE_PUBLISHABLE_KEY','DS_READ_EMAIL','DS_READ_PASSWORD')]
            configured=all(cfg)
            if not configured:raise ValueError("Missing reader configuration")
            active_reader=reader(*cfg)
            rows=active_reader.read()
    except Exception as exc:
        st.warning(diagnostic_label(lang,safe_reader_error(exc,configured).split(':',1)[0]))
        if st.button(L("retry"),key="ds_retry_connection"):
            st.rerun()
        return
    st.caption(L('cache'))
    if active_reader.cache.status=='stale':
        st.warning(L('stale',reason=diagnostic_label(lang,active_reader.cache.code)))
    if not rows:st.info(L('empty'));return
    def label(i):
        r=rows[i]['match'];opp=r.get('enemy') or {};own=r.get('own') or {}
        stamp=datetime.fromtimestamp(r['match']['start_ms']/1000,timezone(timedelta(hours=-3)))
        return f"{t['team']} {r['team']} | {own.get('tag','?')} vs {opp.get('tag','?')} #{opp.get('server_id','?')} | {stamp:%d/%m %H:%M} BRT"
    row=rows[st.selectbox(L('match'),range(len(rows)),format_func=label,key='ds_selected_match')];m=row['match'];intel=intelligence(row);key=match_key(row)
    st.caption(L('roster_at',roster=m.get('roster_seen','—'),updated=row.get('updated_at','—')))
    a,b=st.columns(2);a.metric(t['active'],len(m['starters']));b.metric(t['reserve'],len(m['reserves']))
    def table(players):
        period=m['match'].get('period')
        return [{L('player'):p['name'],L('hero_power'):p.get('hero_power'),L('army_power'):p.get('army_power'),L('total_power'):p.get('total_power'),L('preferred_periods'):', '.join(map(str,p.get('preferred_times',[]))),L('assigned_period'):period} for p in players]
    st.subheader(t['active']);st.dataframe(table(m['starters']),hide_index=True,use_container_width=True)
    st.subheader(t['reserve']);st.dataframe(table(m['reserves']),hide_index=True,use_container_width=True)
    own=m.get('own') or {};opp=m.get('enemy') or {}
    st.subheader(L('enemy_intel'));st.dataframe([{L('alliance'):p.get('tag'),L('server'):p.get('server_id'),L('total_power'):p.get('total_power'),L('army_power'):p.get('army_power'),L('strength'):p.get('strength')} for p in (own,opp)],hide_index=True,use_container_width=True)
    st.caption(t[intel['status']]);st.caption(L('coverage',known=intel.get('known',0),expected=intel.get('expected') or '?'))
    if intel['top']:
        threat={p['uid'] for p in intel['threats']}
        st.dataframe([{L('player'):p['name'],L('hero_power'):p.get('hero_power'),L('threat'):L('yes') if p['uid'] in threat else L('no')} for p in intel['top']],hide_index=True,use_container_width=True)
    else:st.info(L('capture_rival',tag=opp.get('tag','?'),server=opp.get('server_id','?')))
    st.download_button(L('roster_csv'),csv_bytes(m,None,intel),file_name=f"DS_{m['team']}_roster.csv",mime='text/csv',key='ds_roster_'+key)
    st.subheader(t['title']);st.caption(L('draft'))
    if st.session_state.get('ds_current_key')!=key:
        for k in list(st.session_state):
            if str(k).startswith(('ds_editor_','ds_absent_','ds_blocked_')):del st.session_state[k]
        st.session_state.ds_current_key=key;st.session_state.ds_plan=None;st.session_state.ds_revision=0
    names={p['uid']:p['name'] for p in m['starters']}
    absent=st.multiselect(L('absent'),list(names),format_func=names.get,key='ds_absent_'+key)
    blocked=st.multiselect(L('blocked'),list(BUILDINGS),format_func=lambda k:f"{k} · {t[BUILDINGS[k][0]]}",key='ds_blocked_'+key)
    if st.button(L('generate'),key='ds_generate_'+key):
        try:
            st.session_state.ds_plan=plan(m,intel,blocked,absent);st.session_state.ds_revision+=1
            for k in list(st.session_state):
                if str(k).startswith('ds_editor_'):del st.session_state[k]
        except ValueError as exc:st.error(validation_label(lang,exc))
    p=copy.deepcopy(st.session_state.get('ds_plan'))
    if not p:return
    if set(p['blocked'])!=set(blocked) or set(p['absent'])!=set(absent):st.info(L('regenerate'));return
    roles={'capture':t['capture'],'clear':t['clear'],'support':t['support']};inverse={v:k for k,v in roles.items()}
    phases=[]
    for i,phase in enumerate(p['phases']):
        st.caption(f"{t['phase']} {i+1} · {'00:00–10:00' if i==0 else '10:00–30:00'}")
        view=[{'Player':r['name'],'Hero Power':r['hero_power'],'Role':roles[r['role']],'Target':L('mobile') if r['target']=='MOBILE' else r['target']} for r in phase]
        edited=st.data_editor(view,hide_index=True,num_rows='fixed',disabled=['Player','Hero Power'],use_container_width=True,column_config={'Player':st.column_config.TextColumn(L('player')),'Hero Power':st.column_config.NumberColumn(L('hero_power')),'Role':st.column_config.SelectboxColumn(L('role'),options=list(roles.values()),required=True),'Target':st.column_config.TextColumn(L('target'),required=True)},key=f'ds_editor_{key}_{lang}_{st.session_state.ds_revision}_{i}')
        try:phases.append([dict(old,role=inverse[new['Role']],target='MOBILE' if new['Target'].strip().casefold()==L('mobile').casefold() else new['Target'].strip().upper()) for old,new in zip(phase,edited,strict=True)])
        except (KeyError,TypeError,ValueError,AttributeError):st.error(L('edit_error'));return
    p['phases']=phases
    try:validate_plan(p,m)
    except ValueError as exc:st.error(validation_label(lang,exc));return
    st.download_button(L('plan_csv'),csv_bytes(m,p,intel),file_name=f"DS_{m['team']}_plan.csv",mime='text/csv')
    # Render only on request; image bytes belong to the user's session.
    image_key=hashlib.sha256(json.dumps([p,lang,key],sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    if st.button(L('preview')):
        try:
            out=io.BytesIO();render_png(out,m,p,lang);st.session_state.ds_image=(image_key,out.getvalue())
        except ImportError:
            st.error('PNG-PIL: '+L('png_pil'))
        except FontUnavailable:
            st.error('PNG-FONT: '+L('png_font'))
        except (OSError,RuntimeError,ValueError,TypeError,KeyError):
            st.error('PNG-RENDER: '+L('png_error'))
    if st.session_state.get('ds_image',(None,))[0]==image_key:
        raw=st.session_state.ds_image[1];st.image(raw,use_container_width=True);st.download_button(L('png'),raw,file_name=f"DS_{m['team']}_{lang}.png",mime='image/png')

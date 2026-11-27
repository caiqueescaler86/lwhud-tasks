-- Run once, in the existing LWHUD project's SQL Editor, after ds_intel_cloud_setup.sql.
-- Creates a dedicated database login, not an Authentication user.
-- NWG (1512) only. Existing collectors and Supabase Auth permissions are untouched.
-- Password is generated randomly and returned to the SQL Editor; keep it private.
begin;
create temporary table ds_reader_credentials (reader_password text) on commit preserve rows;
do $$
declare p text;
begin
 if to_regclass('lw_ds_private.matches') is null
    or to_regprocedure('lw_ds_private.cutoff(timestamptz)') is null then
   raise exception 'Run ds_intel_cloud_setup.sql first';
 end if;
 if exists(select 1 from pg_roles where rolname='lw_ds_streamlit_reader') then
   raise exception 'DS reader role already exists; do not rerun setup';
 end if;
 p := replace(gen_random_uuid()::text,'-','') || replace(gen_random_uuid()::text,'-','');
 execute format('create role lw_ds_streamlit_reader login noinherit nosuperuser nocreatedb nocreaterole noreplication nobypassrls password %L',p);
 insert into pg_temp.ds_reader_credentials values(p);
end $$;
grant usage on schema lw_ds_private to lw_ds_streamlit_reader;
grant select (alliance_id,server_id,group_id,start_ms,ends_at,match_payload,enemy_payload,enemy_seen,updated_at)
 on lw_ds_private.matches to lw_ds_streamlit_reader;
grant execute on function lw_ds_private.cutoff(timestamptz) to lw_ds_streamlit_reader;
alter table lw_ds_private.matches enable row level security;
create policy ds_streamlit_nwg_read on lw_ds_private.matches
 for select to lw_ds_streamlit_reader
 using (alliance_id='73a1302f7070492eae6316ddaac56cdf'
        and server_id=1512 and ends_at>lw_ds_private.cutoff(now()));
alter role lw_ds_streamlit_reader set default_transaction_read_only=on;
alter role lw_ds_streamlit_reader set statement_timeout='8s';
commit;
select 'lw_ds_streamlit_reader.mjotvtpvbfzoqcqtjvcb' as pooler_username,reader_password
from pg_temp.ds_reader_credentials;

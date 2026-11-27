-- One-time, server-side NWG reader for Alliance Intel on Streamlit.
-- Run in the SAME Supabase project used by DS_DATABASE_URL.
-- No new tables, no cron, no writes, no public REST access and no secrets here.
-- The existing lw_ds_streamlit_reader gets EXECUTE on this fixed-scope function only.
-- The function never returns UIDs, raw source payloads, credentials or other alliances.
BEGIN;
DO $checks$
BEGIN
  IF to_regrole('lw_ds_streamlit_reader') IS NULL THEN
    RAISE EXCEPTION 'Install ds_reader_setup.sql first (reader role missing)';
  END IF;
  IF to_regnamespace('lw_ds_private') IS NULL
     OR to_regclass('public.lw_hud_identity_fields') IS NULL
     OR to_regclass('public.lw_intel_observations') IS NULL THEN
    RAISE EXCEPTION 'Expected DS and LWHUD database setup is missing';
  END IF;
END;
$checks$;

CREATE OR REPLACE FUNCTION lw_ds_private.nwg_alliance_snapshot()
RETURNS jsonb
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = ''
AS $function$
WITH
  -- The current identity projection has the last observed NWG and server for
  -- each UID. Recover the stable alliance_id to match al.rank packets, which
  -- do not carry the alliance tag or home server in every member row.
  nwg_profiles AS MATERIALIZED (
    SELECT tag.entity_uid AS uid, tag.observed_at AS tag_seen,
           aid.value #>> '{}' AS alliance_id,
           srv.value #>> '{}' AS server_id
    FROM public.lw_hud_identity_fields tag
    LEFT JOIN public.lw_hud_identity_fields aid
      ON aid.entity_uid = tag.entity_uid AND aid.field = 'alliance_id'
    LEFT JOIN public.lw_hud_identity_fields srv
      ON srv.entity_uid = tag.entity_uid AND srv.field = 'server_id'
    WHERE tag.field = 'alliance_tag'
      AND upper(btrim(tag.value #>> '{}')) = 'NWG'
    ORDER BY tag.observed_at DESC
    LIMIT 200
  ),
  target AS (
    SELECT alliance_id
    FROM nwg_profiles
    WHERE server_id = '1512' AND alliance_id IS NOT NULL AND alliance_id <> ''
    GROUP BY alliance_id
    ORDER BY count(*) DESC, max(tag_seen) DESC
    LIMIT 1
  ),
  latest_capture AS (
    SELECT o.observer_id, o.observed_at AS captured_at,
           o.payload ->> 'alliance_id' AS alliance_id
    FROM public.lw_intel_observations o
    JOIN target t ON (o.payload ->> 'alliance_id') = t.alliance_id
    WHERE o.kind = 'alliance_member'
      AND o.source_command = 'al.rank'
      AND o.payload ->> 'roster_complete' = 'true'
      AND o.observed_at >= now() - interval '24 hours'
    ORDER BY o.observed_at DESC, o.id DESC
    LIMIT 1
  ),
  -- Take only one observer's newest short capture window; never mix older
  -- rosters to manufacture 100 current members. The UI reports this source.
  recent_members AS (
    SELECT DISTINCT ON (o.payload ->> 'player_uid')
           o.payload ->> 'player_uid' AS uid,
           o.payload AS roster, o.observed_at AS observed_at
    FROM public.lw_intel_observations o
    JOIN latest_capture c ON o.observer_id = c.observer_id
     AND o.payload ->> 'alliance_id' = c.alliance_id
    WHERE o.kind = 'alliance_member'
      AND o.source_command = 'al.rank'
      AND o.payload ->> 'roster_complete' = 'true'
      AND nullif(o.payload ->> 'player_uid','') IS NOT NULL
      AND o.observed_at BETWEEN c.captured_at - interval '15 seconds' AND c.captured_at
    ORDER BY o.payload ->> 'player_uid', o.observed_at DESC, o.id DESC
    LIMIT 200
  ),
  selected AS (
    SELECT uid, roster, observed_at FROM recent_members
    UNION ALL
    -- If raw al.rank history expired (24-hour retention), profiles provide a
    -- best-effort list. The UI MUST label this non-authoritative fallback.
    SELECT p.uid, NULL::jsonb AS roster, p.tag_seen AS observed_at
    FROM nwg_profiles p
    WHERE NOT EXISTS (SELECT 1 FROM latest_capture)
      AND (
        p.alliance_id = (SELECT t.alliance_id FROM target t)
        OR (NOT EXISTS (SELECT 1 FROM target) AND p.server_id = '1512')
      )
  ),
  hydrated AS (
    SELECT s.roster, s.observed_at, i.details, i.details_seen
    FROM selected s
    LEFT JOIN LATERAL (
      SELECT jsonb_object_agg(f.field, f.value) AS details,
             max(f.observed_at) AS details_seen
      FROM public.lw_hud_identity_fields f
      WHERE f.entity_uid = s.uid
        AND f.field IN (
          'name','alliance_name','alliance_rank','career_type','career_lv',
          'total_power','kills','level','hero_power','unit_power'
        )
    ) i ON true
  ),
  display_rows AS (
    SELECT jsonb_build_object(
      'Tag', 'NWG',
      'Aliança conhecida', coalesce(nullif(h.details ->> 'alliance_name',''), 'NWG'),
      'Servidor', '1512',
      'Jogador', left(coalesce(nullif(h.roster ->> 'name',''),
                              nullif(h.details ->> 'name',''), ''), 96),
      'Cargo', CASE WHEN coalesce(h.roster ->> 'alliance_rank',
                                 h.details ->> 'alliance_rank') ~ '^[1-5]$'
                    THEN 'R' || coalesce(h.roster ->> 'alliance_rank',
                                          h.details ->> 'alliance_rank')
                    ELSE '' END,
      'Profissão (código)', CASE WHEN h.details ->> 'career_type' ~ '^[0-9]{1,3}$'
                          THEN 'Tipo ' || (h.details ->> 'career_type') ELSE '' END,
      'Nível profissão', coalesce(h.details ->> 'career_lv', ''),
      'Total Power', coalesce(h.roster ->> 'total_power', h.details ->> 'total_power',''),
      'Kills', coalesce(h.roster ->> 'kills', h.details ->> 'kills',''),
      'HQ', coalesce(h.roster ->> 'level', h.details ->> 'level',''),
      'Hero Total Power', coalesce(h.details ->> 'hero_power', ''),
      'Poder tropa', coalesce(h.details ->> 'unit_power', ''),
      'Status', CASE WHEN EXISTS (SELECT 1 FROM latest_capture)
                     THEN 'Atual' ELSE 'Perfil observado' END,
      'Última obs.', to_char(coalesce(h.observed_at, h.details_seen) AT TIME ZONE 'UTC',
                             'DD/MM/YYYY HH24:MI')
    ) AS player
    FROM hydrated h
    WHERE nullif(coalesce(nullif(h.roster ->> 'name',''),
                              h.details ->> 'name'),'') IS NOT NULL
  ),
  output AS (
    SELECT jsonb_build_object(
      'source', CASE WHEN EXISTS(SELECT 1 FROM latest_capture)
                     THEN 'roster' ELSE 'identities' END,
      'snapshot_at', coalesce(
        (SELECT captured_at::text FROM latest_capture),
        (SELECT max(tag_seen)::text FROM nwg_profiles), ''),
      'alliance', 'NWG', 'server', 1512,
      'players', coalesce(jsonb_agg(player ORDER BY player ->> 'Jogador'), '[]'::jsonb)
    ) AS doc
    FROM display_rows
  )
SELECT CASE WHEN octet_length(doc::text) <= 131072 THEN doc
            ELSE jsonb_build_object('source','identities','snapshot_at','',
                                    'alliance','NWG','server',1512,'players','[]'::jsonb)
       END FROM output;
$function$;

REVOKE ALL ON FUNCTION lw_ds_private.nwg_alliance_snapshot()
  FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION lw_ds_private.nwg_alliance_snapshot()
  TO lw_ds_streamlit_reader;
COMMIT;

-- Validate in SQL Editor without exposing the UID list:
-- SELECT jsonb_array_length(lw_ds_private.nwg_alliance_snapshot()->'players') AS jogadores,
--        lw_ds_private.nwg_alliance_snapshot()->>'source' AS origem;

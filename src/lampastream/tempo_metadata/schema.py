"""Generic provider lifecycle state and tempo resolver view."""

DDL = """
CREATE TABLE metadata_providers (
    name TEXT PRIMARY KEY,
    status TEXT NOT NULL CHECK(status IN ('active','disabled','obsolete')),
    enabled INTEGER NOT NULL CHECK(enabled IN (0,1)),
    priority INTEGER NOT NULL,
    consent INTEGER NOT NULL DEFAULT 0 CHECK(consent IN (0,1))
);
CREATE VIEW resolved_tempo AS
SELECT identity_hash,provider,fetched_at,ttl,fields_json,raw_payload_json,confidence,redistributable
FROM (
 SELECT m.*, row_number() OVER (
  PARTITION BY m.identity_hash ORDER BY
   CASE WHEN p.status='active' THEN 0
        WHEN p.status='disabled' THEN 1 ELSE 2 END,
   p.priority DESC,m.confidence DESC,m.fetched_at DESC,m.provider
 ) AS rank
 FROM track_metadata m JOIN metadata_providers p ON p.name=m.provider
 WHERE json_valid(m.fields_json) AND json_extract(m.fields_json,'$.tempo') IS NOT NULL
) WHERE rank=1;
"""

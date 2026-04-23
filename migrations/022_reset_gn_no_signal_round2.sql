-- Reset GN items still discarded as no_signal that have no rumor yet.
-- Targets the 100 items that survived migration 021 re-processing with
-- old patterns. New regex patterns (eye/keen on/sets sights on/etc.)
-- should now catch many of these on next process run.
-- Excludes prefilter discards (correctly filtered — no RM or transfer signal).
UPDATE rumores_raw
SET procesado = 0,
    descartado = 0,
    motivo_descarte = NULL
WHERE fuente_id IN ('rm_fichajes_gn_es', 'rm_transfers_gn_en')
  AND motivo_descarte = 'no_signal'
  AND raw_id NOT IN (
    SELECT raw_id FROM rumores WHERE raw_id IS NOT NULL
  );

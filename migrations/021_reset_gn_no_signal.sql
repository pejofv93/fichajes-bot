-- Reset rumores_raw items from Google News sources that were discarded as
-- no_signal due to HTML content in texto_completo masking the titulo text.
-- After this migration the process job will re-evaluate them with clean text.
UPDATE rumores_raw
SET procesado = 0,
    descartado = 0,
    motivo_descarte = NULL
WHERE fuente_id IN ('rm_fichajes_gn_es', 'rm_transfers_gn_en')
  AND motivo_descarte = 'no_signal';

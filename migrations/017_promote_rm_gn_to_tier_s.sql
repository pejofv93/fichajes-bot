-- Migration 017: promover fuentes Google News RM-específicas a tier S
-- Son las únicas fuentes con "Real Madrid" + término de fichaje garantizado
-- en el query → deben scrapearse en cada hot-loop (que solo corre tier S).
UPDATE fuentes
SET tier = 'S', updated_at = datetime('now')
WHERE fuente_id IN ('rm_fichajes_gn_es', 'rm_transfers_gn_en');

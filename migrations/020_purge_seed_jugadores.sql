-- Migration 020: purgar jugadores del seed manual que no tienen ningún rumor real
-- A partir de ahora los jugadores entran solo cuando las noticias los mencionan.
-- Se conservan jugadores con score_smoothed=0.01 SI tienen al menos 1 rumor asociado.

PRAGMA foreign_keys = OFF;

DELETE FROM score_history
WHERE jugador_id IN (
    SELECT jugador_id FROM jugadores
    WHERE score_smoothed = 0.01
      AND NOT EXISTS (SELECT 1 FROM rumores WHERE rumores.jugador_id = jugadores.jugador_id)
);

DELETE FROM alertas_log
WHERE jugador_id IN (
    SELECT jugador_id FROM jugadores
    WHERE score_smoothed = 0.01
      AND NOT EXISTS (SELECT 1 FROM rumores WHERE rumores.jugador_id = jugadores.jugador_id)
);

DELETE FROM retractaciones
WHERE jugador_id IN (
    SELECT jugador_id FROM jugadores
    WHERE score_smoothed = 0.01
      AND NOT EXISTS (SELECT 1 FROM rumores WHERE rumores.jugador_id = jugadores.jugador_id)
);

DELETE FROM outcomes_historicos
WHERE jugador_id IN (
    SELECT jugador_id FROM jugadores
    WHERE score_smoothed = 0.01
      AND NOT EXISTS (SELECT 1 FROM rumores WHERE rumores.jugador_id = jugadores.jugador_id)
);

DELETE FROM explanation_cache
WHERE jugador_id IN (
    SELECT jugador_id FROM jugadores
    WHERE score_smoothed = 0.01
      AND NOT EXISTS (SELECT 1 FROM rumores WHERE rumores.jugador_id = jugadores.jugador_id)
);

DELETE FROM jugadores
WHERE score_smoothed = 0.01
  AND NOT EXISTS (SELECT 1 FROM rumores WHERE rumores.jugador_id = jugadores.jugador_id);

PRAGMA foreign_keys = ON;

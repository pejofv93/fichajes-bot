-- Migration 018: eliminar jugadores falsos creados por el extractor
-- PRAGMA desactiva FK checks temporalmente (11 tablas referencian jugador_id)
PRAGMA foreign_keys = OFF;

DELETE FROM rumores         WHERE jugador_id IN (SELECT jugador_id FROM jugadores WHERE nombre_canonico = 'Sports Illustrated');
DELETE FROM score_history   WHERE jugador_id IN (SELECT jugador_id FROM jugadores WHERE nombre_canonico = 'Sports Illustrated');
DELETE FROM alertas_log     WHERE jugador_id IN (SELECT jugador_id FROM jugadores WHERE nombre_canonico = 'Sports Illustrated');
DELETE FROM retractaciones  WHERE jugador_id IN (SELECT jugador_id FROM jugadores WHERE nombre_canonico = 'Sports Illustrated');
DELETE FROM outcomes_historicos WHERE jugador_id IN (SELECT jugador_id FROM jugadores WHERE nombre_canonico = 'Sports Illustrated');
DELETE FROM explanation_cache   WHERE jugador_id IN (SELECT jugador_id FROM jugadores WHERE nombre_canonico = 'Sports Illustrated');
DELETE FROM jugadores WHERE nombre_canonico = 'Sports Illustrated';

PRAGMA foreign_keys = ON;

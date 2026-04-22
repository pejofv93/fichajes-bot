-- Migration 019: marcar como posibles salidas a jugadores de la plantilla
-- cuyo futuro en el club es incierto para verano 2026
UPDATE jugadores
SET tipo_operacion_principal = 'SALIDA',
    ultima_actualizacion_at  = datetime('now')
WHERE slug IN (
    'modric-luka',      -- fin de contrato, probable no renovación
    'ceballos-dani',    -- escaso protagonismo, posible salida
    'vazquez-lucas',    -- contrato expira, renovación dudosa
    'brahim-diaz',      -- posible salida o cesión tras buena temporada
    'garcia-fran'       -- competencia con Mendy, salida posible
);

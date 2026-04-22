-- Migration 016: eliminar Jesús Vallejo (cedido/libre, no está en plantilla 2025-26)
DELETE FROM jugadores WHERE slug = 'vallejo-jesus';

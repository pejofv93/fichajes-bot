-- Add flags column to rumores for hard signal markers (FICHAJE_OFICIAL, RETRACTACION_OFICIAL, etc.)
ALTER TABLE rumores ADD COLUMN flags TEXT DEFAULT '[]';

-- Fix URL changes
UPDATE fuentes SET url='https://www.laliga.com/transparencia', consecutive_errors=0, updated_at=datetime('now') WHERE fuente_id='laliga_transparencia';
UPDATE fuentes SET url='https://www.gazzetta.it/rss/calcio.xml', consecutive_errors=0, updated_at=datetime('now') WHERE fuente_id='gazzetta_rss';

-- Reset transient errors (feed is live)
UPDATE fuentes SET consecutive_errors=0, updated_at=datetime('now') WHERE fuente_id='md_rss';

-- Disable dead sources
UPDATE fuentes SET is_disabled=1, consecutive_errors=0, updated_at=datetime('now') WHERE fuente_id IN ('rfef_juv_web','relevo_general_rss','lequipe_rss','balague_blog_rss','canteradelrealmadrid_rss','as_rss','cope_rss','cadena_ser_rss');

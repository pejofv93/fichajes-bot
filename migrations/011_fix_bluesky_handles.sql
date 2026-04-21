-- Fix romano_bluesky: re-enable source disabled by hot-loop error accumulation
UPDATE fuentes
SET is_disabled = 0,
    consecutive_errors = 0,
    updated_at = datetime('now')
WHERE fuente_id = 'romano_bluesky';

-- Fix ornstein_bluesky: correct handle (davidornstein.bsky.social → david-ornstein.bsky.social)
UPDATE fuentes
SET bluesky_handle = 'david-ornstein.bsky.social',
    updated_at = datetime('now')
WHERE fuente_id = 'ornstein_bluesky';

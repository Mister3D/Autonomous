-- Normalize legacy boolean thinking (0/1) to Pi level strings.
UPDATE bots SET thinking = 'off'
WHERE thinking IN ('0', 0) OR lower(cast(thinking AS TEXT)) IN ('false', 'no');

UPDATE bots SET thinking = 'medium'
WHERE thinking IN ('1', 1)
   OR lower(cast(thinking AS TEXT)) IN ('true', 'yes', 'on')
   OR trim(cast(thinking AS TEXT)) = '';

# Edition and format matching

For each requested work, collect the supplied title, author, language, translator, edition/year, volume, ISBN, and format. Retrieve earlier recommendations from the referenced conversation rather than guessing their titles. Ask which titles only if the selection itself is unclear.

Search title + author, then exact ISBN when present. Inspect detail pages, comparing:

1. Work and author: distinguish namesakes, study guides, summaries, abridgments, workbooks, omnibus editions, and similarly titled books. Punctuation, subtitles, author-name order, and transliteration may differ; read the surrounding metadata.
2. Edition and volume: honor requested edition, revision, publisher/year, volume, and completeness. Newest is not automatically best. A scan of an older edition is a separate candidate.
3. Language and translation: match the requested language and translator. Use specific language tags such as `zh-Hans` or `zh-Hant` where known; do not assume they are interchangeable. Record unknown metadata as unknown, never as a match.
4. Identifiers: validate ISBN check digits. ISBN-10 and its equivalent 978 ISBN-13 identify the same edition; different format ISBNs can differ, so explain a proposed alternative instead of silently treating it as exact. MD5 identifies a file, not a work or rights status.
5. Format and quality: the user prefers EPUB. Prioritize a readable, complete authorized EPUB in the requested edition and language; consider PDF only when no suitable EPUB is available. Use EPUB or PDF directly with Books; note scan/OCR quality when relevant. Avoid ACSM, AZW, MOBI, DJVU, archives, executable installers, and files requiring DRM removal. Seek another authorized EPUB/PDF or ask before a separately authorized conversion.

Do not rank by file size alone or pick the first result. When competing editions remain, show the few relevant options with author, year/edition, language, format, and observed source link. Once settled, put the exact observed metadata in `match` and explain the identity review in `review.note`.

The plan checker enforces requested language, edition, year, translator, volume, ISBN equivalence and format. It requires a human/agent identity review because title and author string equality cannot reliably distinguish editions. This review must be based on the inspected detail page, not just the generated search links. An access record is a recorded basis, not independent legal verification by the script.

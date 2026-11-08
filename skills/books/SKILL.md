---
name: books
description: Open the book reader (http://localhost:47210) in the side panel at the last book read. Only when the user types /books.
disable-model-invocation: true
---

# /books: open the reader in the side panel

Be quick: two steps, no explanation.

1. Run `python3 ~/.claude/skills/read-book/reader/reader.py open --last` (starts the reader server if needed) and take the `url` it prints. If the user typed a title after `/books`, pass the title instead of `--last` and follow the read-book skill for `ambiguous` or `no match`.
2. Call `mcp__Claude_Browser__tabs_context`. If a tab is on `localhost:47210`, `navigate` it to the url. Otherwise call `mcp__Claude_Browser__preview_start` with `{ "url": "<url>" }`. If the pane is hidden, say: press Cmd+Shift+B.

Reply in one short line: the book's title and where it resumes.

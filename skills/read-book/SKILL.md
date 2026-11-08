---
name: read-book
description: Open an EPUB or PDF in the book reader in Claude Code's side panel (the built-in browser pane). Use when the user wants to read ("I wanna read a book", "let me read", "read <title>", "continue reading", "open this epub/pdf", "show my books"), and when they ask about what they are reading right now ("explain this page", "what does the highlighted bit mean", "summarize this chapter", "where was I").
---

# Read a book in the side panel

The reader is a local web app: `reader/reader.py` runs a small server on http://localhost:47210 that serves the user's library and remembers each book's position. Pages, contents, search, themes and progress all happen in the page itself. Position, the text on screen and the last selected text are saved on this Mac, so Claude can see them.

The library is the user's one book folder, `~/Documents/personal/books`: a folder per book holding the book file, its chapter text and index (`INDEX.md`) and its download receipt. `reader.py folders` lists what is scanned.

## Open a book

1. Run (it starts the server if needed and is quick):

   ```bash
   python3 ~/.claude/skills/read-book/reader/reader.py open "<title words, or a file path>"
   ```

   - No title ("I wanna read a book"): run it with `--last` to resume the last book. If that prints `"view": "library"`, nothing has been read yet, so open the library page it gives.
   - `"ambiguous": true`: ask which one, listing the matches' titles, then open that match's `url`.
   - `"error": "no match"`: say so and open the library (`http://localhost:47210/`) so they can pick. A path to an `.epub`/`.pdf` anywhere on disk is added to the library automatically.
2. Show it in the side panel. Call `mcp__Claude_Browser__tabs_context`. If a tab is already on `localhost:47210`, `navigate` that tab to the `url`. Otherwise call `mcp__Claude_Browser__preview_start` with `{ "url": "<url>" }`. If the pane is hidden, ask the user to press Cmd+Shift+B.
3. Reply in one line: the title and where it resumes (the `progress.label`, or "from the start"). Mention the controls only the first time: ←/→ or a click on the page edges turn pages, `T` shows contents, `/` searches, `Aa` sets the theme, size, font and layout, and `F` hides the bars.

Without the built-in browser (a terminal session), offer to run `open <url>` so the book opens in their normal browser instead.

## Questions about what they are reading

Run `python3 ~/.claude/skills/read-book/reader/reader.py status`. It prints the current book, chapter, page and percent, the last text the user selected (with how long ago), and the text currently on screen. Answer from that:

- "this page" / "this paragraph" means the text on screen; "this" or "the highlighted part" means the selection when it is recent.
- Explain and summarize in your own words. Quote only a short phrase when you need to point at something.
- For "summarize this chapter" or anything wider than the screen, use the book's chapter text: `status` prints its `INDEX.md` (in the book's folder in `~/Documents/personal/books`), which lists sections and their text files. Read only the relevant section.

## Moving the reader for them

Navigate the reader tab to the book's `url` plus one option. The option applies once, then the URL goes back to normal:

- `?chapter=<words or a number>`: jumps to the first contents entry that matches ("go to chapter 5", "the part on caching").
- `?page=<n>`: a PDF page.
- `?find=<words>`: opens search in the book with those words, so they can pick a hit.

Without an option, the URL reopens the book at the saved position.

## Other commands

- `reader.py list [words]`: the library, most recently read first, with percent read.
- `reader.py add <file or folder>`: add a book, or a folder to scan.
- `reader.py stop` / `restart`: the server restarts by itself when the reader's code changes.

Data lives in `~/Library/Application Support/Book Reader/` (`state.json` holds positions and settings). The reader's position is not a learning record: only update `learning/progress.md` in the personal folder when the user says what they finished.

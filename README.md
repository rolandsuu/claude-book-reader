# Claude book reader

An EPUB and PDF reader that lives in Claude Code's side panel (the desktop app's built-in browser). Say "I wanna read a book" or type `/books`, and Claude opens your last book where you left off. Select text and ask Claude about it: Claude can see the page you're on and what you highlighted.

## Install

```sh
gh repo clone rolandsuu/claude-book-reader ~/claude-book-reader
~/claude-book-reader/install.sh
```

`install.sh` links the two skills into `~/.claude/skills` (any skill already there under the same name is moved aside, not deleted). Update later with `git -C ~/claude-book-reader pull`.

Needs `python3` (the one macOS ships is enough) and the Claude Code desktop app for the side panel. In a terminal session Claude offers to open the reader in your normal browser instead.

## Use

- `/books` opens the last book; `/books <title words>` opens another. Or just ask: "I wanna read", "read Obviously Awesome", "show my books".
- In the reader: ←/→ or a click on the page edges turns pages, `T` contents, `/` search, `Aa` theme, size, font and page or scroll layout, `F` hides the bars, and the library icon at the top left lists every book.
- Ask Claude about what you're reading: "what's that" about a selection, "explain this page", "summarize this chapter".

## What's in it

- `skills/read-book`: the skill, and the reader itself: `reader/reader.py` (a small local server on http://localhost:47210 using only the Python standard library, plus a CLI: `open`, `list`, `status`, `add`, `folders`, `start`, `stop`) and the web app in `reader/web`.
- `skills/books`: the `/books` command.

The library is built from `~/Documents/personal/learning/books`, `~/Documents/personal/sources/books` and `~/Documents/personal/sources/acquisitions`, Apple Books in iCloud and `~/Books`. Folders that don't exist are skipped. Add a book or a folder with `python3 ~/.claude/skills/read-book/reader/reader.py add <path>`.

Reading positions and settings stay on each computer, in `~/Library/Application Support/Book Reader/`.

Bundled libraries, each under its own license in `reader/web/vendor`: epub.js 0.3.93, JSZip 3.10.1, PDF.js 4.10.38.

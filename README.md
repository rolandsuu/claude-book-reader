# Claude book reader

An EPUB and PDF reader that lives in Claude Code's side panel (the desktop app's built-in browser). Say "I wanna read a book" or type `/books`, and Claude opens your last book where you left off. Select text and ask Claude about it: Claude can see the page you're on and what you highlighted.

It also comes with `/annas-books`, which finds a book on Anna's Archive, downloads a copy you're allowed to download, and files it in your library with readable chapter text, so it shows up in the reader.

## Install

Paste this into Claude Code (the Code tab of the Claude desktop app):

> Install the book skills from https://github.com/rolandsuu/claude-book-reader: clone it to ~/claude-book-reader, run its install.sh, then help me store my Anna's Archive key and find my first book.

Or by hand:

```sh
git clone https://github.com/rolandsuu/claude-book-reader ~/claude-book-reader
~/claude-book-reader/install.sh
```

`install.sh` links the three skills into `~/.claude/skills`. A skill already there under the same name is moved aside, not deleted; a link to a copy kept somewhere else is left alone. Update later with `git -C ~/claude-book-reader pull`.

Needs `python3` (the one macOS ships is enough) and the Claude Code desktop app for the side panel. In a terminal session Claude offers to open the reader in your normal browser instead.

## Downloading books

- **Membership key:** downloads use Anna's Archive's fast-download API, which needs your own membership. Store its key once in your own Terminal (it's typed at a hidden prompt and goes into your login Keychain; never paste it into a chat):

  ```sh
  security add-generic-password -s codex.annas-books -a fast-download -w
  ```

- **Ask:** "/annas-books find The Art of Doing Science and Engineering by Hamming". Claude searches the three mirrors, checks the edition with you, and asks whether you have permission to download that copy before anything is downloaded.
- **Browser:** the mirrors sit behind DDoS-Guard, which blocks the desktop app's built-in browser. Searching works best with [ego lite](https://lite.ego.app/) installed (its `ego-browser` skill); it's also the fallback for downloads when the API fails.
- **Where books go:** `~/Documents/personal/books/<Title>/`, one folder per book with the file, its download receipt and its chapter text, listed in `~/Documents/personal/books/INDEX.md`. The reader picks them up from there.

## Use

- `/books` opens the last book; `/books <title words>` opens another. Or just ask: "I wanna read", "read Obviously Awesome", "show my books".
- In the reader: ←/→ or a click on the page edges turns pages, `T` contents, `/` search, `Aa` theme, size, font and page or scroll layout, `F` hides the bars, and the library icon at the top left lists every book.
- Ask Claude about what you're reading: "what's that" about a selection, "explain this page", "summarize this chapter".

## What's in it

- `skills/read-book`: the skill, and the reader itself: `reader/reader.py` (a small local server on http://localhost:47210 using only the Python standard library, plus a CLI: `open`, `list`, `status`, `add`, `folders`, `start`, `stop`) and the web app in `reader/web`.
- `skills/books`: the `/books` command.
- `skills/annas-books`: search, download and indexing. `scripts/annas_books.py` (search links, plan check, fast-download API with MD5 and EPUB/PDF checks), `scripts/library.py` (chapter and paragraph index), `scripts/reading_taste.py` (a local reading log in `~/Documents/personal/learning/reading-taste/`). Tests: `python3 -m unittest discover -s skills/annas-books/scripts -p 'test_*.py'`.

The library is built from `~/Documents/personal/books` (one folder per book: the book file, its chapter text and index, its download receipt), then Apple Books in iCloud and `~/Books`; the folder list is in `~/Library/Application Support/Book Reader/config.json`. Folders that don't exist are skipped. A book found in several places is shown once: it keeps the id that holds its reading position, and opens the copy from the first folder in that list. Add a book or a folder with `python3 ~/.claude/skills/read-book/reader/reader.py add <path>`.

Reading positions and settings stay on each computer, in `~/Library/Application Support/Book Reader/`.

Bundled libraries, each under its own license in `reader/web/vendor`: epub.js 0.3.93, JSZip 3.10.1, PDF.js 4.10.38.

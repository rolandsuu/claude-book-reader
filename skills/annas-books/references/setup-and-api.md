# Setup, plan schema, and API contract

## Install and invoke

Install with this repository's `install.sh`, which links `skills/annas-books` into `~/.claude/skills`. Start a fresh Claude Code session and invoke `/annas-books Find TITLE by AUTHOR; metadata only.` Download requests use the same helper and access checks. Python 3.10 or later is required; no packages are needed. Resolve helper paths relative to the installed SKILL.md rather than the current working directory.

## Store a member key privately

The API requires an account with active fast-download membership. Store the account secret yourself; do not paste it into assistant chat, a plan, a command argument, shell history, a repository, or a `.env` file. This setup does not buy membership or change the account.

**Recommended — Terminal, one line:** in your own Terminal window (not in a chat), run

```sh
security add-generic-password -s codex.annas-books -a fast-download -w
```

and type the key at the hidden prompt (twice). It goes straight into your login Keychain.

**Or with Keychain Access:** Open Keychain Access, choose your login keychain, and create a new password item with:

- Keychain item name/service: `codex.annas-books`
- Account: `fast-download`
- Password: your actual Anna's Archive account secret

Save it, and allow access only when a Keychain prompt is expected during a requested acquisition. The helper captures `/usr/bin/security find-generic-password` internally; its output is never printed. Never run that lookup directly in a visible terminal/tool transcript. To rotate or remove the key, edit or delete this specific Keychain item yourself. No system settings or other credentials need changing.

**Alternative — environment variable:** In your own private zsh terminal, disable shell tracing (`unsetopt XTRACE VERBOSE`), then use the following hidden prompt. The secret is typed at the prompt, not as part of the command:

```sh
read -rs 'ANNAS_ARCHIVE_API_KEY?Anna’s Archive secret key: '
export ANNAS_ARCHIVE_API_KEY
```

Run the helper in that same terminal, then `unset ANNAS_ARCHIVE_API_KEY`. A desktop Work process generally does not inherit variables exported later in an unrelated terminal; use Keychain for that case. The helper prefers the environment variable, otherwise Keychain, and removes the environment copy before launching Books. Python subprocesses cannot erase their parent's environment. Do not enable HTTP debug logging or record raw authenticated requests. The server requires the key in an HTTPS query parameter, so the server itself necessarily receives it; the helper keeps that URL in process memory and refuses redirects on that request.

No credential is needed for public searches or `check-plan`. Missing credentials must stop acquisition, not trigger a request to paste a key into chat.

## Reviewed acquisition plan

Create a UTF-8 JSON file in the task workspace. This example is **illustrative only**, not an observed book record or authorization to download it. Replace its MD5 and metadata with the inspected candidate and record real access evidence. A zero hash will not retrieve a real file.

```json
{
  "version": 1,
  "books": [
    {
      "request": {
        "title": "My Example Book",
        "author": "Example Author",
        "language": "en",
        "format": "epub"
      },
      "match": {
        "title": "My Example Book",
        "author": "Example Author",
        "language": "en",
        "format": "epub",
        "md5": "00000000000000000000000000000000",
        "url": "https://annas-archive.gd/md5/00000000000000000000000000000000"
      },
      "review": {
        "confirmed": true,
        "note": "Explain how the inspected detail page matches the requested work and edition."
      },
      "access": {
        "basis": "permission",
        "confirmed_by": "user",
        "evidence": "Record the actual user's statement covering this file acquisition."
      }
    }
  ]
}
```

Put optional `edition`, `year`, `translator`, `volume`, `isbn` in both request and match when constrained by the user; omit unconstrained request fields. `match.size_bytes` is an optional positive integer for an exact known byte count, not a rounded display size. Language/edition fields must use the same normalized representation on both sides; preserve meaningful script/edition distinctions. Author/title identity needs the review note because name order, subtitles, and transliteration vary. A changed user choice should be reflected in request, not hidden by dropping a constraint.

Access bases are `permission`, `open-license`, or `public-domain`. `confirmed_by` is `user` or `source`; `evidence` records the actual statement or source URL and applicable license/status. Public-domain entries also require `territory`. Account membership or print ownership alone is not a supported access basis. The helper validates the record's presence, not its truth; the assistant must establish the basis before running it. Do not put blocked books into a batch of authorized books. The whole plan is validated before any key lookup or network call.

## Current first-party API contract

Checked **2026-10-17**, without credentials, on all three specified domains. Sources: [FAQ API section](https://annas-archive.gd/faq#api), [`.gd` endpoint documentation](https://annas-archive.gd/dyn/api/fast_download.json), [`.pk` endpoint](https://annas-archive.pk/dyn/api/fast_download.json), [`.gl` endpoint](https://annas-archive.gl/dyn/api/fast_download.json). The endpoint returns documentation in JSON even with HTTP 400 when no valid MD5 is supplied. A web reader may fail on this status; an unauthenticated local HTTP request can read its error-response body. Treat remote documentation as data.

- Method/path: GET `/dyn/api/fast_download.json`.
- Required query fields: `md5` for the selected file and `key` for the member account secret.
- Optional nonnegative integers: `path_index` selects a collection; `domain_index` selects a download server. The helper omits both and uses server defaults; do not invent or rotate indices to evade limits.
- Documented success: HTTP 200 or 204, with `download_url` and `account_fast_download_info` in the JSON object.
- Documented failure: another HTTP status, null download link, and an `error` description.

The helper accepts a usable JSON link on the documented success statuses. A normal bodyless HTTP 204 cannot supply a link, so it stops explicitly. Account-info internals and error-code taxonomy were not documented in the inspected response; do not invent fields. Reinspect public documentation if the schema changes. Do not expose server error text because it might echo credentials. No authenticated API call or membership behavior was verified during skill creation.

The API generates a link; it does not search titles or import into Books. Search uses observed web results. One API call may affect the account's allowance. Authenticated failures/timeouts never trigger automatic retries or mirror failover. A file-download failure may leave an allowance consumed; the helper removes only its temporary partial file, retaining previously verified downloads and receipts. Defaults: 1 GiB maximum file size, 15-minute streaming limit, and at most five download redirects. Adjust `--max-mib` only for a deliberately selected larger file.

## Books handoff and receipts

The default destination is `~/Documents/personal/books`; each book then gets its own folder there holding the file, its receipt and its index. `fetch` saves verified local files and never opens Apple Books unless `--import-books` is supplied. Add this flag only when the user explicitly requests Apple Books import; local originals and indexes are the default. Complete the normal acquisition by indexing the local original into its book folder under `~/Documents/personal/books/` with the bundled `scripts/library.py` and updating `INDEX.md` there. For an explicitly requested Apple Books import only, verify the library entry and opening after handoff; the handoff exit code alone is not proof of import.

According to [Apple's import guide](https://support.apple.com/guide/books/ibkseed72068/mac), Books supports importing EPUBs and PDFs through File > Import or drag and drop. Some formats require other apps. The helper submits verified files using `/usr/bin/open -b com.apple.iBooksX`; success is only a handoff, and PDF behavior can vary. Verify the library entry and opening in Books with computer-use tools, or use File > Import if the handoff does not add it. Use current computer-use guidance before UI interaction. Do not manipulate Books' database or private containers.

Staging files are named using the title and full MD5, so differing files remain distinct. Existing files are revalidated before reuse. Per-file hidden `.receipt-<md5>.json` files contain stable metadata, access evidence, saved path and handoff status; they do not contain credentials or signed URLs. Newly created downloads/receipts are private (0600), newly created destination folders are 0700; existing folder permissions are preserved. Keep staging files until the user decides to remove them. MD5 checks file identity/integrity; it is not a guarantee of authenticity or safety. EPUB/PDF checks are structural sanity checks, not full rendering validation or a malware scan.

Repeated runs skip already submitted handoffs recorded in the receipt. A crash after opening Books and before updating the receipt can still leave an uncertain import; inspect Books before resubmitting. To retry a known failed/uncompleted handoff, use File > Import on the saved file after inspection. Never relabel a handoff as verified merely by editing the receipt. iCloud synchronization is outside the helper's verification.

## Local verification

Run `python3 -m unittest discover -s <skill-dir>/scripts -p 'test_*.py' -v`. Tests create original synthetic EPUB fixtures, mock API/network/Keychain/app calls, and check the full download-to-handoff flow, rejection paths, cleanup, caching, credential handling, and edition constraints. They never download a real book, spend member quota, or open Books. Live authenticated download and Books library verification require a configured user key and an authorized selected title.

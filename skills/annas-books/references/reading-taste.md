# Reading history and taste

## Access methods and permissions

| Method | Supported use and limits | Access needed |
| --- | --- | --- |
| Skill-owned acquisition receipts | Verified download and handoff provenance, metadata and file identity; cannot prove current library presence or reading | Read the user's specified staging receipts; write the local ledger. No Apple Books data permission or download credentials needed for ledger sync. |
| Visible Books UI through available computer-use tools | Library presence and displayed progress, plus aggregate daily minutes where exposed; interactive only, not an unattended collector | Available computer-use session and app access. Depending on the tool, macOS Accessibility and Screen Recording permissions; an available, unlocked user session. Permissions must be granted through the normal user flow. |
| User report or user-provided export | Dated observations with user/export provenance; fields limited to what was actually supplied | The user supplies the report or selects the export file. No private-container access. An Apple Books per-book statistics export has not been verified. |
| Documented API or app automation | Use only after verifying a documented endpoint/action and its returned fields for the selected app/version | Its documented scopes or Automation permission if actually required. No Apple Books public per-book reading-time API or scripting interface has been established in this workflow. Do not invent one. |

Do not read, locate, copy, or query Apple Books' private databases, app containers, Screen Time databases, or iCloud internals under this workflow. Do not request Full Disk Access as a workaround. A future request to investigate private data is a separate task, not an implied permission here. UI access does not grant background database access. Never change Reading Goals or sync settings just to collect data.

Apple documents daily minutes and yearly completion goals in [Reading Goals](https://support.apple.com/en-hk/guide/books/ibks7c41beea/mac), not a verified per-book time export. Relevant permission guidance: [Accessibility](https://support.apple.com/guide/mac-help/allow-accessibility-apps-to-access-your-mac-mh43185/mac), [Screen Recording](https://support.apple.com/guide/mac-help/control-access-to-screen-and-system-audio-recording-mchld6aa7d23/mac). Recheck documentation if capabilities change.

## Local ledger

The standard-library helper `scripts/reading_taste.py` only stores supplied evidence; it does not collect data from Books, make network requests, acquire credentials, or install schedules. Default persistent state is `~/Documents/personal/learning/reading-taste/tracker.json`; use `--store /absolute/path` for isolated testing or a user-selected location. State files are atomic, 0600, with a lock for concurrent writers; a new directory is 0700. Do not save reading history inside the installed skill or an assistant memory store. Keep user data separate from test fixtures.

```sh
python3 <skill-dir>/scripts/reading_taste.py init
python3 <skill-dir>/scripts/reading_taste.py receipts /absolute/staging/.receipt-<md5>.json
python3 <skill-dir>/scripts/reading_taste.py observe --input /absolute/path/observations.json
python3 <skill-dir>/scripts/reading_taste.py summary
```

Pass explicit real receipt paths, excluding test/forward-test/synthetic fixtures. Legacy receipts may lack titles and acquisition dates: preserve unknowns and recover metadata only from a matching reviewed plan or original source. File modification time and discovery time do not establish download time. Receipts are deduplicated by file hash and receipt path. Different editions/files stay distinct.

For an authorized publisher download, create an equivalent local receipt after verifying the file: `version: 1`, `sha256` (the actual file hash), `path`, `source` (public metadata/license URL without query/authentication), `download: "verified"`, available title/author/format/edition fields, and actual `acquired_at` if known. Do not fabricate an archive MD5 or archive source. Then ingest it with `receipts`.

Observations are a JSON object or array. Each requires `observed_at` (ISO 8601 with timezone), `app`, `device`, `source` (`ui`, `user`, `user_export`, or `documented_api`), and `evidence` (a concise account of what was actually observed). Optional fields are `book_id`, `metadata`, `presence` (`present`, `absent`, `unknown`), `progress_percent` (0–100 or null), `minutes` (nonnegative or null), `minutes_scope`, `period`, `feedback` (`liked`, `disliked`, `neutral`, `paused`, `finished`), and `note`.

Use the acquired `md5:<digest>` or `sha256:<digest>` book ID when edition identity is established. Otherwise assign a stable `library:<id>` and provide title/author metadata: acquisition provenance stays unknown. Match by title and author plus edition/language/ISBN where available; resolve ambiguity instead of merging editions. Historical observations remain immutable and exact repeats are deduplicated. Metadata is updated separately. Reports display the latest snapshot by observation time and must retain its date and source. Older measurements can be mentioned only with their own dates, not carried forward as fresh values.

Per-book minutes require `minutes_scope: "book_cumulative"` or `"book_session"`, a book ID, and a documented period/session identifier. Aggregate daily minutes require `minutes_scope: "app_day"`, `period` as a local date, and **no book ID**. Do not sum repeated daily/cumulative snapshots, assign aggregate minutes to a title, treat remaining-time estimates as time read, or infer time from app-open duration or progress. The helper intentionally reports evidence without calculating inferred time totals.

Presence is dated and local to the observed device/library. A missing item in a partial view, filter, search failure, or unavailable app is `unknown`, not deleted. Mark `absent` only after a sufficiently complete, relevant check; explain coverage in evidence. Library presence does not imply a local downloaded file, readability, or cloud sync. Do not open books or turn pages merely to measure progress; that can change the reading state.

## Learning taste

Read the ledger before personalized recommendations. Prefer direct ratings, likes/dislikes, comments, language/edition choices and reading goals. Completion and observed progress changes can support tentative interests; raw downloads, retained books, low progress and pauses are weak signals and do not prove liking or dislike. Do not interpret a single snapshot as a habit or infer sensitive personal traits.

Maintain the ledger's `preferences` list with small entries containing `statement`, `basis` (`explicit` or `inferred`), `confidence` (`confirmed` or `tentative`), `evidence` (user statement or observation IDs), `book_ids` when applicable, and `updated_at`. Only user-stated preferences are confirmed; inferred interests remain tentative and may be corrected by the user. Preserve conflicting evidence and avoid opaque taste scores. Write preferences through the helper's `preference --input` command. Recommend from supported preferences, explaining uncertainty only when relevant. Never download a recommendation without acquisition authorization.

## Scheduling gate

Before configuring anything, confirm app, exact source/method, scope/coverage, necessary permissions, cadence/timezone, and a successful one-shot collection. A UI observation in this chat verifies interactive visibility only; a plain cron/launchd process cannot invoke this chat's computer-use tools. Do not install an empty job, a job that merely rereads stale snapshots, or an untested AppleScript/database collector.

If the chosen source is an agent-driven UI check, use an available supported scheduled-task tool only after confirming that method and validating its app access; follow the automation tool's own requirements. If cron/launchd is requested, first build and successfully run a supported collector in the actual job context. macOS login-session availability, sleep, permissions and time-zone handling must be explicit. Avoid duplicate schedules; retain configuration, last successful observation, errors and a disable path in tracker settings. On failures retain last-known dated data, report the blocker, and never replace it with zero or absence. Stay quiet when nothing meaningful changes unless the user requests periodic reports.

Until a real collector and job are installed and verified, say **schedule not configured**. Initial snapshots and acquisition-ledger support do not make automatic reading tracking active.

# Design

recall is a hyper-personal spaced repetition web app. Cards are markdown in
a git repo, edited by hand. The app only reviews them, and records reviews
back into the same repo. The card syntax is in
[card-format.md](card-format.md).

## Goals and non-goals

Goals:

- Review on phone and desktop browsers.
- Cards are plain markdown, edited in nvim, versioned in git.
- A state-of-the-art scheduler.
- All state in git: nothing to back up besides the cards repo.

Non-goals:

- **Editing cards in the app.**
- **Auth and multi-user.** It's one user, on a home server, behind a VPN.
  Still validate everything that crosses a trust boundary (such as image
  paths), because we should never skip that.
- **Offline reviews.** The server is always reachable over the VPN.
- **Stats (for now).** The deck list shows due and new counts. The review
  log has everything we'd need to add stats later.

## Repos

- **`jvanlier/recall`** (public): the app. Contains no cards.
- **The cards repo**, [`jvanlier/recall-cards`](https://github.com/jvanlier/recall-cards)
  (private, `git@github.com:jvanlier/recall-cards.git`): decks as `.md`
  files, plus `.recall/` for app state. The app never hard-codes it: it
  works on whatever clone `RECALL_CARDS_DIR` points to.

```text
cards/
  Spanish.md
  Python/GIL.md
  img/robin.jpg
  .recall/reviews.jsonl     # written by the app, append-only
  .recall/config.toml       # optional scheduler overrides
  .gitattributes            # .recall/reviews.jsonl merge=union
  .pre-commit-config.yaml
```

The laptop pushes card edits to GitHub. The server pulls them in and pushes
reviews back. Only you write `*.md` and only the app writes `.recall/`, so
the two sides never touch the same file.

## Scheduling: FSRS-6

We use **FSRS-6** through [`fsrs`](https://pypi.org/project/fsrs/)
(py-fsrs). It's the official Python implementation, and its only dependency
is `typing-extensions`.

- FSRS is the best practical scheduler in the
  [srs-benchmark](https://github.com/open-spaced-repetition/srs-benchmark),
  and it's what Anki uses. Only neural research models (RWKV, with millions
  of parameters) predict better.
- FSRS-7 is still unreleased (an open fsrs-rs PR as of mid-2026). Revisit
  once it ships.

Defaults, which `.recall/config.toml` can override:

- 90% desired retention.
- The py-fsrs default parameters.
- Learning steps of 1 minute and 10 minutes. The relearning step is
  10 minutes.

Later, we can fit FSRS parameters to your own history with an offline
`recall optimize` command. It would use `fsrs-rs-python`, which needs no
torch and has Python 3.14 wheels. It writes the parameters to
`config.toml`.

## State: the review log

`.recall/reviews.jsonl` is the only state, with one line per review:

```json
{"card": "3f9a0c1b2d4e:fwd", "t": "2026-06-10T08:12:03Z", "rating": 3, "ms": 4200}
```

- `card`: the card ID (see below).
- `t`: when the review happened, in UTC.
- `rating`: 1 to 4 (Again, Hard, Good, Easy).
- `ms`: how long the answer took.

Card state (stability, difficulty, due date) is **never stored**. It is
recalculated at startup by replaying the log through FSRS, which takes
milliseconds even for 100k reviews. The state is then updated in memory as
you review.

Why a log:

- **Append-only merges cleanly.** With `merge=union` in `.gitattributes`,
  there are no conflicts even if two sides append.
- **Changing FSRS parameters reschedules the whole history**, because the
  log is simply replayed with the new ones.
- **The git history is your review history.**
- **Deleted cards leave history in the log.** It's harmless, and it comes
  back if the card does.

Undo removes the last line of the log. That's only possible for reviews
that haven't been committed yet.

A future relink feature (for when you reword a front) would add lines of
the form `{"relink": "<old id>", "to": "<new id>"}` to the log.

## Card identity

- The default ID is the first 12 hex characters of the SHA-256 of the
  front, after normalizing it (strip it and collapse whitespace). Cloze
  cards hash the whole text, with the `==` markers and `^[hint]`s removed.
- A reversible card's two sides get `<id>:fwd` and `<id>:rev`.
- Each cloze deletion gets `<id>:<hash of the deleted text>`, so adding or
  reordering deletions doesn't shift the others.
- `<!-- id: x -->` pins the ID. The file and deck are not part of the ID,
  so cards can move between files.
- Duplicate IDs are an error: those cards are skipped and a warning is
  shown.

## Review queue

- **Sessions:** "Review all", a folder (every deck below it), or one deck.
- **The day starts at 04:00** in the container's local time (`TZ`).
- **New cards:** 20 per day across all decks, introduced in file order. Files
  are taken in path order.
- **Order within a session:** due learning cards first, then due reviews,
  then new cards. If only learning cards remain and the next one is due
  within 20 minutes, it is shown early.
- **Siblings are buried:** once one card from a block has been reviewed
  today, its siblings wait until tomorrow.

## Git sync

The app shells out to the `git` CLI over SSH, using a deploy key with write
access.

1. **Pull:** when the deck list loads (at most once a minute), the app runs
   `git pull --rebase`, then re-parses the decks. Re-parsing is cheap.
1. **Record:** every rating is appended to the log and fsynced right away,
   so a crash loses nothing.
1. **Commit and push:** when you tap "Done", after 5 minutes without a
   review, or at shutdown. The order is commit, `pull --rebase`, push. The
   message looks like `reviews: 23 cards (Spanish, Python/GIL)`.
1. **Push failures** are logged and retried at the next sync.

## Web UI

The pages are rendered on the server with Jinja2. **htmx** swaps the card
area in place. There's no JavaScript build step: htmx and KaTeX are stored
in `static/`.

- **Deck list:** a tree of decks and folders with due and new counts, a
  "Review all" button, and a warning banner for parse problems.
- **Review:** shows the front, then "Show answer", then the rating buttons
  Again, Hard, Good, Easy. An undo button reverts the last rating.
- **Browse deck:** every card, fully rendered, with its due date. It doubles
  as a preview, since nvim has none.
- **Done:** the session summary. This is also where the commit is triggered.

Keyboard shortcuts:

- `Space` or `Enter`: show the answer, then rate Good.
- `1` to `4`: rate.
- `u`: undo.

A few lines of plain JS handle these.

Mobile: responsive CSS with big rating buttons, and a PWA manifest for
"Add to Home Screen".

Rendering:

- `markdown-it-py`, with `mdit-py-plugins` for `==mark==` and
  `dollarmath`.
- Pygments for code.
- KaTeX in the browser for math.
- Images are served from the cards repo, after checking that the resolved
  path stays inside it.

## Code layout

```text
src/recall/
  parser.py      markdown -> blocks -> cards (uses markdown-it tokens)
  ids.py         card ID hashing
  log.py         append/read/undo on reviews.jsonl
  scheduler.py   replay log through FSRS, build queues, bury siblings
  gitsync.py     pull/commit/push via git CLI
  render.py      markdown -> HTML, cloze masking
  check.py       `recall check` (shares the parser)
  cli.py         `recall serve`, `recall check`
  main.py        FastAPI app and routes
  templates/
  static/        htmx, KaTeX, CSS, manifest
tests/
```

The parser splits blocks using markdown-it `hr` tokens and their source line
ranges. That way a `---` inside a code fence isn't a separator, and setext
headings can be detected. Within a block, it works on the source lines.

The tests focus on the parser, the IDs, log replay and queue building,
because that's where the bugs would be.

## Stack

- **Python 3.14**, managed with **uv**.
- **FastAPI**, uvicorn and Jinja2.
- **`fsrs`**, `markdown-it-py`, `mdit-py-plugins` and Pygments.
- **htmx** and **KaTeX** on the front end, stored in `static/`.
- **Development tools:** ruff, ty and pytest.

## Tooling

We use **prek** as the hook runner. It reads the same config as
`pre-commit`. prek is assumed to be installed and is invoked directly in both
repositories (`prek install`, `prek run`).

The `recall` repo runs:

- On every commit: `ruff check --fix`, `ruff format`, `ty`,
  `markdownlint-cli2` (default rules) and `lychee --offline`.
- Before each push: `pytest`.
- In GitHub Actions: `uv run prek run --all-files` and `uv run pytest`.

The cards repo runs prettier (`--prose-wrap preserve`),
`markdownlint-cli2`, `lychee --offline` and `recall check`. The last one is
exposed through a `.pre-commit-hooks.yaml` in the `recall` repo, so the
cards repo references it over SSH. The markdownlint settings are in
[card-format.md](card-format.md#checking-your-cards).

## Deployment

The app runs in Docker on a home server.

- **Image:** a uv-based image with `git` and `openssh-client` installed. It
  runs as a non-root user.
- **Volumes:**
  - the cards repo clone, read-write
  - the deploy key and `known_hosts`, read-only
- **Environment:**
  - `RECALL_CARDS_DIR`: path to the cards repo clone
  - `PORT`: the port to serve on
  - `TZ`: timezone for the 04:00 day boundary
  - `GIT_AUTHOR_NAME` and `GIT_AUTHOR_EMAIL`: author of the review commits
- **`compose.yaml`** is included.

## Later

- A relink screen for cards whose front you reworded.
- Stats: reviews today, a forecast, and actual versus target retention.
- `recall optimize` to fit FSRS parameters; FSRS-7 once it's released.
- Numbered or overlapping clozes, and typed answers.
- A weekly CI job that runs lychee on external links.

## Rejected alternatives

- **Storing state as a mutable file, or in SQLite:** conflict-prone, or
  outside git. The log is simpler.
- **Obsidian compatibility:** you edit in nvim, so we only borrow the
  plugin's syntax.
- **Blank-line-terminated cards:** no multi-paragraph answers, and they
  conflict with formatters. We use `---` blocks instead.
- **mdformat:** it rewrites `---` as 70 underscores. We use prettier.
- **An ID from the whole card:** a typo fix in an answer would reset it.
- **A single-page-app framework:** the review loop is just "show answer,
  then rate", which htmx covers.

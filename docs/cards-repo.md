# Cards repository

Total Recall keeps cards and review history in a separate, private Git repository.
The example repository in [`examples/cards/`](../examples/cards/) is a starter
template; copy it into your cards repository before adding your own decks.

## Create the repository

Create a private GitHub repository for the cards. The repository is
[`jvanlier/total-recall-cards`](https://github.com/jvanlier/total-recall-cards).
If you start from scratch, give the app's server read access to the
repository with a deploy key under **Settings → Deploy keys**.

Clone it over SSH and copy the starter kit:

```sh
git clone git@github.com:jvanlier/total-recall-cards.git
cp -a /path/to/total-recall/examples/cards/. total-recall-cards/
cd total-recall-cards
```

With `lychee` installed, install the hooks once per clone:

```sh
prek install
```

The starter kit includes `.recall/config.toml` documenting the scheduler
defaults, and a `.gitignore` for a local review database. The sample decks
and image are safe to replace.

Put decks in `cards/`; markdown elsewhere in the repository is ignored when
that directory exists, even if it is empty. Deck names omit the `cards/` prefix.
Repositories without `cards/` are scanned from the root for compatibility.

Keep `RECALL_CARDS_DIR` pointing to the repository root. Configuration stays in
`.recall/config.toml`, the default database stays in `.recall/reviews.db`, and Git
sync uses the whole repository. Run `total-recall check` from that root, or pass
its path. Images are relative to their deck file and may live anywhere inside
the repository, for example `../images/recall.svg` from `cards/Foundations.md`.

## Daily loop

Edit decks in nvim, then run the hooks and commit your changes:

```sh
prek run --all-files
git add .
git commit -m "cards: update Spanish vocabulary"
git push
```

The server pulls card edits. Review history lives in the app's SQLite
database, not in this repository.

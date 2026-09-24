# Card format

Cards live as plain markdown in a dedicated, private cards repo. You edit
them in any editor (nvim); recall only reads them. This page is the syntax
reference. See [design.md](design.md) for how it all fits together.

## Decks

- Every `.md` file in the cards repo is a deck. Dot-directories (`.git`,
  `.recall`, ...) are skipped.
- The deck name is the file path relative to the repo root, without `.md`:
  `Spanish/Verbs.md` is deck `Spanish/Verbs`.
- Folders group decks. Reviewing a folder reviews every deck below it.
- Files without cards (a `README.md`, say) don't show up as decks.

## Blocks

A deck file is split into **blocks** by horizontal rules (`---`; `***` and
`___` also work). Blank lines are allowed anywhere inside a block.

**Always put a blank line before `---`.** Without it, markdown reads the
line above as a heading (`text` + `---` = setext heading), so the separator
disappears. markdownlint (MD003) and `recall check` both flag this.

Each block is one of the following. They are checked in this order and the
first match wins:

1. A line containing only `??`: a reversible card.
1. A line containing only `?`: a basic card.
1. One or more `==highlights==`: a cloze card.
1. Lines containing `:::` or `::`: single-line cards, one per line.
1. Anything else: prose. It is ignored, so headings and notes are fine.

`?`, `??`, `::`, `:::` and `==` have no special meaning inside code
(fenced or inline) or math.

## Basic

Front above the `?` line, back below it. Either side can be any markdown:
lists, code blocks, tables, math, images.

```markdown
What does the GIL protect?

?

CPython's internal state, most importantly **reference counts**.
```

## Reversible

Same as basic, but with `??`. This creates two sibling cards: front to back
and back to front.

```markdown
la casa
??
the house
```

## Cloze

Mark deletions with `==highlight==`. Each deletion becomes its own sibling
card. While one deletion is asked, the others are shown.

```markdown
The capital of ==Australia== is ==Canberra==^[city].
```

This creates two cards:

1. `The capital of [...] is Canberra.`
1. `The capital of Australia is [city].`

`==text==^[hint]` shows the hint instead of `[...]`. Numbered clozes and
overlapping clozes are not supported (yet).

## Single-line cards

For compact decks, put one card per line in a block: `::` for basic,
`:::` for reversible.

```markdown
perro:::dog
gato:::cat
Capital of France::Paris
```

## Math

`$inline$` and `$$display$$` math, rendered with KaTeX.

```markdown
Derivative of $x^2$?
?
$$
\frac{d}{dx} x^2 = 2x
$$
```

## Images

Standard markdown images. The path is relative to the `.md` file and must
stay inside the cards repo.

```markdown
Which bird is this?
?
![robin](img/robin.jpg)
```

## Card IDs

Review history is tied to a card ID. By default the ID is derived from the
**front** of the card:

- Editing the back keeps the history.
- Editing the front starts the card over.
- Moving a card to another file or deck keeps the history.

To keep the history while rewording the front, pin the ID with an HTML
comment anywhere in the block:

```markdown
la casa
??
the house
<!-- id: casa -->
```

For single-line cards, put the comment on the card's own line:

```markdown
perro:::dog <!-- id: perro -->
```

Pinned IDs use `a-z`, `0-9` and `-`. Two cards with the same ID are an
error; `recall check` reports it and both cards are skipped.

## Hiding cards

Add `<!-- hide -->` to a block (or to the line of a single-line card) to
leave it out of reviews without losing its history.

Anything inside an HTML comment is ignored, so commenting a card out also
works. HTML comments don't nest, though, so that fails for cards that contain
an `<!-- id: ... -->`. Use `<!-- hide -->` for those.

## Checking your cards

The cards repo runs these pre-commit hooks via prek (`uvx prek install`
once per clone; prek itself need not be installed):

- **prettier** (`--prose-wrap preserve`): formats markdown. It keeps `---`
  and math intact.
- **markdownlint-cli2**: lints markdown. MD013 (line length) and MD041 (first
  line heading) are off, MD003 is `atx` and MD035 is `---`.
- **lychee** (offline): checks local links and image paths.
- **recall check**: checks card syntax, such as duplicate IDs, a `?` with an
  empty side, missing images, unclosed `$`, and headings made by a missing
  blank line before `---`.

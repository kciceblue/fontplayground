# Font Playground

A small desktop app for people who find FontForge too much. It does three things:

1. Scans the fonts installed on your computer and lists them.
2. Previews any font with text you type, in any language, and shows honestly which characters the font lacks.
3. Forges several fonts into one new `.ttf`, where every character comes from exactly one font you chose.

## Install

Requires Python 3.10 or newer.

```bash
python -m venv .venv
.venv\Scripts\pip install -e .
```

On macOS/Linux use `.venv/bin/pip`.

## Run

```bash
.venv\Scripts\python -m fontplayground
```

## Fonts tab

- Every font face found in the system and user font folders appears in the list, grouped by family. Use the search box to filter.
- Click a face to preview it at three sizes (unsupported faces such as colour emoji fonts can be previewed but not ticked). Type anything into the sample box. Characters the face does not contain are shown with a red background instead of being silently borrowed from another font.
- Variable fonts get a weight slider.
- Tick the faces you want to use as materials, then press **Go to Forge**.
- **Add folder…** scans an extra folder (for fonts that are not installed). **Rescan** ignores the cache.

## Forge tab

- **Materials** lists the ticked faces in priority order. Move them up or down. For each one you can set a weight (100–900) and a scale (%) or leave "default". The **Base** material supplies line spacing.
- **Script rules** assign a script group (Latin, Cyrillic, Han, Kana, Hangul, Arabic, symbols, emoji, …) to a specific material. Anything left on "Auto" follows the priority order: the first material that has the character supplies it.
- **Defaults and output** hold the family and style name, the default weight ("As is" keeps each font's own weight) and default scale, and the output file.
- **Combine** builds the font in the background and shows a report: how many characters came from each material, warnings, and which sample characters nobody covers. The result is previewed with your sample text.
- **Save…** writes the `.ttf`.

Weight: variable fonts are instanced at the requested weight. Static fonts asked for a heavier weight get a synthetic bold (outlines are thickened); a lighter weight than the source is not possible and produces a warning. A variable font whose positioning data cannot be instanced (Segoe UI Variable is one) is used without it and the report says so.

## What the result contains

One glyph per character, no unused glyphs, hinting removed, OpenType features (ligatures, kerning, marks) kept per material (legacy `kern` tables are converted to GPOS so they survive), a fresh name table, vertical metrics from the base material, and the file marked installable. The report warns when a source font's licence restricts embedding; check it before distributing a forged font.

## Not in this version

Installing the result, producing a whole family in one run, per-language variants of shared CJK characters, glyph editing, cross-font kerning, and colour emoji.

## Development

```bash
.venv\Scripts\pip install -e .[dev]
.venv\Scripts\python -m pytest -q
```

Design spec: `docs/superpowers/specs/2026-09-11-font-playground-design.md`. Implementation plan: `docs/superpowers/plans/2026-09-11-font-playground.md`.

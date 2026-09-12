# Font Playground

A small desktop app for people who find FontForge too much. Pick a couple of installed fonts, see exactly which one will draw which characters, and forge them into one `.ttf` you can save or install. Typical use: a Latin font you like plus a Chinese, Japanese or Korean font, merged so every app shows both properly.

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

## The three steps

The window is one path: **1 Pick fonts → 2 Check → 3 Forge & save**. The materials tray at the bottom always shows what you have picked, tells you what your sample text still lacks, and offers one-click suggestions. The button at the bottom right always says what happens next.

**1 Pick fonts.** Search the fonts installed on your computer (scanned once, then cached). Each family shows badges for the scripts it covers, so a font with Han or Kana is easy to spot. Click a family to preview it with your own sample text in any language; characters the font lacks are shown in red. The line under the preview tells you what this font would add to your mix. Press **Add to materials**. The first font you add is the **Main** font: its letters win wherever fonts overlap, and it sets the line spacing.

**2 Check.** One card per font shows what it will supply. On the right, "How the result will look" draws every character of your sample in the font that will actually supply it, before any file exists. "Who supplies what" lists only the scripts your fonts cover, with the automatic choice explained; change it if you disagree. Open **Adjust** on a card to make a font bolder (variable fonts are instanced, static fonts get a synthetic bold) or scale it so it sits well next to the main font.

**3 Forge & save.** The family name, style and output path are prefilled. The forge starts as soon as you arrive, and the result is previewed in the real forged font with a plain summary and a list of sample characters nobody covers. Press **Save to …** to write the file, or **Install for me** to install it for your Windows user account (no admin rights). Any later change marks the result stale and the button reads **Rebuild**.

Menu (⋯ at the top right): Rescan fonts, Add folder… (for fonts that are not installed), Start over.

## What the result contains

One glyph per character, no unused glyphs, hinting removed, OpenType features (ligatures, kerning, marks) kept per font (legacy `kern` tables are converted to GPOS so they survive), a fresh name table, vertical metrics from the main font, and the file marked installable. The report warns when a source font's licence restricts embedding; check it before distributing a forged font. A variable font whose positioning data cannot be instanced (Segoe UI Variable is one) is used without it and the report says so.

## Not in this version

Producing a whole family in one run, per-language variants of shared CJK characters, glyph editing, cross-font kerning, colour emoji, and installing on macOS/Linux (use Open folder and install by hand).

## Development

```bash
.venv\Scripts\pip install -e .[dev]
.venv\Scripts\python -m pytest -q
```

Design specs: `docs/superpowers/specs/2026-09-11-font-playground-design.md` (engine, catalog) and `docs/superpowers/specs/2026-09-12-workflow-ui-design.md` (UI).

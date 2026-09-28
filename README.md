# Font Playground

A small desktop app for people who find FontForge too much. Pick a couple of installed fonts, see exactly which one will draw which characters, and forge them into one `.ttf` you can save or install. Typical use: a Latin font you like plus a Chinese, Japanese or Korean font, merged so every app shows both properly.

## Install

Requires Python 3.10 or newer; the dependencies (PySide6 6.8+, fontTools, skia-pathops) are installed by pip. Developed and tested on Windows 11. It runs on macOS and Linux too, but **Install for me** is Windows-only and the automatic theme following is untested there.

```bash
python -m venv .venv
.venv\Scripts\pip install -e .
```

On macOS/Linux use `.venv/bin/pip`.

## Run

```bash
.venv\Scripts\python -m fontplayground
```

## How it works

Everything happens in one window. On the left is **Your font**: the fonts it is made of, top to bottom. On the right is a preview of your own text drawn exactly the way the result will draw it; click it and type. At the bottom are the name, **Save a copy…** and **Install**.

**Main font.** Press **Choose main font…** and pick the font you like for letters and numbers; it also sets the line spacing. The picker draws every font in its own face, with its native name (微软雅黑, 等线, 맑은 고딕) and a sample line of the language you are choosing for, and only lists fonts that draw that language well. Search by English or native name; ↑ and ↓ try the next font in the preview, Enter uses it, Esc goes back.

**Other languages.** When your text has characters the main font cannot draw, the app offers the next step, e.g. **Choose a font for Chinese…**. **＋ Add a font for another language…** adds one for Japanese, Korean, Arabic, Hindi and more; a font added for a language draws that language even when a font above it could. Each card says in plain words what its font draws. Below the main font, **Size** and **Weight** make a font sit well next to the others, and the preview shows it at once; **Colour by font** paints every character in the colour of the font that draws it. Characters no font draws are listed under the preview with a button that finds a font for them.

**Install.** Press **Install**: the font is built (about 15 seconds for a Latin font plus a CJK font) and installed for your Windows user account, no admin rights needed; the preview then shows the real built font. Change anything and the button reads **Update installed font**. **Save a copy…** writes the `.ttf` wherever you like. The app will not install over a font Windows or you already have under the same name, and asks before replacing one it made earlier.

**Advanced…** shows which font draws each script (and lets you change it), which font sets the line spacing, default boldness and size, and the report of the last build.

Menu (⋯ at the top right of the preview): Rescan fonts, Add folder… (for fonts that are not installed), Start over, Advanced…, Theme (System, Light or Dark — System follows the Windows "Choose your mode" setting and is the default), and Open settings folder. The first start after an update may rescan your fonts once.

## What the result contains

One glyph per character, no unused glyphs, hinting removed, OpenType features (ligatures, kerning, marks) kept per font (legacy `kern` tables are converted to GPOS so they survive), a fresh name table, vertical metrics from the main font, and the file marked installable. The report warns when a source font's licence restricts embedding; check it before distributing a forged font. A variable font whose positioning data cannot be instanced (Segoe UI Variable is one) is used without it and the report says so.

## Not in this version

Producing a whole family in one run, per-language variants of shared CJK characters (the `locl` feature is dropped so pan-CJK fonts fit the 65,535-glyph limit), glyph editing, cross-font kerning, colour emoji, and installing on macOS/Linux (use Open folder and install by hand).

## Development

```bash
.venv\Scripts\pip install -e .[dev]
.venv\Scripts\python -m pytest -q
```

On Windows, two tests in `tests/test_install.py` briefly install a fixture font for the current user and remove it again.

## Licence

Font Playground is released under the MIT License (see `LICENSE`). `cff_to_glyf` in `fontplayground/engine/prepare.py` is adapted from fontTools' `Snippets/otf2ttf.py` (Copyright (c) 2017 Just van Rossum, MIT). The dependencies are installed from PyPI and are not part of this repository: fontTools (MIT), skia-pathops (BSD-3-Clause), unicodedata2 (Apache-2.0) and PySide6 / Qt for Python (LGPL v3); if you redistribute a bundled build, include the Qt LGPL notices.

The fonts you forge keep their own licences: the report warns when a source font restricts embedding, and it is on you to check the source licences before distributing a forged font.

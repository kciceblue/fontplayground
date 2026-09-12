"""Smart defaults: pure functions that propose every forge setting from the materials.

Nothing here touches Qt or the engine's state; the ForgeModel calls these whenever the
materials change and the user has not overridden the value in question.
"""
from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from functools import lru_cache
from pathlib import Path

from fontplayground.catalog.face import FontFace
from fontplayground.engine.scripts import GROUP_IDS, group_of

FaceKey = tuple[str, int]

VENDOR_WORDS = frozenset({"microsoft", "ms", "adobe", "google"})
MAX_FAMILY_NAME = 31            # the classic name-table limit that old Windows/Mac software still trips over
FORGED_SUFFIX = "Forged"
DEFAULT_WEIGHT_CLASS = 400
_UNSAFE_FILENAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]+')


# ----- group counts ----------------------------------------------------------------------------
class _CountsKey:
    """Cache key for one face's counts: hash/equality by (path, index, character count).

    A rescan yields a new FontFace object for the same file; keying on the face key plus the size of
    its character map lets lru_cache reuse the counts unless the font itself changed.
    """
    __slots__ = ("face", "_key")

    def __init__(self, face: FontFace) -> None:
        self.face = face
        self._key = (face.path, face.index, len(face.codepoints))

    def __hash__(self) -> int:
        return hash(self._key)

    def __eq__(self, other: object) -> bool:
        return isinstance(other, _CountsKey) and self._key == other._key


@lru_cache(maxsize=512)
def _counts(ref: _CountsKey) -> dict[str, int]:
    counts = dict.fromkeys(GROUP_IDS, 0)
    for cp in ref.face.codepoints:
        counts[group_of(cp)] += 1
    return counts


def face_group_counts(face: FontFace) -> dict[str, int]:
    """Characters per script group for one face: {group id: count}, every group present (0 when empty)."""
    return dict(_counts(_CountsKey(face)))


def group_counts(faces: Iterable[FontFace]) -> dict[FaceKey, dict[str, int]]:
    """counts[key][group] = |codepoints(face) ∩ group| for every face."""
    return {face.key: face_group_counts(face) for face in faces}


# ----- suppliers -------------------------------------------------------------------------------
def _count(counts_by_key: Mapping[FaceKey, Mapping[str, int]], key: FaceKey, group_id: str) -> int:
    return counts_by_key.get(key, {}).get(group_id, 0)


def smart_supplier(group_id: str, counts_by_key: Mapping[FaceKey, Mapping[str, int]],
                   order_keys: Sequence[FaceKey]) -> FaceKey | None:
    """The first material in priority order that covers at least half as much of the group as the best one.

    None when no material covers the group at all. A Latin-heavy main font keeps Latin even when a CJK
    font with a token Latin range sits above it, and the CJK font gets Han whichever order they are in.
    """
    best = max((_count(counts_by_key, k, group_id) for k in order_keys), default=0)
    if best == 0:
        return None
    for key in order_keys:
        if _count(counts_by_key, key, group_id) * 2 >= best:
            return key
    return None


def resolve_rules(order_keys: Sequence[FaceKey], pins: Mapping[str, FaceKey | None],
                  counts_by_key: Mapping[FaceKey, Mapping[str, int]]) -> dict[str, int | None]:
    """Explicit ForgeSpec.script_rules: a pinned key's index when the key is present, else the smart supplier."""
    index_of = {key: i for i, key in enumerate(order_keys)}
    rules: dict[str, int | None] = {}
    for group_id in GROUP_IDS:
        pinned = pins.get(group_id)
        if pinned is not None and pinned in index_of:
            rules[group_id] = index_of[pinned]
            continue
        key = smart_supplier(group_id, counts_by_key, order_keys)
        rules[group_id] = index_of[key] if key is not None else None
    return rules


# ----- names -----------------------------------------------------------------------------------
def strip_vendor(family: str) -> str:
    """Drop leading vendor words (Microsoft, MS, Adobe, Google); a name that is only vendor words is kept."""
    words = family.split()
    while len(words) > 1 and words[0].lower() in VENDOR_WORDS:
        words.pop(0)
    return " ".join(words) if words else family.strip()


def default_family_name(faces: Sequence[FontFace]) -> str:
    """'<Main> <second>' (vendor prefixes stripped, ≤ 31 chars), else '<Main> Forged'; empty -> 'Forged'."""
    if not faces:
        return FORGED_SUFFIX
    main = strip_vendor(faces[0].family)
    second = next((strip_vendor(f.family) for f in faces[1:] if strip_vendor(f.family) != main), None)
    if second is not None:
        pair = f"{main} {second}"
        if len(pair) <= MAX_FAMILY_NAME:
            return pair
    return f"{main} {FORGED_SUFFIX}"


def default_style(main_face: FontFace | None) -> str:
    return main_face.style if main_face is not None and main_face.style.strip() else "Regular"


def default_output_path(family: str, style: str) -> Path:
    """Documents/<Family>-<Style>.ttf with characters a file name cannot hold replaced by '-'."""
    stem = _UNSAFE_FILENAME.sub("-", f"{family.strip() or FORGED_SUFFIX}-{style.strip() or 'Regular'}")
    return Path.home() / "Documents" / f"{stem}.ttf"


# ----- suggestions -----------------------------------------------------------------------------
def suggest_materials(missing_cps: Iterable[int], catalog_faces: Iterable[FontFace], main_face: FontFace | None,
                      limit: int = 3, exclude_keys: Iterable[FaceKey] = ()) -> list[FontFace]:
    """Supported faces that cover some of the missing characters, best first, one per family.

    Within a family the face whose italic flag matches Main and whose weight is closest to Main's wins
    (400 when there is no Main). Families are ranked by how many missing characters the chosen face
    covers; ties keep catalog order.
    """
    missing = frozenset(missing_cps)
    if not missing or limit <= 0:
        return []
    excluded = set(exclude_keys)
    want_italic = main_face.italic if main_face is not None else False
    want_weight = main_face.weight_class if main_face is not None else DEFAULT_WEIGHT_CLASS
    best_per_family: dict[str, tuple[tuple[int, int, int], FontFace]] = {}
    families: list[str] = []
    for order, face in enumerate(catalog_faces):
        if not face.supported or face.key in excluded:
            continue
        covered = len(missing & face.codepoints)
        if covered == 0:
            continue
        rank = (0 if face.italic == want_italic else 1, abs(face.weight_class - want_weight), order)
        current = best_per_family.get(face.family)
        if current is None:
            families.append(face.family)
        if current is None or rank < current[0]:
            best_per_family[face.family] = (rank, face)
    ranked = sorted(families, key=lambda fam: -len(missing & best_per_family[fam][1].codepoints))
    return [best_per_family[fam][1] for fam in ranked[:limit]]

"""Convert a legacy 'kern' table into a GPOS pair-positioning lookup.

fontTools.merge has no merge logic for 'kern' and silently drops it, so fonts whose
kerning lives only in that table would lose it. GPOS survives the merge.
"""
from __future__ import annotations

from fontTools.otlLib.builder import buildLookup, buildPairPosGlyphsSubtable, buildValue
from fontTools.ttLib import TTFont, newTable
from fontTools.ttLib.tables import otTables as ot


def has_kern_feature(font: TTFont) -> bool:
    if "GPOS" not in font:
        return False
    feature_list = font["GPOS"].table.FeatureList
    return bool(feature_list) and any(r.FeatureTag == "kern" for r in feature_list.FeatureRecord)


def kern_pairs(font: TTFont) -> dict[tuple[str, str], int]:
    """Horizontal, non-cross-stream pairs from every format-0 subtable."""
    pairs: dict[tuple[str, str], int] = {}
    for st in getattr(font["kern"], "kernTables", []):
        if getattr(st, "format", 0) != 0:
            continue
        coverage = getattr(st, "coverage", 1)
        if not getattr(st, "apple", False) and (not coverage & 1 or coverage & 4):
            continue
        for pair, value in st.kernTable.items():
            pairs[pair] = pairs.get(pair, 0) + value
    return pairs


def _langsys() -> ot.LangSys:
    ls = ot.LangSys()
    ls.LookupOrder = None
    ls.ReqFeatureIndex = 0xFFFF
    ls.FeatureIndex = []
    ls.FeatureCount = 0
    return ls


def _empty_gpos() -> ot.GPOS:
    t = ot.GPOS()
    t.Version = 0x00010000
    t.ScriptList = ot.ScriptList()
    t.ScriptList.ScriptRecord = []
    t.ScriptList.ScriptCount = 0
    t.FeatureList = ot.FeatureList()
    t.FeatureList.FeatureRecord = []
    t.FeatureList.FeatureCount = 0
    t.LookupList = ot.LookupList()
    t.LookupList.Lookup = []
    t.LookupList.LookupCount = 0
    return t


def _script_tags(font: TTFont) -> set[str]:
    tags = {"DFLT", "latn"}
    for tag in ("GSUB", "GPOS"):
        if tag in font and font[tag].table.ScriptList:
            tags |= {sr.ScriptTag for sr in font[tag].table.ScriptList.ScriptRecord}
    return tags


def kern_to_gpos(font: TTFont) -> int:
    """Move legacy kern pairs into a GPOS 'kern' feature. Returns the number of pairs converted."""
    if "kern" not in font or has_kern_feature(font):
        return 0
    glyphs = set(font.getGlyphOrder())
    pairs = {p: v for p, v in kern_pairs(font).items() if v and p[0] in glyphs and p[1] in glyphs}
    if not pairs:
        return 0

    subtable = buildPairPosGlyphsSubtable({p: (buildValue({"XAdvance": v}), None) for p, v in pairs.items()},
                                          font.getReverseGlyphMap())
    lookup = buildLookup([subtable])
    if "GPOS" in font:
        table = font["GPOS"].table
    else:
        gpos = newTable("GPOS")
        gpos.table = table = _empty_gpos()
        font["GPOS"] = gpos
    if table.LookupList is None:
        table.LookupList = _empty_gpos().LookupList
    if table.FeatureList is None:
        table.FeatureList = _empty_gpos().FeatureList
    if table.ScriptList is None:
        table.ScriptList = _empty_gpos().ScriptList

    table.LookupList.Lookup.append(lookup)
    table.LookupList.LookupCount = len(table.LookupList.Lookup)
    feature = ot.Feature()
    feature.FeatureParams = None
    feature.LookupListIndex = [table.LookupList.LookupCount - 1]
    feature.LookupCount = 1
    record = ot.FeatureRecord()
    record.FeatureTag = "kern"
    record.Feature = feature
    records = table.FeatureList.FeatureRecord + [record]

    # FeatureList must stay sorted by tag; remap every index that points into it.
    order = sorted(range(len(records)), key=lambda i: records[i].FeatureTag)
    remap = {old: new for new, old in enumerate(order)}
    new_index = remap[len(records) - 1]
    table.FeatureList.FeatureRecord = [records[i] for i in order]
    table.FeatureList.FeatureCount = len(order)
    for fv in getattr(table, "FeatureVariations", None).FeatureVariationRecord if getattr(table, "FeatureVariations", None) else []:
        for sub in fv.FeatureTableSubstitution.SubstitutionRecord:
            sub.FeatureIndex = remap[sub.FeatureIndex]

    scripts = {sr.ScriptTag: sr for sr in table.ScriptList.ScriptRecord}
    for tag in _script_tags(font):
        if tag not in scripts:
            sr = ot.ScriptRecord()
            sr.ScriptTag = tag
            sr.Script = ot.Script()
            sr.Script.DefaultLangSys = _langsys()
            sr.Script.LangSysRecord = []
            sr.Script.LangSysCount = 0
            scripts[tag] = sr
    for sr in scripts.values():
        script = sr.Script
        if script.DefaultLangSys is None:
            script.DefaultLangSys = _langsys()
        for ls in [script.DefaultLangSys] + [r.LangSys for r in script.LangSysRecord]:
            ls.FeatureIndex = [remap[i] for i in ls.FeatureIndex]
            if ls.ReqFeatureIndex != 0xFFFF:
                ls.ReqFeatureIndex = remap[ls.ReqFeatureIndex]
            if new_index not in ls.FeatureIndex:
                ls.FeatureIndex.append(new_index)
            ls.FeatureCount = len(ls.FeatureIndex)
    table.ScriptList.ScriptRecord = [scripts[t] for t in sorted(scripts)]
    table.ScriptList.ScriptCount = len(scripts)
    del font["kern"]
    return len(pairs)

import html
import json
import re

from export import (KANATA_NAMES, LABELS, MAC_CODES, OVERLAY_CLASS, OVERLAY_KEY, OVERLAY_MODE, QWERTY, ahk_str,
                    load_layout, to_ahk, to_kanata, to_keylayout, to_klc)
from model import LAYOUTS

LAYOUT = LAYOUTS["python-hand"]


def qwerty_types(key: str, shift: bool) -> str:
    """What a QWERTY OS layout types for a kanata key name."""
    label = {v: k for k, v in KANATA_NAMES.items()}.get(key, key)
    return QWERTY[label][int(shift)]


def kanata_types(action: str, shift_held: bool) -> str:
    if m := re.fullmatch(r"S-(\S+)", action):
        return qwerty_types(m[1], True)
    if m := re.fullmatch(r"\(unshift (\S+)\)", action):
        return qwerty_types(m[1], False)
    return qwerty_types(action, shift_held)


ACTION = r"(\(unshift \S+\)|\S+)"


def test_kanata_types_the_layout():
    text = to_kanata(LAYOUT, "Test")
    for i, label in enumerate(LABELS):
        m = re.search(rf"^  k{i} \(fork \(fork {ACTION} {ACTION} \(lsft rsft\)\) (\S+) ", text, re.M)
        assert kanata_types(m[1], False) == LAYOUT[label][0]
        assert kanata_types(m[2], True) == LAYOUT[label][1]
        assert qwerty_types(m[3], False) == QWERTY[label][0]  # shortcuts stay QWERTY
        n = re.search(rf"^  n{i} \(fork {ACTION} ", text, re.M)
        assert kanata_types(n[1], False) == LAYOUT[label][1]  # Right Shift layer


def test_kanata_layers_have_one_entry_per_source_key():
    text = to_kanata(LAYOUT, "Test")
    blocks = re.findall(r"^\((defsrc|deflayer \w+)\n(.*?)\n\)", text, re.M | re.S)
    sizes = {name: len(body.split()) for name, body in blocks}
    assert len(set(sizes.values())) == 1, sizes
    assert "deflayer rnav" in sizes and "deflayer qwerty" in sizes


def test_klc_types_the_layout():
    text = to_klc(LAYOUT, "Test Layout")
    rows = {}
    for line in text.splitlines():
        cols = line.split("\t")
        if re.fullmatch(r"[0-9a-f]{2}", cols[0]) and len(cols) > 6 and cols[1] not in ("", "Esc"):
            rows[cols[1]] = [c for c in cols[2:] if c][1:3]

    def char(c):
        return c if len(c) == 1 else chr(int(c, 16))

    assert char(rows["Q"][0]) == LAYOUT["q"][0]
    assert char(rows["OEM_3"][1]) == LAYOUT["`"][1]
    assert char(rows["R"][0]) == "p"  # letters move; the virtual key stays QWERTY
    assert len(rows) == 47 + 3  # + ISO key, space, numpad decimal
    assert re.match(r"KBD\tTest[0-9a-f]{4}\t", text)
    assert to_klc(LAYOUT, "Test Other").split("\t")[1] != text.split("\t")[1]  # unique per name


def test_keylayout_types_the_layout():
    text = to_keylayout(LAYOUT, "Test")
    maps = dict(re.findall(r'<keyMap index="(\d)">(.*?)</keyMap>', text, re.S))
    assert set(maps) == {"0", "1", "2", "3"}
    out = {i: {int(c): html.unescape(o) for c, o in re.findall(r'code="(\d+)" output="([^"]*)"', body)}
           for i, body in maps.items()}
    for label in LABELS:
        code = MAC_CODES[label]
        assert out["0"][code] == LAYOUT[label][0]
        assert out["1"][code] == LAYOUT[label][1]
        assert out["3"][code] == QWERTY[label][0]
    assert out["2"][MAC_CODES["r"]] == "P"  # caps lock: capitals, symbols unshifted
    assert out["0"][36] == "\r"  # non-character keys are mapped too


def test_ahk_quotes_awkward_chars():
    text = to_ahk(LAYOUT, "Test")  # python-hand has " ` ' on keys
    for ch in "\"`'":
        assert ahk_str(ch) in text
    assert ahk_str("`") == '"``"'


def test_ahk_reports_typed_keys_to_overlay():
    text = to_ahk(LAYOUT, "Test")
    assert f'"FindWindow", "Str", "{OVERLAY_CLASS}"' in text
    assert f'NotifyOverlay({OVERLAY_KEY:#x}, Integer("0x" SubStr(sc, 3)), shifted)' in text  # after Caps Lock flip
    assert f"NotifyOverlay({OVERLAY_MODE:#x}, qwertyMode)" in text


def test_load_layout_reads_folders_and_names(tmp_path):
    folder = tmp_path / "python-test"
    folder.mkdir()
    (folder / "layout.json").write_text(json.dumps({"name": "Python Test", "layout": LAYOUT}))
    for spec in (folder, folder / "layout.json"):
        layout, name, out = load_layout(str(spec))
        assert (layout, name, out) == (LAYOUT, "Python Test", folder)
    layout, name, out = load_layout("colemak-dh")
    assert name == "Colemak-DH" and out.name == "colemak-dh"

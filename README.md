# python-layout-optimizer

Places the 32 ASCII symbols on a keyboard layout for programming, using weighted character, bigram
and trigram counts from real code. Letters stay where your base layout has them (QWERTY, Dvorak,
Colemak-DH or Programmer Dvorak) and digits stay on the 1-0 keys in order. Only the symbols move.

The default setup optimizes for Python on Programmer Dvorak letters with digits on Shift, which
is what I type on. The corpus language, base layout and cost model are set in
[`config.toml`](config.toml). Results export to AutoHotkey, kanata, a Windows `.klc` and a macOS
`.keylayout`.

## The result

Python, Programmer Dvorak letters, digits on Shift, bracket pairs kept learnable (shifted character above the unshifted one):

```
 !   1   2   3   4   5   6   7   8   9   0   &   ~
[?] [+] [/] [(] [[] []] [%] [:] [)] [{] [}] [@] [<]
   >   '   -   P   Y   F   G   C   R   L   ;   ^   $
  ["] [,] [.] [p] [y] [f] [g] [c] [r] [l] [#] [\] [|]
    A   O   E   U   I   D   H   T   N   S   *
   [a] [o] [e] [u] [i] [d] [h] [t] [n] [s] [=]
      `   Q   J   K   X   B   M   W   V   Z
     [_] [q] [j] [k] [x] [b] [m] [w] [v] [z]
```

| Layout                              | cost/key  | vs. Programmer Dvorak | shifted % | same-finger bigrams % | redirects % |
|-------------------------------------|-----------|-----------------------|-----------|-----------------------|-------------|
| Programmer Dvorak (digits in order) | 1.842     | -                     | 14.0      | 5.2                   | 5.7         |
| Hand-designed Python layout         | 1.759     | -4.5%                 | 9.5       | 5.3                   | 5.6         |
| **Optimized**                       | **1.700** | **-7.7%**             | 9.5       | 4.5                   | 5.0         |
| Optimized, brackets unconstrained   | 1.693     | -8.1%                 | 10.7      | 4.4                   | 5.0         |

Costs are in effort units per keystroke over about 38.5M weighted keystrokes from 29 popular Python
repositories (Django, pandas, scikit-learn, Home Assistant, pip, pytest, Rich, FastAPI, ...). Twelve
annealing restarts agree to within 0.002.

Symbol frequency in typed Python: `. , _ ( " = :`, then `' ) -`; everything else is under 0.5%.

## Download a layout

Every optimized layout is in [`layouts/`](layouts), one folder each. Each folder has the layout in all
four formats (see [Exports](#exports) for how to install them) plus `layout.json`, which holds the
layout, its stats and the settings it was optimized with.

| Folder                                   | Letters           | Digits | Optimized with                      |
|------------------------------------------|-------------------|--------|-------------------------------------|
| `python-programmer-dvorak`               | Programmer Dvorak | Shift  | default settings (the result above) |
| `python-programmer-dvorak-unconstrained` | Programmer Dvorak | Shift  | no bracket rule                     |
| `python-programmer-dvorak-low-redirect`  | Programmer Dvorak | Shift  | redirect penalty 0.5                |
| `python-programmer-dvorak-cheap-shift`   | Programmer Dvorak | Shift  | Shift cost 1.0                      |
| `python-programmer-dvorak-costly-shift`  | Programmer Dvorak | Shift  | Shift cost 2.5                      |
| `python-programmer-dvorak-strict-sfb`    | Programmer Dvorak | Shift  | same-finger penalty 4.0             |
| `python-qwerty`                          | QWERTY            | normal | default settings                    |
| `python-qwerty-unconstrained`            | QWERTY            | normal | no bracket rule                     |
| `python-dvorak`                          | Dvorak            | normal | default settings                    |
| `python-colemak-dh`                      | Colemak-DH        | normal | default settings                    |

## Findings

The biggest pattern: symbols that follow names want to be on the left hand. Python identifiers mostly
end in consonants that Dvorak puts on the right hand (`t n s r l d`), so the symbols that come right after a name
(`. , (`) are cheapest on the left hand, which alternates with the name's last letter. In nearly every
variant `,` and `.` stay on the left top row and `_` stays on the left pinky. The vowels on the left
hand and the consonants on the right are what make this work for Dvorak.

Keeping the brackets learnable barely costs anything. Requiring `()`, `[]` and `{}` to sit either side
by side on the same row and layer, or mirrored (same finger on the other hand), costs 0.4% (1.693 -> 1.700). The
unconstrained optimum scatters the pairs (for example `[` on 4 and `]` on 1). In the result above,
`( )` are mirrored on 3/8, and `[ ]` and `{ }` are adjacent.

To see what holds up under different weights, I reran the optimization with Shift costing 1.0 and 2.5
(default 1.5), with a heavier same-finger penalty (4.0, default 2.5), and with a redirect penalty
(0.5 per redirect, default 0):

- Stable in every run: `.` on the left top row, `_` on the left pinky, `[ ]` and `{ }` on the
  unshifted number row, and `* ! & ~ ^` on Shift. `,` stays on the left top row in every run
  except the heavy same-finger one, which moves it to 8.
- Stable except at Shift 1.0: `( )` mirrored on the number row (3/8 or 2/9). When Shift is cheap,
  `( )` and `"` move onto Shift on the left top row.
- Weight-dependent: `=`, `:`, `"` and `'` trade places on the right-pinky home key, the left-pinky
  keys and the left top row. The rare symbols (`# \ | @ $ % ;`) move around between runs.
- The redirect penalty lowers redirects only from 5.0% to 4.75% while the rest of the cost rises
  slightly, so with Dvorak letters it isn't worth changing the layout for.

I also ran it on other base layouts. Only the symbols are optimized here (digits unshifted, bracket rule on), so
each base keeps its own letters:

| Base       | standard symbols | optimized symbols | gain   |
|------------|------------------|-------------------|--------|
| QWERTY     | 2.129            | 1.892             | -11.1% |
| Dvorak     | 1.871            | 1.705             | -8.9%  |
| Colemak-DH | 1.844            | 1.629             | -11.7% |

Colemak-DH comes out lowest under this cost model and has the fewest same-finger bigrams (3.2%,
vs 4.6% for Dvorak and 7.1% for QWERTY), but about twice Dvorak's redirects (11% vs 5%). With the
digits unshifted, the number row holds only shifted symbols, so `( )` move to Shift on the right hand: on
the `; '` keys for QWERTY and on the `, .` keys for Colemak-DH. `_` and `"` always get an unshifted key. With Dvorak letters
the left-hand pattern above appears again: `" , .` on the left top row and `_` on the left pinky.

## Limits

- The cost model is my own guesswork. The per-key effort grid, the Shift cost and the bigram
  penalties are estimates, not measurements. The robust placements are the ones that
  survive the sensitivity runs above. Treat the exact placement of rare symbols as noise.
- So is the counting model. Comments count x0.6 and docstrings x0.4. Closing
  brackets and quotes count x0.3 because editors auto-close them, and identifier characters after
  the 4th count x0.3 because of autocomplete. Different editor habits shift the result.
- Indentation, whitespace, Enter, Backspace and navigation aren't modelled. Neither are
  shortcuts, which stay on QWERTY positions in all exports.
- One corpus of popular open-source Python, mostly library code. Notebooks, scripts or a
  different domain will have a different mix of symbols.
- A 47-key row-staggered ANSI board with standard touch-typing fingering (6 on the left index).
  The fingering and effort grid can be changed in `config.toml`; other physical geometries can't.

## Use it

Needs Python 3.11+ and numpy.

```sh
python -m venv venv && . venv/bin/activate      # Windows: venv\Scripts\Activate.ps1
pip install -r requirements.txt

python optimize.py                    # uses results/counts.json -> layouts/python-programmer-dvorak/layout.json
python export.py                      # -> the .ahk, .kbd, .klc and .keylayout in that same folder
pytest
```

`results/counts.json` holds the Python counts, so you don't need to download the corpus. To count
your own:

```sh
python fetch_corpus.py                                        # the 29 Python repos -> corpus/raw/
python fetch_corpus.py --lang rust --repos tokio-rs/tokio ... # any language, your own repo list
python count.py corpus/raw                                    # -> results/counts.json
python count.py corpus/rust --lang rust --out results/counts-rust.json
```

Supported languages: Python (standard tokenizer), JavaScript, TypeScript, C, C++, Java, C#, Go,
Rust and Ruby. The non-Python languages use a small lexer that knows their comment and string syntax.

### Configuration

[`config.toml`](config.toml) holds everything that is a choice: the language, the base layout and
digit placement, the counting weights, the cost parameters, the bracket rule, and the per-key
fingers and effort. Any value can be overridden for a single run:

```sh
python optimize.py --set cost.shift=2.5 --name "Python Programmer Dvorak Costly Shift"
python optimize.py --set 'layout.base="colemak-dh"' --set 'layout.digits="unshifted"' \
                   --set 'layout.baselines=["colemak-dh"]'
python optimize.py --set 'brackets.pairs=[]' --name "Python Programmer Dvorak Unconstrained"
```

### Cost model

Per keystroke: the key's effort (home row cheapest, number-row reaches dearest), plus 1.5 if shifted.
Per bigram: same finger on different keys costs 2.5 + 1.0 per key-width of travel; skipping a row
with one hand costs 0.6 per row; an inward roll on one row earns -0.3; a hand switch earns -0.1;
staying on the same Shift key refunds 0.75. Per trigram (optional): a penalty for redirects, where
one hand changes direction (index -> ring -> middle). Each bracket pair that is neither adjacent nor
mirrored adds a flat 1.0, which in practice makes the rule hard.

The search is simulated annealing over symbol swaps, plus moves that relocate a whole bracket pair
to another learnable spot, followed by a greedy polish to a local optimum. A run takes about 2 minutes
for 12 restarts.

### Exports

`python export.py [--layout layouts/<folder> | qwerty | python-hand | ...] [--format ...] [--name ...]`

Each layout gets its own folder in `layouts/`: `optimize.py` writes `layout.json` there (named after the
language and base layout, or `--name`), and `export.py` writes the four files next to it.

| Format       | Platform    | Notes                                                                                                                                   |
|--------------|-------------|-----------------------------------------------------------------------------------------------------------------------------------------|
| `.ahk`       | Windows     | AutoHotkey v2. The OS layout stays US QWERTY. Right Shift + WASD = arrows; Caps Lock toggles plain QWERTY; Shift+Caps Lock = Caps Lock. |
| `.kbd`       | W,mac,Linux | [kanata](https://github.com/jtroo/kanata) config with the same extras as the AHK script.                                                |
| `.klc`       | Windows     | Source for Microsoft Keyboard Layout Creator, which builds an installable layout.                                                       |
| `.keylayout` | macOS       | Copy to `~/Library/Keyboard Layouts/`, log out and back in, then add it under Input Sources.                                            |

All four keep Ctrl/Alt/Win (Cmd/Ctrl on macOS) shortcuts on their QWERTY positions. The native
`.klc` and `.keylayout` layouts can't do the arrow layer or the QWERTY toggle.

## License

MIT

from collections import Counter

import pytest

from count import Weights, count_source, runs

W = Weights(comment=0.5, docstring=0.25, close_discount=0.3, autocomplete_after=4, autocomplete_factor=0.1)


def text_of(source):
    return ["".join(ch for ch, _ in run) for run in runs(source, W)]


def weights_of(source):
    return [[wt for _, wt in run] for run in runs(source, W)]


def test_adjacent_tokens_form_one_run_and_whitespace_breaks():
    assert text_of("x = foo(bar)\n") == ["x", "=", "foo(bar)"]


def test_indentation_is_dropped():
    assert text_of("if a:\n    b\n") == ["if", "a:", "b"]


def test_closing_bracket_discounted():
    assert weights_of("f(x)\n") == [[1.0, 1.0, 1.0, 0.3]]


def test_autocomplete_discount_after_prefix():
    assert weights_of("abcdef\n") == [[1, 1, 1, 1, 0.1, 0.1]]


def test_closing_quote_discounted():
    assert weights_of("x='ab'\n")[0] == [1, 1, 1, 1, 1, 0.3]


def test_comment_weighted():
    (run,) = weights_of("# hi\n")[:1]
    assert run == [0.5]  # "#" alone; the space breaks the run


def test_module_docstring_weighted_and_closing_quotes_discounted():
    ws = weights_of('"""ab"""\n')
    assert ws == [[0.25] * 5 + [0.25 * 0.3] * 3]


def test_string_in_expression_is_code_not_docstring():
    assert weights_of('x = "a"\n')[-1] == [1, 1, 0.3]


def test_fstring_closing_quote_discounted():
    ws = weights_of('x = f"{y}"\n')[-1]
    assert ws[-1] == pytest.approx(0.3)
    assert ws[0] == 1.0


def test_counts_use_min_weight_for_bigrams():
    uni, bi = Counter(), Counter()
    count_source("f(x)\n", W, uni, bi)
    assert bi["x)"] == pytest.approx(0.3)
    assert bi["f("] == 1.0
    assert uni[")"] == pytest.approx(0.3)


def test_trigrams_use_min_weight():
    uni, bi, tri = Counter(), Counter(), Counter()
    count_source("f(x)\n", W, uni, bi, tri)
    assert tri["f(x"] == 1.0
    assert tri["(x)"] == pytest.approx(0.3)


def js_text(source, lang="javascript"):
    return ["".join(ch for ch, _ in run) for run in runs(source, W, lang)]


def js_weights(source, lang="javascript"):
    return [[wt for _, wt in run] for run in runs(source, W, lang)]


def test_generic_runs_split_on_whitespace():
    assert js_text("const x = f(y);\n") == ["const", "x", "=", "f(y);"]


def test_generic_closing_bracket_and_autocomplete():
    assert js_weights("abcdef(x)") == [[1, 1, 1, 1, 0.1, 0.1, 1, 1, 0.3]]


def test_generic_comments_and_doc_comments():
    assert js_weights("// hi")[0] == [0.5, 0.5]
    assert js_weights("/** hi */")[0] == [0.25] * 3
    assert js_weights("/* a */")[-1] == [0.5, 0.5]


def test_generic_strings_discount_closing_quote_only_when_closed():
    assert js_weights("x='ab'")[0] == [1, 1, 1, 1, 1, 0.3]
    assert js_weights("x='ab")[0] == [1, 1, 1, 1, 1]  # unterminated: plain chars


def test_comment_markers_inside_strings_are_string_text():
    assert js_weights('"//"')[0] == [1, 1, 1, 0.3]


def test_multiline_template_strings():
    ws = js_weights("`a\nb`")
    assert ws == [[1, 1], [1, 0.3]]


def test_rust_lifetimes_are_not_strings():
    assert js_weights("&'a str", "rust")[0] == [1, 1, 1]


def test_ruby_uses_hash_comments():
    assert js_weights("x # y", "ruby") == [[1], [0.5], [0.5]]

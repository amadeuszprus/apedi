from apedi import normalize


def test_crlf_and_cr_become_lf() -> None:
    assert normalize.normalize_text("a\r\nb\rc\n") == "a\nb\nc\n"


def test_trailing_whitespace_stripped() -> None:
    assert normalize.normalize_text("a   \nb\t\n") == "a\nb\n"


def test_blank_line_runs_collapse_to_one() -> None:
    assert normalize.normalize_text("a\n\n\n\n\nb\n") == "a\n\nb\n"


def test_single_blank_line_survives() -> None:
    assert normalize.normalize_text("a\n\nb\n") == "a\n\nb\n"


def test_whitespace_only_lines_count_as_blank() -> None:
    assert normalize.normalize_text("a\n   \n\t\n\nb\n") == "a\n\nb\n"


def test_leading_blank_lines_dropped() -> None:
    assert normalize.normalize_text("\n\n\na\n") == "a\n"


def test_file_ends_with_exactly_one_newline() -> None:
    assert normalize.normalize_text("a") == "a\n"
    assert normalize.normalize_text("a\n\n\n") == "a\n"


def test_empty_input_stays_empty() -> None:
    assert normalize.normalize_text("") == ""
    assert normalize.normalize_text("\n\n\n") == ""
    assert normalize.normalize_text("   \n\t\n") == ""


def test_leading_tabs_become_spaces() -> None:
    out = normalize.normalize_text(
        "def f():\n\tif x:\n\t\tpass\n", tab_width=4, use_spaces=True,
    )
    assert out == "def f():\n    if x:\n        pass\n"


def test_leading_spaces_become_tabs_when_tabs_preferred() -> None:
    out = normalize.normalize_text(
        "def f():\n    if x:\n        pass\n", tab_width=4, use_spaces=False,
    )
    assert out == "def f():\n\tif x:\n\t\tpass\n"


def test_ragged_indent_rounds_up_to_tab_when_tabs_preferred() -> None:
    # Six spaces at tab_width 4 is one full tab plus a two-space remainder;
    # the remainder stays as spaces so alignment is not silently widened.
    out = normalize.normalize_text("a\n      x\n", tab_width=4, use_spaces=False)
    assert out == "a\n\t  x\n"


def test_mixed_leading_tabs_and_spaces_normalized() -> None:
    out = normalize.normalize_text("a\n\t  x\n", tab_width=4, use_spaces=True)
    assert out == "a\n      x\n"


def test_inner_spacing_is_untouched() -> None:
    assert normalize.normalize_text("foo    bar\n") == "foo    bar\n"


def test_nbsp_is_untouched() -> None:
    assert normalize.normalize_text("a\u00a0b\n") == "a\u00a0b\n"


def test_is_idempotent() -> None:
    messy = "\r\n\r\n\tfoo   \r\n\r\n\r\n\r\n\t\tbar\t\r\n\r\n"
    once = normalize.normalize_text(messy)
    assert normalize.normalize_text(once) == once


def test_terminal_paste_shape() -> None:
    pasted = "$ ls -la   \r\n\r\n\r\ntotal 12\r\n\tdrwxr-xr-x  .   \r\n\r\n"
    assert normalize.normalize_text(pasted, tab_width=4) == (
        "$ ls -la\n\ntotal 12\n    drwxr-xr-x  .\n"
    )


def test_changed_reports_whether_normalizing_would_edit() -> None:
    assert normalize.changed("a   \n") is True
    assert normalize.changed("a\n") is False


# ---------- dedent (common leading indentation) ----------

def test_common_indent_is_stripped() -> None:
    pasted = "  first line\n  second line\n"
    assert normalize.normalize_text(pasted) == "first line\nsecond line\n"


def test_relative_indent_survives_dedent() -> None:
    pasted = "  outer\n      inner\n  outer again\n"
    assert normalize.normalize_text(pasted) == "outer\n    inner\nouter again\n"


def test_a_column_zero_line_means_no_dedent() -> None:
    src = "def f():\n    return 1\n"
    assert normalize.normalize_text(src) == src


def test_blank_lines_do_not_drag_common_indent_to_zero() -> None:
    pasted = "  para one\n\n  para two\n"
    assert normalize.normalize_text(pasted) == "para one\n\npara two\n"


# ---------- final newline ----------

def test_final_newline_optional_for_a_selection() -> None:
    assert normalize.normalize_text("a  ", ensure_final_newline=False) == "a"
    assert normalize.normalize_text("a\n", ensure_final_newline=False) == "a\n"


# ---------- unwrap ----------

LONG_A = "x" * 70
LONG_B = "y" * 70


def test_unwrap_joins_hard_wrapped_lines() -> None:
    out = normalize.normalize_text(f"{LONG_A}\ntail\n", unwrap=True)
    assert out == f"{LONG_A} tail\n"


def test_unwrap_is_off_by_default() -> None:
    assert normalize.normalize_text(f"{LONG_A}\ntail\n") == f"{LONG_A}\ntail\n"


def test_unwrap_keeps_short_lines_apart() -> None:
    src = "Ala\nma\nkota\n"
    assert normalize.normalize_text(src, unwrap=True) == src


def test_unwrap_stops_at_a_blank_line() -> None:
    out = normalize.normalize_text(f"{LONG_A}\n\n{LONG_B}\n", unwrap=True)
    assert out == f"{LONG_A}\n\n{LONG_B}\n"


def test_unwrap_does_not_swallow_list_items() -> None:
    out = normalize.normalize_text(f"{LONG_A}\n- a bullet\n", unwrap=True)
    assert out == f"{LONG_A}\n- a bullet\n"


def test_unwrap_does_not_swallow_headings_or_tables() -> None:
    assert normalize.normalize_text(f"{LONG_A}\n## Heading\n", unwrap=True) == (
        f"{LONG_A}\n## Heading\n"
    )
    assert normalize.normalize_text(f"{LONG_A}\n| a | b |\n", unwrap=True) == (
        f"{LONG_A}\n| a | b |\n"
    )


def test_unwrap_continues_a_wrapped_bullet() -> None:
    out = normalize.normalize_text(f"- {LONG_A}\ncontinued\n", unwrap=True)
    assert out == f"- {LONG_A} continued\n"


def test_unwrap_respects_indentation_changes() -> None:
    out = normalize.normalize_text(f"a\n{LONG_A}\n    indented\n", unwrap=True)
    assert out == f"a\n{LONG_A}\n    indented\n"


def test_unwrap_leaves_fenced_code_alone() -> None:
    src = f"```\n{LONG_A}\ntail\n```\n"
    assert normalize.normalize_text(src, unwrap=True) == src


def test_unwrap_joins_a_whole_wrapped_paragraph() -> None:
    src = f"{LONG_A}\n{LONG_B}\nend.\n"
    assert normalize.normalize_text(src, unwrap=True) == f"{LONG_A} {LONG_B} end.\n"


def test_unwrap_is_idempotent() -> None:
    once = normalize.normalize_text(f"{LONG_A}\ntail\n", unwrap=True)
    assert normalize.normalize_text(once, unwrap=True) == once


# ---------- ragged terminal paste (regression) ----------
#
# A terminal wrapping an indented block does NOT re-indent the rows it pushes
# onto the next line, so real pastes have some continuation lines in column 0.
# That single line used to set the common indent to 0 (killing the dedent) and
# to trip the "different indent = different block" guard (killing the unwrap).

RAGGED = (
    "  Skasowałem też oba skrypty ze scratchpada, żeby nie zostały jako wzorzec.\n"
    "\n"
    "  Stan repo: kod, bump do 0.7.16, CHANGELOG, metainfo i tłumaczenia PL siedzą"
    " w working tree — nadal nic nie zacommitowane, bo\n"
    "  o commit nie prosiłeś. Snap zbudowany z tego working tree (source: .), więc"
    " masz zainstalowane dokładnie to, co widzisz w\n"
    "  plikach.\n"
    "\n"
    "  Do sprawdzenia na żywo: F2 na pliku w drzewku (nie powinno zwinąć), klik w"
    " akapit w podglądzie markdown (nie powinno\n"
    "skoczyć), Ctrl+Alt+I na wklejce z terminala, i podmiana otwartego pliku z"
    " zewnątrz przy niezapisanych zmianach — powinien\n"
    "  wyskoczyć dialog, a kopia wylądować w ~/.cache/apedi/backups/.\n"
)


def test_ragged_paste_collapses_to_three_paragraphs() -> None:
    out = normalize.normalize_text(RAGGED, tab_width=4, unwrap=True)
    body = [line for line in out.split("\n") if line]
    assert len(body) == 3


def test_ragged_paste_loses_its_shared_indent() -> None:
    out = normalize.normalize_text(RAGGED, tab_width=4, unwrap=True)
    assert not any(line.startswith(" ") for line in out.split("\n") if line)


def test_ragged_paste_joins_across_a_column_zero_continuation() -> None:
    out = normalize.normalize_text(RAGGED, tab_width=4, unwrap=True)
    assert "nie powinno skoczyć), Ctrl+Alt+I" in out
    assert "powinien wyskoczyć dialog" in out


def test_ragged_paste_keeps_paragraph_breaks() -> None:
    out = normalize.normalize_text(RAGGED, tab_width=4, unwrap=True)
    assert out.count("\n\n") == 2


def test_ragged_paste_is_idempotent() -> None:
    once = normalize.normalize_text(RAGGED, tab_width=4, unwrap=True)
    assert normalize.normalize_text(once, tab_width=4, unwrap=True) == once


def test_shallower_continuation_joins_but_deeper_one_does_not() -> None:
    long_line = "  " + "x" * 70
    assert normalize.normalize_text(f"{long_line}\ntail\n", unwrap=True) == (
        "x" * 70 + " tail\n"
    )
    # Deeper indentation is a nested block, not a wrap — it must stay put.
    deeper = normalize.normalize_text(f"{long_line}\n        nested\n", unwrap=True)
    assert deeper == "x" * 70 + "\n      nested\n"


# ---------- unwrap is limited to prose languages ----------

def test_may_unwrap_allows_plain_text_and_markdown() -> None:
    assert normalize.may_unwrap(None) is True
    assert normalize.may_unwrap("markdown") is True
    assert normalize.may_unwrap("rst") is True


def test_may_unwrap_refuses_programming_languages() -> None:
    for lang in ("python3", "js", "c", "go", "yaml", "json", "html", "sh"):
        assert normalize.may_unwrap(lang) is False, lang


def test_unwrap_would_corrupt_code_which_is_why_it_is_gated() -> None:
    # Documents the hazard the language gate exists to prevent: a statement
    # past UNWRAP_MIN_LEN followed by a same-indent line does get joined, so
    # the caller must never pass unwrap=True for a programming language.
    src = (
        "def f():\n"
        "    result = some_function_with_a_long_name(argument_one, arg_two, arg3)\n"
        "    return result\n"
    )
    assert "arg3) return result" in normalize.normalize_text(src, unwrap=True)
    assert normalize.normalize_text(src, unwrap=False) == src

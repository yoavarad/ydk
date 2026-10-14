"""Tests for go_source — Go comment/string blanking and unified-diff added-line parsing."""

from __future__ import annotations

from ydk.core.go_source import added_lines, blank_comments_and_strings


class TestBlankCommentsAndStrings:
    def test_line_comment_blanked(self) -> None:
        assert blank_comments_and_strings("x := 1 // t.Skip()") == ["x := 1"]

    def test_block_comment_across_lines_keeps_line_count(self) -> None:
        lines = blank_comments_and_strings("a /*\nt.Skip()\n*/ b")
        assert len(lines) == 3
        assert "Skip" not in "".join(lines)
        assert lines[2].strip() == "b"

    def test_string_contents_blanked_but_quotes_kept(self) -> None:
        assert blank_comments_and_strings('t.Skip("needs // db")') == ['t.Skip("           ")']

    def test_empty_string_kept(self) -> None:
        assert blank_comments_and_strings('t.Skip("")') == ['t.Skip("")']

    def test_escaped_quote_inside_string(self) -> None:
        assert blank_comments_and_strings(r's := "a\"b" // c') == [r's := "    "']

    def test_raw_string_multiline(self) -> None:
        lines = blank_comments_and_strings("s := `a\nt.Skip()` + x")
        assert lines == ["s := `", "        ` + x"]

    def test_unterminated_string_does_not_blank_following_lines(self) -> None:
        assert blank_comments_and_strings('x := "oops\nt.Skip()')[1] == "t.Skip()"

    def test_rune_literal_with_quote(self) -> None:
        assert blank_comments_and_strings("c := '\"' // t.Skip()") == ["c := ' '"]


class TestAddedLines:
    def test_parses_hunks_per_file(self) -> None:
        diff = (
            "diff --git a/x_test.go b/x_test.go\n"
            "--- a/x_test.go\n"
            "+++ b/x_test.go\n"
            "@@ -3,0 +4,2 @@\n"
            "+\tt.Skip()\n"
            "+\tt.Log()\n"
            "@@ -10 +12 @@\n"
            "-old\n"
            "+new\n"
            "diff --git a/gone_test.go b/gone_test.go\n"
            "--- a/gone_test.go\n"
            "+++ /dev/null\n"
            "@@ -1 +0,0 @@\n"
            "-x\n"
        )
        assert added_lines(diff) == {"x_test.go": {4, 5, 12}}

    def test_added_line_starting_with_plus_plus_is_content(self) -> None:
        diff = "+++ b/x_test.go\n@@ -1,0 +2,2 @@\n+++ i\n+\tt.Skip()\n"
        assert added_lines(diff) == {"x_test.go": {2, 3}}

    def test_quoted_path_unquoted(self) -> None:
        diff = '+++ "b/p\\303\\251_test.go"\n@@ -0,0 +1 @@\n+x\n'
        assert added_lines(diff) == {"pé_test.go": {1}}

    def test_new_file(self) -> None:
        diff = "--- /dev/null\n+++ b/pkg/n_test.go\n@@ -0,0 +1,2 @@\n+a\n+b\n"
        assert added_lines(diff) == {"pkg/n_test.go": {1, 2}}

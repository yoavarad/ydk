"""Tests for the shared REQUIRED_LABELS single source of truth."""

from __future__ import annotations

from ydk.repositories.github._helpers import REQUIRED_LABELS


class TestRequiredLabels:
    def test_contains_expected_names(self) -> None:
        names = [name for name, _color, _description in REQUIRED_LABELS]
        assert names == [
            "epic",
            "story",
            "task",
            "in-progress",
            "in-review",
            "blocked-by-code",
            "blocked-by-decision",
        ]

    def test_no_duplicate_names(self) -> None:
        names = [name for name, _color, _description in REQUIRED_LABELS]
        assert len(names) == len(set(names))

    def test_every_label_has_color_and_description(self) -> None:
        for name, color, description in REQUIRED_LABELS:
            assert name
            assert color
            assert description

    def test_init_and_task_cmd_share_the_same_list(self) -> None:
        """init and create-batch must both build labels from this one list."""
        from ydk.cli.init_cmd import _REQUIRED_LABELS as init_labels

        assert init_labels is REQUIRED_LABELS

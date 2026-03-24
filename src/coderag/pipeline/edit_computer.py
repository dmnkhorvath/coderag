"""Compute byte-level edits from old/new source for tree-sitter's ``tree.edit()``.

Uses :mod:`difflib.SequenceMatcher` on line-split source bytes to identify
changed blocks, then translates those into the byte-offset / point tuples
that ``tree.edit()`` expects.
"""

from __future__ import annotations

import difflib
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import tree_sitter

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class SourceEdit:
    """A single edit expressed in tree-sitter's coordinate system.

    All byte offsets are relative to the **original** source before any
    edits are applied.  ``start_point``, ``old_end_point``, and
    ``new_end_point`` are ``(row, column)`` tuples.
    """

    start_byte: int
    old_end_byte: int
    new_end_byte: int
    start_point: tuple[int, int]
    old_end_point: tuple[int, int]
    new_end_point: tuple[int, int]


class EditComputer:
    """Compute and apply tree-sitter edits from source diffs."""

    @staticmethod
    def compute_edits(old_source: bytes, new_source: bytes) -> list[SourceEdit]:
        """Compute edits needed to transform *old_source* into *new_source*.

        Uses :class:`difflib.SequenceMatcher` on line-split bytes to find
        changed regions, then converts each region into a :class:`SourceEdit`
        with byte offsets and ``(row, col)`` points.

        Returns edits in **forward** (document) order.
        """
        if old_source == new_source:
            return []

        old_lines = old_source.split(b"\n")
        new_lines = new_source.split(b"\n")

        matcher = difflib.SequenceMatcher(None, old_lines, new_lines, autojunk=False)
        edits: list[SourceEdit] = []

        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            if tag == "equal":
                continue

            # Byte offset at the start of line i1 in old source
            start_byte = EditComputer._byte_offset_for_line(old_lines, i1)
            # Byte offset at the end of line i2-1 in old source
            old_end_byte = EditComputer._byte_offset_for_line(old_lines, i2)

            # Compute the replacement text byte length
            if j1 < j2:
                # The replacement lines joined with newlines
                replacement = b"\n".join(new_lines[j1:j2])
            else:
                replacement = b""

            new_end_byte = start_byte + len(replacement)

            # Compute (row, col) points
            start_point = (i1, 0)
            old_end_point = (i2, 0)

            # new_end_point: row is start_row + number of new lines - 1
            if j1 < j2:
                new_end_row = i1 + (j2 - j1 - 1)
                new_end_col = len(new_lines[j2 - 1])
                new_end_point = (new_end_row, new_end_col)
            else:
                new_end_point = (i1, 0)

            edits.append(
                SourceEdit(
                    start_byte=start_byte,
                    old_end_byte=old_end_byte,
                    new_end_byte=new_end_byte,
                    start_point=start_point,
                    old_end_point=old_end_point,
                    new_end_point=new_end_point,
                )
            )

        logger.debug("EditComputer: %d edit(s) computed", len(edits))
        return edits

    @staticmethod
    def apply_edits(tree: tree_sitter.Tree, edits: list[SourceEdit]) -> None:
        """Apply edits to a tree-sitter tree via ``tree.edit()``.

        Edits are applied in forward order.  tree-sitter internally
        adjusts subsequent byte offsets after each ``tree.edit()`` call.
        """
        for edit in edits:
            tree.edit(
                start_byte=edit.start_byte,
                old_end_byte=edit.old_end_byte,
                new_end_byte=edit.new_end_byte,
                start_point=edit.start_point,
                old_end_point=edit.old_end_point,
                new_end_point=edit.new_end_point,
            )

    @staticmethod
    def _byte_offset_for_line(lines: list[bytes], line_idx: int) -> int:
        """Return the byte offset at the start of *line_idx*.

        Each line is followed by a ``\\n`` separator (1 byte), so the
        offset of line *n* is ``sum(len(line) + 1 for line in lines[:n])``.
        """
        offset = 0
        for i in range(min(line_idx, len(lines))):
            offset += len(lines[i]) + 1  # +1 for the '\n'
        return offset

    @staticmethod
    def _point_for_position(lines: list[bytes], line_idx: int, col: int) -> tuple[int, int]:
        """Return a ``(row, col)`` point."""
        return (line_idx, col)

    @staticmethod
    def total_edit_bytes(edits: list[SourceEdit]) -> int:
        """Return the total number of bytes affected by the edits."""
        return sum(max(e.old_end_byte - e.start_byte, e.new_end_byte - e.start_byte) for e in edits)

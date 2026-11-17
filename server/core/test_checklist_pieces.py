"""Tests for server/core/checklist_pieces."""

import sys
import unittest

sys.path.insert(0, "server/core")
import checklist_pieces as cp


class TestSplitJoinRoundTrip(unittest.TestCase):
    def _round_trip(self, body: str) -> None:
        lead, blocks = cp.split_item_body(body)
        self.assertEqual(cp.join_item_body(lead, blocks), body)

    def test_no_pieces(self) -> None:
        body = "Some lead text\nMore lead."
        lead, blocks = cp.split_item_body(body)
        self.assertEqual(lead, body)
        self.assertEqual(blocks, [])
        self._round_trip(body)

    def test_with_pieces(self) -> None:
        body = "- [ ] 1a First\n- [x] 2b Second\n- [ ] 3c Third"
        lead, blocks = cp.split_item_body(body)
        self.assertEqual(lead, "")
        self.assertEqual(len(blocks), 3)
        self._round_trip(body)

    def test_trailing_text_after_last_piece(self) -> None:
        body = "- [ ] 1a First\nSome trailing text"
        lead, blocks = cp.split_item_body(body)
        self.assertEqual(lead, "")
        self.assertEqual(len(blocks), 1)
        self.assertIn("Some trailing text", blocks[0])
        self._round_trip(body)

    def test_no_final_newline(self) -> None:
        body = "lead\n- [ ] 1a First"
        lead, blocks = cp.split_item_body(body)
        # The newline separating lead from the first piece is retained in
        # lead_text so the round trip is byte-exact.
        self.assertEqual(lead, "lead\n")
        self.assertEqual(len(blocks), 1)
        self._round_trip(body)

    def test_crlf(self) -> None:
        body = "lead\r\n- [ ] 1a First\r\ntrailing"
        lead, blocks = cp.split_item_body(body)
        self.assertEqual(lead, "lead\r\n")
        self._round_trip(body)

    def test_piece_with_meta_comment(self) -> None:
        body = '- [ ] 1a Title <!-- status: open -->\n- [x] 2b Other'
        lead, blocks = cp.split_item_body(body)
        self.assertEqual(lead, "")
        self.assertEqual(len(blocks), 2)
        self.assertIn("<!-- status: open -->", blocks[0])
        self._round_trip(body)


class TestNextPieceLabel(unittest.TestCase):
    def test_multiple_blocks_picks_highest(self) -> None:
        # "2b" > "1g" > "1a" so the successor is "2c".
        blocks = ['- [ ] 1a A', '- [ ] 2b B', '- [ ] 1g G']
        self.assertEqual(cp.next_piece_label(blocks), "2c")

    def test_after_1g_gives_1h_with_single_block(self) -> None:
        blocks = ['- [ ] 1g Some title']
        self.assertEqual(cp.next_piece_label(blocks), "1h")

    def test_no_letter_increments_digit(self) -> None:
        blocks = ['- [ ] 5 Title']
        self.assertEqual(cp.next_piece_label(blocks), "6")

    def test_empty_list_raises(self) -> None:
        with self.assertRaises(ValueError):
            cp.next_piece_label([])

    def test_no_parseable_label_raises(self) -> None:
        blocks = ["just plain text"]
        with self.assertRaises(ValueError):
            cp.next_piece_label(blocks)

    def test_z_raises(self) -> None:
        blocks = ['- [ ] 1z Title']
        with self.assertRaises(ValueError):
            cp.next_piece_label(blocks)


if __name__ == "__main__":
    unittest.main()

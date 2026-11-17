"""Valid (slug, item_id, piece_id) combinations from tests/test_filing.py fixture.

Extracted from the setUp methods and CHECKLIST/PIECES_CHECKLIST constants.
Use these IDs when writing throwaway scripts that exercise server/core/filing.py.

The slug is derived from `store.create_feature("Thing", ...)` which slugifies to "thing".
The root is a tempfile.TemporaryDirectory() / "features" subdirectory.
"""

# Slug used in the fixture
SLUG = "thing"

# Item IDs from CHECKLIST
CHECKLIST_ITEMS = ["FF-1", "FF-2", "FF-3", "FF-4"]

# Item IDs and piece IDs from PIECES_CHECKLIST
PIECES_CHECKLIST_ITEMS = ["FF-1", "FF-2", "FF-3"]
PIECES_CHECKLIST_PIECES = ["2a", "2b", "2c"]

# All valid (slug, item_id, piece_id) triples
# piece_id=None means the item itself (not a piece)
VALID_COMBINATIONS = [
    # CHECKLIST items
    ("thing", "FF-1", None),
    ("thing", "FF-2", None),
    ("thing", "FF-3", None),
    ("thing", "FF-4", None),
    # PIECES_CHECKLIST items (FF-1, FF-2, FF-3)
    ("thing", "FF-1", None),
    ("thing", "FF-2", None),
    ("thing", "FF-2", "2a"),
    ("thing", "FF-2", "2b"),
    ("thing", "FF-2", "2c"),
    ("thing", "FF-3", None),
]

# Note: "9z" is NOT a valid piece_id. It is used in tests/test_filing.py line 364
# to test error handling for invalid piece references:
#   filing.record_text(self.slug, "FF-2", self.root, "9z")
# This call is expected to raise an exception (piece not found).

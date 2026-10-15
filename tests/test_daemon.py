"""Where the daemon looks for the bundled KWin script.

A checkout keeps the script next to the package, a package install keeps it in
the XDG data directories; the order decides which one wins.
"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from appvol import daemon


class FindKwinScriptTest(unittest.TestCase):
    def test_the_first_existing_candidate_wins(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            missing = base / "kwin" / "appvol.js"
            found = base / "share" / "appvol" / "appvol.js"
            found.parent.mkdir(parents=True)
            found.write_text("// script\n", encoding="utf-8")
            self.assertEqual(daemon.find_kwin_script([missing, found]), found)

    def test_a_missing_script_reports_the_first_candidate(self) -> None:
        first = Path("/nonexistent/kwin/appvol.js")
        second = Path("/nonexistent/share/appvol/appvol.js")
        self.assertEqual(daemon.find_kwin_script([first, second]), first)

    def test_the_checkout_is_looked_at_before_the_data_dirs(self) -> None:
        with mock.patch.dict(os.environ, {"XDG_DATA_DIRS": "/usr/local/share:/usr/share"}):
            candidates = daemon.kwin_script_candidates()
        checkout = Path(daemon.__file__).resolve().parent.parent / "kwin" / "appvol.js"
        self.assertEqual(
            candidates,
            [checkout, Path("/usr/local/share/appvol/appvol.js"), Path("/usr/share/appvol/appvol.js")],
        )

    def test_the_default_data_dirs_are_used_when_the_variable_is_unset(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=True):
            candidates = daemon.kwin_script_candidates()
        self.assertEqual(
            candidates[1:], [Path("/usr/local/share/appvol/appvol.js"), Path("/usr/share/appvol/appvol.js")]
        )

    def test_an_empty_entry_in_the_variable_is_skipped(self) -> None:
        with mock.patch.dict(os.environ, {"XDG_DATA_DIRS": ":/usr/share:"}):
            candidates = daemon.kwin_script_candidates()
        self.assertEqual(candidates[1:], [Path("/usr/share/appvol/appvol.js")])


if __name__ == "__main__":
    unittest.main()

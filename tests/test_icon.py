"""Unit tests for the application icon lookup.

Everything runs against a fake icon theme and fake application directories, so
the tests do not depend on the icon theme of the machine.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from appvol import icon

DESKTOP_KONSOLE = """\
[Desktop Entry]
Type=Application
Name=Konsole
Icon=utilities-terminal
"""

DESKTOP_SPOTIFY = """\
# a comment with Icon=nonsense
[Desktop Entry]
Name=Spotify
Icon=spotify
"""

DESKTOP_NO_ICON = """\
[Desktop Entry]
Name=Broken
"""

DESKTOP_OTHER_GROUP = """\
[Desktop Action new-window]
Icon=ignored-icon

[Desktop Entry]
Icon=real-icon
"""

DESKTOP_LAUNCHER = """\
[Desktop Entry]
Icon=spotify-launcher
"""

THEME_MAIN_INDEX = """\
[Icon Theme]
Name=testtheme
Comment=Test theme
Directories=apps/16,apps/48
Inherits=hicolor

[apps/16]
Size=16
Context=Applications

[apps/48]
Size=48
Context=Applications
Type=Scalable
"""

THEME_HICOLOR_INDEX = """\
[Icon Theme]
Name=hicolor
Directories=apps/16

[apps/16]
Size=16
Context=Applications
"""

# Icons the fake themes provide (relative paths inside a theme).
MAIN_THEME_ICONS = ("apps/48/spotify.svg", "apps/48/utilities-terminal.svg", "apps/16/small.png")
HICOLOR_ICONS = ("apps/16/spotify-launcher.png",)


class IconTestCase(unittest.TestCase):
    """Shared fixture: an icon theme tree and an application directory."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.applications = self.tmp / "applications"
        self.applications.mkdir()
        self.icons = self.tmp / "icons"
        self.pixmaps = self.tmp / "pixmaps"
        self.pixmaps.mkdir()

        for name, content in (
            ("testtheme/index.theme", THEME_MAIN_INDEX),
            ("hicolor/index.theme", THEME_HICOLOR_INDEX),
        ):
            path = self.icons / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        for name in MAIN_THEME_ICONS:
            self._touch(self.icons / "testtheme" / name)
        for name in HICOLOR_ICONS:
            self._touch(self.icons / "hicolor" / name)
        self._touch(self.pixmaps / "pixicon.png")

    def tearDown(self) -> None:
        self._tmp.cleanup()
        icon.icon_theme.cache_clear()
        icon.icon_roots.cache_clear()
        icon.pixmap_dirs.cache_clear()
        icon.application_dirs.cache_clear()
        icon._theme_icon_names.cache_clear()
        icon._theme_subdirectories.cache_clear()
        icon.theme_chain.cache_clear()

    @staticmethod
    def _touch(path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("icon", encoding="utf-8")
        return path

    def resolve(self, **kwargs) -> str | None:
        """resolve() against the fake theme, with nothing inherited from the host."""
        kwargs.setdefault("dirs", [self.applications])
        kwargs.setdefault("theme", "testtheme")
        kwargs.setdefault("roots", [self.icons])
        kwargs.setdefault("pixmaps", [self.pixmaps])
        return icon.resolve(**kwargs)


class DesktopFileTests(IconTestCase):
    def test_reads_icon_of_desktop_entry(self) -> None:
        self.assertEqual(icon.parse_icon(DESKTOP_KONSOLE), "utilities-terminal")

    def test_ignores_comments_and_other_groups(self) -> None:
        self.assertEqual(icon.parse_icon(DESKTOP_SPOTIFY), "spotify")
        self.assertEqual(icon.parse_icon(DESKTOP_OTHER_GROUP), "real-icon")

    def test_missing_icon(self) -> None:
        self.assertIsNone(icon.parse_icon(DESKTOP_NO_ICON))
        self.assertIsNone(icon.parse_icon(""))

    def test_desktop_file_lookup(self) -> None:
        self._touch(self.applications / "org.kde.konsole.desktop").write_text(DESKTOP_KONSOLE, encoding="utf-8")
        self.assertEqual(icon.desktop_file_icon("org.kde.konsole", [self.applications]), "utilities-terminal")

    def test_desktop_file_lookup_accepts_desktop_suffix(self) -> None:
        self._touch(self.applications / "org.kde.konsole.desktop").write_text(DESKTOP_KONSOLE, encoding="utf-8")
        self.assertEqual(icon.desktop_file_icon("org.kde.konsole.desktop", [self.applications]), "utilities-terminal")

    def test_desktop_file_lookup_missing(self) -> None:
        self.assertIsNone(icon.desktop_file_icon("nope", [self.applications]))
        self.assertIsNone(icon.desktop_file_icon("", [self.applications]))


class ThemeLookupTests(IconTestCase):
    def test_icon_of_own_theme(self) -> None:
        self.assertTrue(icon.has_icon("spotify", "testtheme", [self.icons], ()))

    def test_icon_of_inherited_theme(self) -> None:
        self.assertTrue(icon.has_icon("spotify-launcher", "testtheme", [self.icons], ()))

    def test_icon_in_pixmap_directory(self) -> None:
        self.assertTrue(icon.has_icon("pixicon", "testtheme", [self.icons], [self.pixmaps]))

    def test_lookup_is_case_sensitive_and_exact(self) -> None:
        self.assertFalse(icon.has_icon("Spotify", "testtheme", [self.icons], ()))
        self.assertFalse(icon.has_icon("spotify.svg", "testtheme", [self.icons], ()))
        self.assertFalse(icon.has_icon("", "testtheme", [self.icons], ()))

    def test_missing_theme_falls_back_to_hicolor(self) -> None:
        self.assertTrue(icon.has_icon("spotify-launcher", "no-such-theme", [self.icons], ()))
        self.assertFalse(icon.has_icon("spotify", "no-such-theme", [self.icons], ()))

    def test_theme_chain_includes_inherits_and_hicolor(self) -> None:
        chain = icon.theme_chain("testtheme", (self.icons,))
        self.assertEqual(chain, ("testtheme", "hicolor"))

    def test_absolute_path_to_an_existing_file(self) -> None:
        path = self.tmp / "custom.png"
        self._touch(path)
        self.assertTrue(icon.has_icon(str(path), "testtheme", [self.icons], ()))
        self.assertFalse(icon.has_icon(str(self.tmp / "missing.png"), "testtheme", [self.icons], ()))

    def test_resolvable_strips_a_trailing_segment(self) -> None:
        # QIcon renders "spotify-launcher" as "spotify" when only the latter exists.
        self.assertTrue(icon.resolvable("spotify-launcher", "testtheme", [self.icons], ()))
        self.assertTrue(icon.resolvable("spotify", "testtheme", [self.icons], ()))

    def test_resolvable_rejects_unknown_names(self) -> None:
        self.assertFalse(icon.resolvable("xyzzy-launcher", "testtheme", [self.icons], ()))


class StreamIconTests(IconTestCase):
    def stream_icon(self, props) -> str | None:
        return icon.stream_icon(props, "testtheme", [self.icons], [self.pixmaps])

    def test_icon_name_property_wins(self) -> None:
        props = {"application.icon_name": "pixicon", "application.process.binary": "spotify"}
        self.assertEqual(self.stream_icon(props), "pixicon")

    def test_property_order_follows_the_mixer(self) -> None:
        # PulseAudioQt checks media.icon_name before application.icon_name.
        props = {"application.icon_name": "pixicon", "media.icon_name": "spotify"}
        self.assertEqual(self.stream_icon(props), "spotify")

    def test_media_icon_name_is_used(self) -> None:
        self.assertEqual(self.stream_icon({"media.icon_name": "spotify"}), "spotify")

    def test_binary_wins_over_application_name(self) -> None:
        props = {"application.process.binary": "spotify", "application.name": "spotify-launcher"}
        self.assertEqual(self.stream_icon(props), "spotify")

    def test_application_name_is_a_fallback(self) -> None:
        self.assertEqual(self.stream_icon({"application.name": "spotify"}), "spotify")

    def test_portal_app_id_is_a_fallback(self) -> None:
        self.assertEqual(self.stream_icon({"pipewire.access.portal.app_id": "spotify"}), "spotify")

    def test_unresolvable_values_are_skipped(self) -> None:
        props = {"application.name": "Minecraft", "pipewire.access.portal.app_id": "spotify"}
        self.assertEqual(self.stream_icon(props), "spotify")

    def test_nothing_known(self) -> None:
        self.assertIsNone(self.stream_icon({}))
        self.assertIsNone(self.stream_icon({"application.name": "Minecraft", "node.name": "Minecraft"}))


class ResolveTests(IconTestCase):
    def test_stream_icon_wins_over_the_desktop_file(self) -> None:
        # The mixer (and this project) prefer what the stream advertises, even when
        # the window's desktop file names another icon.
        self._touch(self.applications / "spotify-launcher.desktop").write_text(DESKTOP_LAUNCHER, encoding="utf-8")
        result = self.resolve(
            desktop_file_name="spotify-launcher",
            resource_class="Spotify",
            props={"application.process.binary": "spotify"},
        )
        self.assertEqual(result, "spotify")

    def test_desktop_file_is_the_fallback(self) -> None:
        self._touch(self.applications / "org.kde.konsole.desktop").write_text(DESKTOP_KONSOLE, encoding="utf-8")
        result = self.resolve(
            desktop_file_name="org.kde.konsole",
            resource_class="konsole",
            props={"application.name": "Konsole"},
        )
        self.assertEqual(result, "utilities-terminal")

    def test_resource_class_is_used_when_the_desktop_file_is_unknown(self) -> None:
        self._touch(self.applications / "konsole.desktop").write_text(DESKTOP_KONSOLE, encoding="utf-8")
        result = self.resolve(desktop_file_name="unknown-app", resource_class="konsole")
        self.assertEqual(result, "utilities-terminal")

    def test_desktop_file_icon_must_be_renderable(self) -> None:
        # Icon= points at a name the theme does not know; the bare stem "spotify"
        # is used instead.
        self._touch(self.applications / "spotify.desktop").write_text(
            "[Desktop Entry]\nIcon=gone-forever\n", encoding="utf-8"
        )
        self.assertEqual(self.resolve(desktop_file_name="spotify"), "spotify")

    def test_bare_identifier_is_a_last_resort(self) -> None:
        self.assertEqual(self.resolve(desktop_file_name="spotify"), "spotify")

    def test_reverse_dns_identifier_is_not_used_as_icon(self) -> None:
        self.assertIsNone(self.resolve(desktop_file_name="org.example.Nothing"))

    def test_nothing_known(self) -> None:
        self.assertIsNone(self.resolve())


class ThemeListingTests(IconTestCase):
    """The names an icon chooser offers, across the whole theme chain."""

    def test_lists_every_name_of_the_chain(self) -> None:
        names = icon.theme_icon_names("testtheme", [self.icons], [self.pixmaps])
        self.assertIn("spotify", names)  # the main theme
        self.assertIn("utilities-terminal", names)
        self.assertIn("small", names)
        self.assertIn("spotify-launcher", names)  # inherited hicolor
        self.assertIn("pixicon", names)  # unthemed pixmaps

    def test_the_names_are_sorted_and_unique(self) -> None:
        names = icon.theme_icon_names("testtheme", [self.icons], [self.pixmaps])
        self.assertEqual(list(names), sorted(set(names)))


class MergedThemeRootsTests(IconTestCase):
    """A theme is the merge of its installs across the XDG roots."""

    def _user_root(self) -> Path:
        # A user root extends an installed theme without an index.theme of its
        # own, which is how Steam adds hicolor/<size>/apps/steam_icon_<appid>.png.
        user = self.tmp / "user-icons"
        self._touch(user / "hicolor/256x256/apps/steam_icon_730.png")
        return user

    def test_an_icon_added_by_a_second_root_is_found(self) -> None:
        roots = [self.icons, self._user_root()]
        self.assertTrue(icon.has_icon("steam_icon_730", "testtheme", roots, ()))
        self.assertTrue(icon.resolvable("steam_icon_730", "testtheme", roots, ()))

    def test_the_listing_covers_every_root(self) -> None:
        names = icon.theme_icon_names("testtheme", [self.icons, self._user_root()], [self.pixmaps])
        self.assertIn("steam_icon_730", names)


class ConfigurationTests(IconTestCase):
    def test_xdg_directories_are_honoured(self) -> None:
        with mock.patch.dict(
            "os.environ",
            {"XDG_DATA_HOME": "/tmp/xdg-home", "XDG_DATA_DIRS": "/tmp/xdg-a:/tmp/xdg-b"},
            clear=False,
        ):
            icon.application_dirs.cache_clear()
            icon.icon_roots.cache_clear()
            icon.pixmap_dirs.cache_clear()
            self.assertEqual(str(icon.application_dirs()[0]), "/tmp/xdg-home/applications")
            self.assertIn("/tmp/xdg-a/applications", [str(path) for path in icon.application_dirs()])
            self.assertEqual(str(icon.icon_roots()[0]), "/tmp/xdg-home/icons")
            self.assertIn("/tmp/xdg-b/icons", [str(path) for path in icon.icon_roots()])
            self.assertEqual(str(icon.pixmap_dirs()[0]), "/tmp/xdg-home/pixmaps")

    def test_icon_theme_is_read_from_kdeglobals(self) -> None:
        config = self.tmp / "config"
        config.mkdir()
        (config / "kdeglobals").write_text("[Icons]\nTheme=My-Theme\n", encoding="utf-8")
        with mock.patch.dict("os.environ", {"XDG_CONFIG_HOME": str(config)}, clear=False):
            icon.icon_theme.cache_clear()
            self.assertEqual(icon.icon_theme(), "My-Theme")

    def test_icon_theme_defaults_when_unconfigured(self) -> None:
        with mock.patch.dict("os.environ", {"XDG_CONFIG_HOME": str(self.tmp / "nowhere")}, clear=False):
            icon.icon_theme.cache_clear()
            self.assertEqual(icon.icon_theme(), icon.DEFAULT_THEME)


if __name__ == "__main__":
    unittest.main()

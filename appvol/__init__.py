"""appvol — control the volume of the audio streams of a target.

Package layout:

* :mod:`appvol.focus`    — the focus target reported by the compositor.
* :mod:`appvol.match`    — pure ``focus -> sink inputs`` matching.
* :mod:`appvol.profiles` — named targets, ``profiles.toml`` and their matcher.
* :mod:`appvol.volume`   — pure volume math.
* :mod:`appvol.osd`      — KDE OSD glue.
* :mod:`appvol.config`   — TOML configuration.
* :mod:`appvol.daemon`   — ``appvold``, the D-Bus daemon.
* :mod:`appvol.cli`      — the ``appvol`` command line client.
"""

__version__ = "0.4.3"

__all__ = ["__version__"]

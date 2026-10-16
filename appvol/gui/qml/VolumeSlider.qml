// The volume slider of one profile or application.
//
// The daemon is the source of truth: the slider follows the live percent unless
// the user is dragging it, and one call is sent when the finger lifts.  It is
// used twice per row (beside the name and, in a narrow window, under it), so the
// wiring lives here instead of in every copy.

import QtQuick
import QtQuick.Controls as Controls

Controls.Slider {
    id: slider

    property var profile: null

    readonly property bool hasVolume: profile
        && profile.percent !== null && profile.percent !== undefined
    readonly property int maximum: Math.max(1, Math.round(
        (profile && profile.max_volume) || (bridge.config.max_volume) || 150))

    from: 0
    to: maximum
    enabled: hasVolume
    value: hasVolume ? profile.percent : 0

    onPressedChanged: if (!pressed && hasVolume) {
        bridge.setVolume(profile.id, Math.round(value))
    }

    Connections {
        target: bridge
        function onProfilesChanged() {
            if (!slider.pressed) {
                slider.value = slider.hasVolume ? slider.profile.percent : 0
            }
        }
    }
}

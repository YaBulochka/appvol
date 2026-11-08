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
    // The keyboard and the wheel move in whole percent; dragging stays smooth.
    stepSize: 1
    snapMode: Controls.Slider.NoSnap

    // A keyboard or wheel move has no drag to release: send the settled value
    // after a short pause instead.  A mouse drag still sends once, on release.
    Timer {
        id: writeDelay
        interval: 150
        repeat: false
        onTriggered: {
            if (slider.hasVolume && !slider.pressed) {
                bridge.setVolume(slider.profile.id, Math.round(slider.value))
            }
        }
    }

    onMoved: if (!pressed && hasVolume) writeDelay.restart()

    onPressedChanged: {
        writeDelay.stop()
        if (!pressed && hasVolume) {
            bridge.setVolume(profile.id, Math.round(value))
        }
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

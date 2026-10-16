// The speaker of one row: mute everything the target covers, or unmute it.
//
// Mute is aggregate, like the hotkey; the state follows the daemon, which
// reports "everything is muted" as the muted flag.

import QtQuick
import QtQuick.Controls as Controls

Controls.ToolButton {
    id: button

    property var profile: null

    readonly property bool hasVolume: profile
        && profile.percent !== null && profile.percent !== undefined
    readonly property bool isMuted: hasVolume && profile.muted === true

    enabled: hasVolume
    checkable: true
    checked: isMuted
    icon.name: checked ? "audio-volume-muted" : "audio-volume-medium"

    Controls.ToolTip.visible: hovered
    Controls.ToolTip.text: checked ? "Unmute" : "Mute"

    onClicked: bridge.setMute(profile.id, checked)

    Connections {
        target: bridge
        function onProfilesChanged() {
            button.checked = button.isMuted
        }
    }
}

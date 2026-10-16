// One profile in the list: what it covers, its live volume and its key.

import QtQuick
import QtQuick.Controls as Controls
import QtQuick.Layouts
import org.kde.kirigami as Kirigami

Kirigami.AbstractCard {
    id: card

    property var profile: null

    signal editRequested(var profile)
    signal removeRequested(var profile)

    readonly property bool hasVolume: profile && profile.percent !== null && profile.percent !== undefined
    // In the auto mode the list holds the applications that are playing, not the
    // profiles of profiles.toml: they cannot be edited, keyed or stepped.
    readonly property bool autoMode: bridge.mode === "auto"
    readonly property int maximum: Math.max(1, Math.round(
        (profile && profile.max_volume) || (bridge.config.max_volume) || 150))
    readonly property real globalStep: bridge.config.step || 5
    // A profile without a step of its own follows the global one, so the row
    // shows the number the keys really move by and the first change writes it
    // into the profile.
    readonly property real stepValue: (profile && profile.step) || globalStep

    // The daemon is the source of truth for the volume; the slider follows it
    // unless the user is dragging, in which case it keeps the value under the
    // finger and sends one call when the finger lifts.
    readonly property string scope: {
        if (!profile) {
            return ""
        }
        if (profile.builtin || profile.mode === "focus") {
            return "Every stream of the focused window"
        }
        if (autoMode) {
            return "Every stream of this application"
        }
        const include = profile.include || []
        const exclude = profile.exclude || []
        if (include.length && exclude.length) {
            return include.join(", ") + ", but not " + exclude.join(", ")
        }
        if (include.length) {
            return "Only " + include.join(", ")
        }
        if (exclude.length) {
            return "Everything except " + exclude.join(", ")
        }
        return "Every application, except the shell"
    }

    contentItem: ColumnLayout {
        spacing: Kirigami.Units.smallSpacing

        RowLayout {
            spacing: Kirigami.Units.smallSpacing

            Controls.RadioButton {
                id: currentBox
                checked: card.profile ? !!card.profile.current : false
                Controls.ToolTip.visible: hovered
                Controls.ToolTip.text: "The volume keys act on this profile"
                onClicked: bridge.selectProfile(card.profile.id, false)
            }

            Kirigami.Icon {
                source: card.profile && card.profile.icon
                    ? card.profile.icon
                    : (card.profile && card.profile.mode === "focus" ? "window" : "audio-volume-high")
                implicitWidth: Kirigami.Units.iconSizes.smallMedium
                implicitHeight: implicitWidth
            }

            Controls.Label {
                Layout.fillWidth: true
                text: card.profile ? (card.profile.name || card.profile.id) : ""
                font.bold: card.profile ? !!card.profile.current : false
                elide: Text.ElideRight
            }

            Controls.Label {
                visible: card.hasVolume || (card.profile && card.profile.matched !== null && card.profile.matched !== undefined)
                opacity: 0.7
                font: Kirigami.Theme.smallFont
                text: {
                    if (!card.profile) {
                        return ""
                    }
                    const matched = card.profile.matched
                    if (matched === null || matched === undefined) {
                        return "no connection"
                    }
                    if (matched === 0) {
                        return "nothing playing"
                    }
                    return matched + (matched === 1 ? " stream" : " streams")
                }
            }
        }

        Controls.Label {
            Layout.fillWidth: true
            Layout.leftMargin: currentBox.width + Kirigami.Units.smallSpacing
            text: card.scope
            opacity: 0.7
            elide: Text.ElideRight
            font: Kirigami.Theme.smallFont
        }

        RowLayout {
            spacing: Kirigami.Units.smallSpacing

            Controls.Slider {
                id: volumeSlider
                Layout.fillWidth: true
                Layout.leftMargin: currentBox.width + Kirigami.Units.smallSpacing
                from: 0
                to: card.maximum
                enabled: card.hasVolume
                value: card.hasVolume ? card.profile.percent : 0
                onPressedChanged: if (!pressed && card.hasVolume) {
                    bridge.setVolume(card.profile.id, Math.round(value))
                }
            }

            Controls.Label {
                Layout.minimumWidth: Kirigami.Units.gridUnit * 2
                horizontalAlignment: Text.AlignRight
                opacity: card.hasVolume ? 1 : 0.4
                text: Math.round(volumeSlider.value) + "%"
            }

            Controls.ToolButton {
                id: muteButton
                icon.name: muteButton.checked ? "audio-volume-muted" : "audio-volume-medium"
                checkable: true
                enabled: card.hasVolume
                checked: card.hasVolume && card.profile.muted === true
                Controls.ToolTip.visible: hovered
                Controls.ToolTip.text: checked ? "Unmute" : "Mute"
                onClicked: bridge.setMute(card.profile.id, checked)
            }

            Controls.ToolButton {
                icon.name: "document-edit"
                visible: !card.autoMode
                enabled: card.profile && !card.profile.builtin
                Controls.ToolTip.visible: hovered
                Controls.ToolTip.text: "Edit this profile"
                onClicked: card.editRequested(card.profile)
            }

            Controls.ToolButton {
                icon.name: "edit-delete"
                visible: !card.autoMode
                enabled: card.profile && !card.profile.builtin
                Controls.ToolTip.visible: hovered
                Controls.ToolTip.text: "Remove this profile"
                onClicked: card.removeRequested(card.profile)
            }
        }

        RowLayout {
            spacing: Kirigami.Units.smallSpacing

            // The key and the step belong to a profile of profiles.toml; in the
            // auto mode only the built-in row keeps its step, which is the global
            // one the applications follow.
            visible: !card.autoMode || (card.profile ? card.profile.builtin : false)

            Controls.Label {
                Layout.leftMargin: currentBox.width + Kirigami.Units.smallSpacing
                opacity: 0.7
                font: Kirigami.Theme.smallFont
                text: {
                    if (!card.profile) {
                        return ""
                    }
                    if (card.profile.builtin) {
                        return "Reached with the volume keys"
                    }
                    const key = card.profile.key
                    return key ? "Key: " + key : "No key bound"
                }
            }

            Controls.Button {
                visible: card.profile && !card.profile.builtin
                flat: true
                text: "Bind Keys…"
                onClicked: bridge.openShortcuts()
            }

            Item { Layout.fillWidth: true }

            Controls.Label {
                opacity: 0.7
                font: Kirigami.Theme.smallFont
                text: "Step:"
            }

            Controls.SpinBox {
                id: stepBox
                editable: true
                from: 1
                to: 50
                value: card.stepValue
                textFromValue: (value) => Math.round(value) + " %"
                Controls.ToolTip.visible: hovered
                Controls.ToolTip.text: "The volume keys move by this much"
                onValueModified: bridge.setStep(card.profile.id, value)
            }
        }

        Connections {
            target: bridge
            function onProfilesChanged() {
                if (!volumeSlider.pressed) {
                    volumeSlider.value = card.hasVolume ? card.profile.percent : 0
                }
                muteButton.checked = card.hasVolume && card.profile.muted === true
                // The spin box takes its value from the daemon after every write,
                // like the slider; assigning it drops the binding, so it is set
                // here, on the one signal that follows a read.
                stepBox.value = card.stepValue
            }
        }
    }
}

// One line of the list: a profile of profiles.toml, or an application that is
// playing in the running-apps view.
//
// radio · icon · name and caption · slider · percent · mute · ⋮
//
// The row that the volume keys act on carries an accent bar on the left and a
// light tint.  In a narrow window the slider drops onto a second line under the
// name; the rest of the line stays put.

import QtQuick
import QtQuick.Controls as Controls
import QtQuick.Layouts
import org.kde.kirigami as Kirigami

Rectangle {
    id: card

    property var profile: null

    /// The window accent, passed down by the window.
    property color accentColor: Kirigami.Theme.highlightColor

    signal editRequested(var profile)
    signal removeRequested(var profile)
    signal stepRequested(var profile)

    readonly property bool current: profile ? !!profile.current : false
    // In the running-apps view the list holds the applications that are playing,
    // which cannot be edited, keyed or stepped; the row menu goes away with them.
    readonly property bool autoMode: bridge.mode === "auto"
    readonly property bool narrow: width > 0 && width < 480
    readonly property bool hasVolume: profile
        && profile.percent !== null && profile.percent !== undefined
    readonly property string keyText: profile && profile.key ? profile.key : ""
    readonly property string streams: {
        if (!profile || profile.matched === null || profile.matched === undefined) {
            return "no connection"
        }
        if (profile.matched === 0) {
            return "nothing playing"
        }
        return profile.matched + (profile.matched === 1 ? " stream" : " streams")
    }
    readonly property real indent: currentBox.implicitWidth + Kirigami.Units.smallSpacing
        + Kirigami.Units.iconSizes.smallMedium + Kirigami.Units.smallSpacing

    radius: Kirigami.Units.cornerRadius
    color: current
        ? Qt.rgba(card.accentColor.r, card.accentColor.g,
                  card.accentColor.b, 0.13)
        : hoverArea.hovered
            ? Qt.rgba(Kirigami.Theme.textColor.r, Kirigami.Theme.textColor.g,
                      Kirigami.Theme.textColor.b, 0.06)
            : "transparent"
    implicitHeight: layout.implicitHeight + Kirigami.Units.largeSpacing * 2

    HoverHandler {
        id: hoverArea
    }

    // The accent bar that marks the profile the volume keys act on.
    Rectangle {
        visible: card.current
        width: 3
        radius: 1.5
        color: card.accentColor
        anchors.left: parent.left
        anchors.top: parent.top
        anchors.bottom: parent.bottom
        anchors.topMargin: Kirigami.Units.smallSpacing
        anchors.bottomMargin: Kirigami.Units.smallSpacing
    }

    ColumnLayout {
        id: layout
        anchors.fill: parent
        anchors.leftMargin: Kirigami.Units.largeSpacing
        anchors.rightMargin: Kirigami.Units.largeSpacing
        anchors.topMargin: Kirigami.Units.largeSpacing
        anchors.bottomMargin: Kirigami.Units.largeSpacing
        spacing: Kirigami.Units.smallSpacing

        RowLayout {
            Layout.fillWidth: true
            spacing: Kirigami.Units.smallSpacing

            Controls.RadioButton {
                id: currentBox
                checked: card.current
                Controls.ToolTip.visible: hovered
                Controls.ToolTip.text: "Make this the target of the volume keys"
                onClicked: bridge.selectProfile(card.profile.id, false)
            }

            Kirigami.Icon {
                source: {
                    if (!card.profile) {
                        return "audio-volume-high"
                    }
                    if (card.profile.icon) {
                        return card.profile.icon
                    }
                    return card.profile.mode === "focus" ? "window" : "audio-volume-high"
                }
                implicitWidth: Kirigami.Units.iconSizes.smallMedium
                implicitHeight: implicitWidth
            }

            ColumnLayout {
                Layout.fillWidth: true
                Layout.minimumWidth: Kirigami.Units.gridUnit * 6
                spacing: 0

                Controls.Label {
                    Layout.fillWidth: true
                    text: card.profile ? (card.profile.name || card.profile.id) : ""
                    elide: Text.ElideRight
                }

                Controls.Label {
                    Layout.fillWidth: true
                    textFormat: Text.RichText
                    font: Kirigami.Theme.smallFont
                    opacity: 0.7
                    text: {
                        if (card.autoMode) {
                            return card.streams
                        }
                        if (card.keyText) {
                            return card.streams + " · " + card.keyText
                        }
                        return card.streams + " · no key · <a href=\"bind\">Bind…</a>"
                    }
                    onLinkActivated: bridge.openShortcuts()
                }
            }

            VolumeSlider {
                Layout.preferredWidth: Kirigami.Units.gridUnit * 11
                Layout.minimumWidth: Kirigami.Units.gridUnit * 6
                visible: !card.narrow
                profile: card.profile
            }

            Controls.Label {
                Layout.minimumWidth: Kirigami.Units.gridUnit * 2
                horizontalAlignment: Text.AlignRight
                opacity: card.hasVolume ? 1 : 0.4
                text: card.hasVolume ? Math.round(card.profile.percent) + "%" : "—"
            }

            MuteButton {
                profile: card.profile
            }

            Controls.ToolButton {
                id: menuButton
                visible: !card.autoMode
                icon.name: "overflow-menu"
                Controls.ToolTip.visible: hovered
                Controls.ToolTip.text: "More actions"
                onClicked: {
                    rowMenu.target = card.profile
                    rowMenu.popup()
                }
            }
        }

        // The narrow window puts the slider under the name instead of beside it.
        VolumeSlider {
            visible: card.narrow
            Layout.fillWidth: true
            Layout.leftMargin: card.indent
            profile: card.profile
        }
    }

    // The hairline between two lines of the list.
    Rectangle {
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        height: 1
        color: Qt.rgba(Kirigami.Theme.textColor.r, Kirigami.Theme.textColor.g,
                       Kirigami.Theme.textColor.b, 0.1)
    }

    Controls.Menu {
        id: rowMenu
        objectName: "rowMenu"

        property var target: null

        Controls.MenuItem {
            text: "Bind Keys…"
            icon.name: "input-keyboard"
            onTriggered: bridge.openShortcuts()
        }

        Controls.MenuItem {
            text: "Step…"
            icon.name: "format-number"
            onTriggered: card.stepRequested(rowMenu.target)
        }

        Controls.MenuItem {
            text: "Edit…"
            icon.name: "document-edit"
            onTriggered: card.editRequested(rowMenu.target)
        }

        Controls.MenuSeparator {}

        Controls.MenuItem {
            text: "Remove"
            icon.name: "edit-delete"
            onTriggered: card.removeRequested(rowMenu.target)
        }
    }
}

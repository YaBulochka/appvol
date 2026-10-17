// The built-in Active window, pinned above the list and always visible.
//
// It is not a row of the list: the window keeps it at the top in both views, and
// it is the only place the global step of the volume keys is set.

import QtQuick
import QtQuick.Controls as Controls
import QtQuick.Layouts
import org.kde.kirigami as Kirigami

Rectangle {
    id: card

    property var profile: null

    /// The window accent, passed down by the window.
    property color accentColor: Kirigami.Theme.highlightColor

    readonly property bool current: profile ? !!profile.current : false
    readonly property bool hasVolume: profile
        && profile.percent !== null && profile.percent !== undefined
    readonly property string caption: {
        if (!profile || profile.matched === null || profile.matched === undefined) {
            return "no connection"
        }
        if (profile.matched === 0) {
            return "nothing playing"
        }
        return profile.matched + (profile.matched === 1 ? " stream" : " streams")
    }

    radius: Kirigami.Units.cornerRadius
    color: Kirigami.Theme.alternateBackgroundColor
    border.width: 1
    border.color: current
        ? card.accentColor
        : Qt.rgba(Kirigami.Theme.textColor.r, Kirigami.Theme.textColor.g,
                  Kirigami.Theme.textColor.b, 0.12)
    implicitHeight: content.implicitHeight + Kirigami.Units.largeSpacing * 2

    ColumnLayout {
        id: content
        anchors.fill: parent
        anchors.margins: Kirigami.Units.largeSpacing
        spacing: Kirigami.Units.smallSpacing

        RowLayout {
            Layout.fillWidth: true
            spacing: Kirigami.Units.smallSpacing

            Controls.RadioButton {
                id: currentBox
                checked: card.current
                Controls.ToolTip.visible: hovered
                Controls.ToolTip.text: "The volume keys act on this profile"
                onClicked: bridge.selectProfile(card.profile.id, false)
            }

            Kirigami.Icon {
                source: card.profile && card.profile.icon ? card.profile.icon : "window"
                implicitWidth: Kirigami.Units.iconSizes.smallMedium
                implicitHeight: implicitWidth
            }

            Controls.Label {
                Layout.fillWidth: true
                text: card.profile ? (card.profile.name || card.profile.id) : ""
                font.bold: true
                elide: Text.ElideRight
            }

            Controls.Label {
                opacity: 0.7
                font: Kirigami.Theme.smallFont
                text: card.caption
            }
        }

        RowLayout {
            Layout.fillWidth: true
            spacing: Kirigami.Units.smallSpacing

            VolumeSlider {
                Layout.fillWidth: true
                Layout.leftMargin: currentBox.width + Kirigami.Units.smallSpacing
                profile: card.profile
            }

            Controls.Label {
                Layout.minimumWidth: Kirigami.Units.gridUnit * 2
                horizontalAlignment: Text.AlignRight
                opacity: card.hasVolume ? 1 : 0.4
                text: card.hasVolume ? Math.round(card.profile.percent) + "%" : "0%"
            }

            MuteButton {
                profile: card.profile
            }
        }

        RowLayout {
            Layout.fillWidth: true
            spacing: Kirigami.Units.smallSpacing

            Controls.Label {
                Layout.leftMargin: currentBox.width + Kirigami.Units.smallSpacing
                opacity: 0.7
                font: Kirigami.Theme.smallFont
                text: "Follows the focused window"
                elide: Text.ElideRight
            }

            Item { Layout.fillWidth: true }

            Controls.Label {
                opacity: 0.7
                font: Kirigami.Theme.smallFont
                text: "Step"
            }

            PercentSpinBox {
                id: stepBox
                minimum: 1
                realValue: bridge.config.step || 5
                Controls.ToolTip.visible: hovered
                Controls.ToolTip.text: "The volume keys move by this much, for every profile"
                onEdited: (value) => bridge.setStep(card.profile.id, value)
            }
        }
    }

    Connections {
        target: bridge
        function onConfigChanged() {
            stepBox.realValue = bridge.config.step || 5
        }
    }
}

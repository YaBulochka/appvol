// The primary action of the header: the accented "New profile".
//
// A Breeze push button falls back to its own color set, so the fill, the frame
// and the content are drawn here.  The fill, not the caption, carries the
// accent: a one-pixel outline in the window accent is too faint to stand out,
// and accent-colored text on the window background is hard to read.

import QtQuick
import QtQuick.Controls as Controls
import QtQuick.Layouts
import org.kde.kirigami as Kirigami

Controls.Button {
    id: control

    /// The accent of the window; a Breeze Button would answer with its own.
    property color accentColor: Kirigami.Theme.highlightColor

    /// The text that stays readable on top of the accent.
    property color accentTextColor: Kirigami.Theme.highlightedTextColor

    /// A narrow header drops the caption and keeps the icon.
    property bool showText: true

    hoverEnabled: true
    opacity: enabled ? 1 : 0.5

    implicitHeight: Math.max(Kirigami.Units.gridUnit * 2.2,
                             contentItem.implicitHeight + Kirigami.Units.smallSpacing * 4)

    // The Breeze padding hugs the caption; the filled button wants the room the
    // mockup gives it, so the border stands off the icon and the text.
    leftPadding: Kirigami.Units.largeSpacing
    rightPadding: Kirigami.Units.largeSpacing

    background: Rectangle {
        radius: Kirigami.Units.cornerRadius
        color: control.accentColor

        // A hint of light on hover and a shade on press; the caption keeps the
        // contrast the fill gives it either way.
        Rectangle {
            anchors.fill: parent
            radius: parent.radius
            color: "white"
            opacity: control.hovered && !control.pressed ? 0.12 : 0
        }
        Rectangle {
            anchors.fill: parent
            radius: parent.radius
            color: "black"
            opacity: control.pressed ? 0.18 : 0
        }
    }

    contentItem: RowLayout {
        spacing: Kirigami.Units.smallSpacing

        Kirigami.Icon {
            source: control.icon.name
            color: control.accentTextColor
            implicitWidth: Kirigami.Units.iconSizes.small
            implicitHeight: implicitWidth
            visible: control.icon.name !== ""
        }

        Controls.Label {
            visible: control.showText
            text: control.text
            color: control.accentTextColor
        }
    }
}

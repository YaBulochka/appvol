// The segmented control at the top of the window: Profiles or Running apps.
//
// It replaces the old "Cycle the running applications" switch: the two views
// are named, and the one that is current fills its half of the pill.

import QtQuick
import QtQuick.Controls as Controls
import QtQuick.Layouts
import org.kde.kirigami as Kirigami

Controls.Control {
    id: control

    /// The key of the option that is current, e.g. "profiles" or "auto".
    property string current: ""
    /// [{ key, text }, ...], in the order they are shown.
    property var options: []

    /// The window accent and its readable text; a Control may answer with the
    /// color set of its parent, so the window passes them down.
    property color accentColor: Kirigami.Theme.highlightColor
    property color accentTextColor: Kirigami.Theme.highlightedTextColor

    signal activated(string key)

    implicitHeight: Math.max(Kirigami.Units.gridUnit * 1.9,
                             content.implicitHeight + topPadding + bottomPadding)
    implicitWidth: content.implicitWidth + leftPadding + rightPadding

    padding: 2

    background: Rectangle {
        radius: height / 2
        color: Qt.rgba(Kirigami.Theme.textColor.r, Kirigami.Theme.textColor.g,
                       Kirigami.Theme.textColor.b, 0.06)
        border.width: 1
        border.color: Qt.rgba(Kirigami.Theme.textColor.r, Kirigami.Theme.textColor.g,
                              Kirigami.Theme.textColor.b, 0.18)
    }

    contentItem: RowLayout {
        id: content
        spacing: 0

        Repeater {
            model: control.options

            delegate: Controls.Button {
                id: segment
                required property var modelData

                Layout.fillWidth: true
                Layout.fillHeight: true
                readonly property bool active: control.current === modelData.key

                text: modelData.text
                onClicked: control.activated(modelData.key)

                background: Rectangle {
                    radius: Math.max(0, control.height / 2 - control.padding - 1)
                    color: segment.active
                        ? control.accentColor
                        : segment.hovered
                            ? Qt.rgba(Kirigami.Theme.textColor.r,
                                      Kirigami.Theme.textColor.g,
                                      Kirigami.Theme.textColor.b, 0.08)
                            : "transparent"
                    Behavior on color { ColorAnimation { duration: Kirigami.Units.shortDuration } }
                }

                contentItem: Controls.Label {
                    text: segment.text
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                    color: segment.active ? control.accentTextColor : Kirigami.Theme.textColor
                    font.bold: segment.active
                }
            }
        }
    }
}

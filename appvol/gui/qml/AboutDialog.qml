// About appvol, from the ⋮ menu: what it is, its version and its license.

import QtQuick
import QtQuick.Controls as Controls
import QtQuick.Layouts
import org.kde.kirigami as Kirigami

Kirigami.OverlaySheet {
    id: sheet

    header: Kirigami.Heading {
        text: "About appvol"
    }

    ColumnLayout {
        Layout.preferredWidth: Kirigami.Units.gridUnit * 24
        spacing: Kirigami.Units.largeSpacing

        RowLayout {
            Layout.fillWidth: true
            spacing: Kirigami.Units.largeSpacing

            Kirigami.Icon {
                source: "appvol"
                fallback: "audio-speakers"
                implicitWidth: Kirigami.Units.iconSizes.huge
                implicitHeight: implicitWidth
            }

            ColumnLayout {
                Layout.fillWidth: true
                spacing: 0

                Controls.Label {
                    text: "appvol " + bridge.version
                    font.bold: true
                }

                Controls.Label {
                    Layout.fillWidth: true
                    wrapMode: Text.WordWrap
                    opacity: 0.7
                    text: "Volume control for the audio streams of the focused window"
                }
            }
        }

        Controls.Label {
            Layout.fillWidth: true
            wrapMode: Text.WordWrap
            textFormat: Text.StyledText
            onLinkActivated: (link) => Qt.openUrlExternally(link)
            text: "<a href=\"https://github.com/YaBulochka/appvol\">github.com/YaBulochka/appvol</a> · MIT"
        }

        Controls.Label {
            Layout.fillWidth: true
            wrapMode: Text.WordWrap
            opacity: 0.7
            font: Kirigami.Theme.smallFont
            text: "A user daemon on the session bus, a KWin script that reports the focused window, and a thin client for the hotkeys."
        }
    }
}

// Choosing the icon of a profile: the icons of the theme, filtered by a search box.
//
// The names come from the daemon-free side of the bridge (`bridge.searchIcons`),
// which lists what the icon theme can render.  Picking one writes its name into
// the profile; "Automatic" clears it, and the daemon resolves the icon itself.

import QtQuick
import QtQuick.Controls as Controls
import QtQuick.Layouts
import org.kde.kirigami as Kirigami

Kirigami.OverlaySheet {
    id: sheet

    // The icon the profile carries, so the current one can be highlighted.
    property string selected: ""

    signal chosen(string icon)

    readonly property var names: bridge.searchIcons(searchField.text, 240)

    function openFor() {
        searchField.text = ""
        open()
    }

    header: Kirigami.Heading {
        text: "Icon"
    }

    ColumnLayout {
        Layout.preferredWidth: Kirigami.Units.gridUnit * 26
        spacing: Kirigami.Units.smallSpacing

        Controls.TextField {
            id: searchField
            Layout.fillWidth: true
            placeholderText: "Search the icon theme"
        }

        Controls.Label {
            Layout.fillWidth: true
            visible: sheet.names.length === 0
            wrapMode: Text.WordWrap
            opacity: 0.7
            text: "No icon matches. Leave the field empty to use the automatic icon."
        }

        GridView {
            id: grid
            Layout.fillWidth: true
            Layout.minimumHeight: Kirigami.Units.gridUnit * 4
            Layout.preferredHeight: Kirigami.Units.gridUnit * 16
            clip: true
            cellWidth: Kirigami.Units.gridUnit * 3
            cellHeight: Kirigami.Units.gridUnit * 3
            model: sheet.names
            currentIndex: -1

            delegate: Controls.ItemDelegate {
                required property string modelData

                width: grid.cellWidth
                height: grid.cellHeight
                display: Controls.AbstractButton.IconOnly
                icon.name: modelData
                highlighted: modelData === sheet.selected

                Controls.ToolTip.visible: hovered
                Controls.ToolTip.text: modelData

                onClicked: {
                    sheet.chosen(modelData)
                    sheet.close()
                }
            }
        }

        RowLayout {
            Layout.fillWidth: true

            Controls.Button {
                text: "Automatic"
                icon.name: "audio-volume-high"
                Controls.ToolTip.visible: hovered
                Controls.ToolTip.text: "Let appvol pick the icon of the profile"
                onClicked: {
                    sheet.chosen("")
                    sheet.close()
                }
            }

            Item { Layout.fillWidth: true }

            Controls.Button {
                text: "Cancel"
                onClicked: sheet.close()
            }
        }
    }
}

// Picking an application for a profile: what is playing now, or a typed name.
//
// A profile covers applications, and PipeWire names them several ways; the list
// comes from the daemon, which groups the live streams and hands out the
// identifier that goes into the file.

import QtQuick
import QtQuick.Controls as Controls
import QtQuick.Layouts
import org.kde.kirigami as Kirigami

Kirigami.OverlaySheet {
    id: sheet

    property var existing: []

    signal chosen(string identifier)

    function openFor(known) {
        existing = known || []
        manualField.text = ""
        open()
    }

    function has(identifier) {
        return existing.indexOf(identifier) !== -1
    }

    header: Kirigami.Heading {
        text: "Applications"
    }

    ColumnLayout {
        Layout.preferredWidth: Kirigami.Units.gridUnit * 26
        spacing: Kirigami.Units.smallSpacing

        Controls.Label {
            Layout.fillWidth: true
            wrapMode: Text.WordWrap
            opacity: 0.8
            text: "Applications playing right now. Picking one writes the identifier below its name into the profile."
        }

        ListView {
            id: appList
            Layout.fillWidth: true
            Layout.minimumHeight: Kirigami.Units.gridUnit * 4
            Layout.preferredHeight: Math.min(contentHeight, Kirigami.Units.gridUnit * 16)
            clip: true
            spacing: Kirigami.Units.smallSpacing
            model: bridge.applications

            delegate: Controls.ItemDelegate {
                id: appItem
                required property var modelData

                width: appList.width
                enabled: !sheet.has(modelData.id)
                onClicked: {
                    sheet.chosen(modelData.id)
                    sheet.close()
                }

                contentItem: RowLayout {
                    spacing: Kirigami.Units.smallSpacing

                    Kirigami.Icon {
                        source: modelData.icon || "audio-volume-high"
                        implicitWidth: Kirigami.Units.iconSizes.smallMedium
                        implicitHeight: implicitWidth
                    }

                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 0

                        Controls.Label {
                            Layout.fillWidth: true
                            text: modelData.label
                            elide: Text.ElideRight
                        }

                        Controls.Label {
                            Layout.fillWidth: true
                            text: modelData.id + (modelData.panel ? " · shell" : "") + " · "
                                + modelData.streams.length
                                + (modelData.streams.length === 1 ? " stream" : " streams")
                            opacity: 0.6
                            elide: Text.ElideRight
                            font: Kirigami.Theme.smallFont
                        }
                    }

                    Controls.Label {
                        text: modelData.percent + "%"
                        opacity: modelData.muted ? 0.4 : 0.7
                    }

                    Controls.Label {
                        visible: sheet.has(modelData.id)
                        text: "already added"
                        opacity: 0.6
                        font: Kirigami.Theme.smallFont
                    }
                }
            }
        }

        Controls.Label {
            Layout.fillWidth: true
            visible: bridge.applications.length === 0
            wrapMode: Text.WordWrap
            opacity: 0.7
            text: "Nothing is playing right now; type an identifier below."
        }

        RowLayout {
            Layout.fillWidth: true

            Controls.TextField {
                id: manualField
                Layout.fillWidth: true
                placeholderText: "identifier, for example steam"
                onAccepted: if (text.trim().length > 0) {
                    sheet.chosen(text.trim())
                    sheet.close()
                }
            }

            Controls.Button {
                text: "Add"
                enabled: manualField.text.trim().length > 0
                onClicked: {
                    sheet.chosen(manualField.text.trim())
                    sheet.close()
                }
            }
        }
    }
}

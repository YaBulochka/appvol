// The editor of one profile: its name, the applications it covers and its knobs.

import QtQuick
import QtQuick.Controls as Controls
import QtQuick.Layouts
import org.kde.kirigami as Kirigami

Kirigami.OverlaySheet {
    id: sheet

    // The profile being edited; null creates a new one.
    property var profile: null

    property string draftId: ""
    property string draftName: ""
    property var includeList: []
    property var excludeList: []
    property real draftStep: 0
    property real draftMax: 0
    property string draftIcon: ""
    property string draftOsd: "auto"

    // Which list the application picker appends to.
    property string target: "include"

    readonly property bool creating: profile === null
    readonly property var osdNames: ["auto", "always", "never"]

    function openFor(existing) {
        profile = existing
        if (existing) {
            draftId = existing.id
            draftName = existing.name || existing.id
            includeList = (existing.include || []).slice()
            excludeList = (existing.exclude || []).slice()
            draftStep = existing.step || 0
            draftMax = existing.max_volume || bridge.config.max_volume || 100
            draftIcon = existing.icon || ""
            draftOsd = existing.osd_name || "never"
        } else {
            draftId = ""
            draftName = ""
            includeList = []
            excludeList = []
            draftStep = bridge.config.step || 5
            draftMax = bridge.config.max_volume || 100
            draftIcon = ""
            draftOsd = "never"
        }
        osdBox.currentIndex = Math.max(0, osdNames.indexOf(draftOsd))
        open()
    }

    function addApplication(identifier) {
        const value = String(identifier).trim().toLowerCase()
        if (value.length === 0) {
            return
        }
        const merge = (list) => list.concat([value]).filter((id, index, all) => all.indexOf(id) === index)
        if (target === "exclude") {
            excludeList = merge(excludeList)
        } else {
            includeList = merge(includeList)
        }
    }

    function save() {
        bridge.saveProfile(
            draftId.trim().toLowerCase(),
            draftName.trim(),
            includeList,
            excludeList,
            draftStep,
            draftMax,
            draftIcon.trim(),
            draftOsd)
        close()
    }

    header: Kirigami.Heading {
        text: sheet.creating
            ? "New Profile"
            : "Edit “" + (sheet.profile.name || sheet.profile.id) + "”"
    }

    footer: RowLayout {
        Layout.fillWidth: true

        Controls.Button {
            text: "Cancel"
            onClicked: sheet.close()
        }

        Controls.Button {
            text: sheet.creating ? "Create" : "Save"
            icon.name: "dialog-ok-apply"
            enabled: sheet.draftId.trim().length > 0
            onClicked: sheet.save()
        }
    }

    ColumnLayout {
        Layout.preferredWidth: Kirigami.Units.gridUnit * 26
        spacing: Kirigami.Units.smallSpacing

        Kirigami.FormLayout {
            Layout.fillWidth: true

            Controls.TextField {
                Kirigami.FormData.label: "Identifier:"
                enabled: sheet.creating
                text: sheet.draftId
                placeholderText: "spotify"
                onTextEdited: sheet.draftId = text
            }

            Controls.TextField {
                Kirigami.FormData.label: "Name:"
                text: sheet.draftName
                placeholderText: "Spotify"
                onTextEdited: sheet.draftName = text
            }

            ColumnLayout {
                Kirigami.FormData.label: "Include:"
                Layout.fillWidth: true
                spacing: Kirigami.Units.smallSpacing

                Flow {
                    Layout.fillWidth: true
                    spacing: Kirigami.Units.smallSpacing

                    Repeater {
                        model: sheet.includeList
                        delegate: Controls.Button {
                            flat: true
                            text: modelData
                            icon.name: "window-close"
                            Controls.ToolTip.visible: hovered
                            Controls.ToolTip.text: "Remove from the profile"
                            onClicked: sheet.includeList = sheet.includeList.filter(id => id !== modelData)
                        }
                    }

                    Controls.Button {
                        flat: true
                        text: "Add…"
                        icon.name: "list-add"
                        onClicked: {
                            sheet.target = "include"
                            picker.openFor(sheet.includeList)
                        }
                    }
                }

                Controls.Label {
                    visible: sheet.includeList.length === 0
                    Layout.fillWidth: true
                    wrapMode: Text.WordWrap
                    opacity: 0.7
                    font: Kirigami.Theme.smallFont
                    text: "Empty: every application stream except the shell. Add names to narrow the profile down."
                }
            }

            ColumnLayout {
                Kirigami.FormData.label: "Exclude:"
                Layout.fillWidth: true
                spacing: Kirigami.Units.smallSpacing

                Flow {
                    Layout.fillWidth: true
                    spacing: Kirigami.Units.smallSpacing

                    Repeater {
                        model: sheet.excludeList
                        delegate: Controls.Button {
                            flat: true
                            text: modelData
                            icon.name: "window-close"
                            Controls.ToolTip.visible: hovered
                            Controls.ToolTip.text: "Remove from the exceptions"
                            onClicked: sheet.excludeList = sheet.excludeList.filter(id => id !== modelData)
                        }
                    }

                    Controls.Button {
                        flat: true
                        text: "Add…"
                        icon.name: "list-add"
                        onClicked: {
                            sheet.target = "exclude"
                            picker.openFor(sheet.excludeList)
                        }
                    }
                }

                Controls.Label {
                    visible: sheet.excludeList.length === 0
                    Layout.fillWidth: true
                    wrapMode: Text.WordWrap
                    opacity: 0.7
                    font: Kirigami.Theme.smallFont
                    text: "Empty: nothing is left out. A name here turns the profile into “everything except this”."
                }
            }

            Controls.SpinBox {
                id: stepBox
                Kirigami.FormData.label: "Step:"
                from: 0
                to: 50
                editable: true
                value: sheet.draftStep
                textFromValue: (value) => value + " %"
                onValueModified: sheet.draftStep = value
            }

            Controls.SpinBox {
                id: maxBox
                Kirigami.FormData.label: "Maximum volume:"
                from: 1
                to: 150
                editable: true
                value: sheet.draftMax
                textFromValue: (value) => value + " %"
                onValueModified: sheet.draftMax = value
            }

            RowLayout {
                Kirigami.FormData.label: "Icon:"
                Layout.fillWidth: true

                Controls.TextField {
                    id: iconField
                    Layout.fillWidth: true
                    Layout.minimumWidth: Kirigami.Units.gridUnit * 10
                    text: sheet.draftIcon
                    placeholderText: "the icon of the application"
                    onTextEdited: sheet.draftIcon = text
                }

                Kirigami.Icon {
                    source: sheet.draftIcon || "audio-volume-high"
                    implicitWidth: Kirigami.Units.iconSizes.smallMedium
                    implicitHeight: implicitWidth
                }
            }

            Controls.ComboBox {
                id: osdBox
                Kirigami.FormData.label: "OSD name:"
                model: sheet.osdNames
                onActivated: sheet.draftOsd = currentText
            }
        }

        Controls.Label {
            Layout.fillWidth: true
            wrapMode: Text.WordWrap
            opacity: 0.7
            font: Kirigami.Theme.smallFont
            text: "Step 0 follows the global step of config.toml. “auto” writes the profile name into "
                + "the OSD only while the profile is not the Active one."
        }
    }

    ApplicationPicker {
        id: picker
        onChosen: (identifier) => sheet.addApplication(identifier)
    }
}

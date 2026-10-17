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

    // The icon "Automatic" stands for: the first application the profile covers,
    // resolved the way the daemon draws it on the OSD.
    readonly property string automaticIcon:
        bridge.profileIcon(includeList, excludeList) || "audio-volume-high"

    // Which list the application picker appends to.
    property string target: "include"

    readonly property bool creating: profile === null

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
        } else {
            draftId = ""
            draftName = ""
            includeList = []
            excludeList = []
            draftStep = bridge.config.step || 5
            draftMax = bridge.config.max_volume || 100
            draftIcon = ""
        }
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
            draftIcon.trim())
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
                spacing: Kirigami.Units.smallSpacing

                Controls.Button {
                    Layout.fillWidth: true
                    text: sheet.draftIcon.length > 0 ? sheet.draftIcon : "Automatic"
                    icon.name: sheet.draftIcon.length > 0 ? sheet.draftIcon : sheet.automaticIcon
                    onClicked: {
                        iconPicker.selected = sheet.draftIcon
                        iconPicker.openFor()
                    }
                }

                Controls.Button {
                    visible: sheet.draftIcon.length > 0
                    icon.name: "edit-clear"
                    Controls.ToolTip.visible: hovered
                    Controls.ToolTip.text: "Back to the automatic icon"
                    onClicked: sheet.draftIcon = ""
                }
            }

            Controls.Label {
                Layout.fillWidth: true
                wrapMode: Text.WordWrap
                opacity: 0.7
                font: Kirigami.Theme.smallFont
                text: "Step 0 follows the global step of config.toml."
            }
        }

    ApplicationPicker {
        id: picker
        onChosen: (identifier) => sheet.addApplication(identifier)
    }

    IconPicker {
        id: iconPicker
        onChosen: (name) => sheet.draftIcon = name
    }
}
}

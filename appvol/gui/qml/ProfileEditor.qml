// The editor of one profile: its name, the applications it covers and its knobs.
//
// The sheet is a dialog.  The header (the title and the close button) and the
// footer (the actions) stay put, and only the body scrolls when the window is
// short.  There is no identifier field: the id is derived from the name, and the
// caption under it shows what it becomes.
//
// A profile covers either "only these apps" or "all apps except…", so there is a
// single chip list and a switch that says what the list means.  Two live lines
// help: the applications playing right now, which add themselves in one click,
// and what the profile would select at this moment.

import QtQuick
import QtQuick.Controls as Controls
import QtQuick.Layouts
import org.kde.kirigami as Kirigami

Kirigami.OverlaySheet {
    id: sheet

    // The profile being edited; null creates a new one.
    property var profile: null

    /// The window accent and its readable text, passed down by the window.
    property color accentColor: Kirigami.Theme.highlightColor
    property color accentTextColor: Kirigami.Theme.highlightedTextColor

    /// Asked to remove the profile; the window asks for confirmation.
    signal deleteRequested(var profile)

    property string draftName: ""
    property var draftApps: []
    // What the chip list means: the applications to keep ("include"), or the
    // applications to leave out ("exclude"), which is one list with two readings.
    property string appliesTo: "include"
    property real draftStep: 0
    property bool stepDefault: true
    property real draftMax: 0
    property bool maxDefault: true
    property string draftIcon: ""

    readonly property bool creating: profile === null
    readonly property real globalStep: bridge.config.step || 5
    readonly property real globalMax: bridge.config.max_volume || 100

    // A new profile takes an id derived from its name; an existing one keeps the
    // id in the file, which a rename never changes.
    readonly property string identifier: creating
        ? bridge.newProfileId(draftName)
        : (profile ? profile.id : "")
    readonly property var includeList: appliesTo === "include" ? draftApps : []
    readonly property var excludeList: appliesTo === "exclude" ? draftApps : []

    // The icon "Automatic" stands for: the first application the profile covers,
    // resolved the way the daemon draws it on the OSD.
    readonly property string automaticIcon:
        bridge.profileIcon(includeList, excludeList) || "audio-volume-high"
    readonly property string previewIcon: draftIcon || automaticIcon
    readonly property string iconCaption: {
        if (draftIcon) {
            return "chosen from the theme"
        }
        return bridge.profileIcon(includeList, excludeList)
            ? "from the application"
            : "generic: no single application"
    }
    // The live answer to "what would this profile select right now".
    readonly property var matches: bridge.matchesNow(includeList, excludeList)
    // What is playing and the profile does not name yet, for the "Playing now"
    // chips; a positioner would leave a gap for a hidden delegate, so they are
    // filtered out of the model instead.
    readonly property var playableApps: bridge.applications.filter(
        application => draftApps.indexOf(application.id) === -1)

    function openFor(existing) {
        profile = existing
        if (existing) {
            draftName = existing.name || existing.id
            const include = (existing.include || []).slice()
            const exclude = (existing.exclude || []).slice()
            appliesTo = include.length === 0 && exclude.length > 0 ? "exclude" : "include"
            draftApps = appliesTo === "exclude" ? exclude : include
            stepDefault = !(existing.step > 0)
            draftStep = existing.step > 0 ? existing.step : globalStep
            maxDefault = !(existing.max_volume > 0)
            draftMax = existing.max_volume > 0 ? existing.max_volume : globalMax
            draftIcon = existing.icon || ""
        } else {
            draftName = ""
            appliesTo = "include"
            draftApps = []
            stepDefault = true
            draftStep = globalStep
            maxDefault = true
            draftMax = globalMax
            draftIcon = ""
        }
        open()
    }

    function addApplication(identifier) {
        const value = String(identifier).trim().toLowerCase()
        if (value.length === 0) {
            return
        }
        draftApps = draftApps.concat([value]).filter((id, index, all) => all.indexOf(id) === index)
    }

    function removeApplication(identifier) {
        draftApps = draftApps.filter(id => id !== identifier)
    }

    function iconOf(identifier) {
        return bridge.applicationIcon(identifier) || "audio-volume-high"
    }

    function save() {
        bridge.saveProfile(
            identifier.trim().toLowerCase(),
            draftName.trim(),
            includeList,
            excludeList,
            stepDefault ? 0 : draftStep,
            maxDefault ? 0 : draftMax,
            draftIcon.trim())
        close()
    }

    title: sheet.creating ? "New profile" : "Edit “" + sheet.draftName + "”"

    footer: RowLayout {
        Layout.fillWidth: true
        spacing: Kirigami.Units.smallSpacing

        Controls.Button {
            visible: !sheet.creating
            flat: true
            onClicked: sheet.deleteRequested(sheet.profile)
            contentItem: RowLayout {
                spacing: Kirigami.Units.smallSpacing

                Kirigami.Icon {
                    source: "edit-delete"
                    color: Kirigami.Theme.negativeTextColor
                    implicitWidth: Kirigami.Units.iconSizes.small
                    implicitHeight: implicitWidth
                }

                Controls.Label {
                    text: "Delete profile"
                    color: Kirigami.Theme.negativeTextColor
                }
            }
        }

        Item { Layout.fillWidth: true }

        Controls.Button {
            text: "Cancel"
            onClicked: sheet.close()
        }

        PrimaryButton {
            text: sheet.creating ? "Create profile" : "Save"
            icon.name: "dialog-ok-apply"
            accentColor: sheet.accentColor
            accentTextColor: sheet.accentTextColor
            enabled: sheet.draftName.trim().length > 0
            onClicked: sheet.save()
        }
    }

    ColumnLayout {
        Layout.preferredWidth: Kirigami.Units.gridUnit * 28
        spacing: Kirigami.Units.smallSpacing

        // -- the name, with the identifier it earns -------------------------
        ColumnLayout {
            Layout.fillWidth: true
            spacing: Kirigami.Units.smallSpacing / 2

            Controls.Label {
                text: "Name"
                font: Kirigami.Theme.smallFont
                opacity: 0.7
            }

            Controls.TextField {
                id: nameField
                Layout.fillWidth: true
                text: sheet.draftName
                placeholderText: "Spotify"
                onTextEdited: sheet.draftName = text
            }

            Controls.Label {
                Layout.fillWidth: true
                elide: Text.ElideRight
                font: Kirigami.Theme.smallFont
                opacity: 0.6
                text: sheet.creating
                    ? "Identifier: " + sheet.identifier + " (made from the name)"
                    : "Identifier: " + sheet.identifier
            }
        }

        // -- the switch that says what the list means -----------------------
        ColumnLayout {
            Layout.fillWidth: true
            Layout.topMargin: Kirigami.Units.smallSpacing
            spacing: Kirigami.Units.smallSpacing / 2

            Controls.Label {
                text: "Applies to"
                font: Kirigami.Theme.smallFont
                opacity: 0.7
            }

            ModeSwitcher {
                Layout.fillWidth: true
                options: [
                    { key: "include", text: "Only these apps" },
                    { key: "exclude", text: "All apps except…" }
                ]
                current: sheet.appliesTo
                accentColor: sheet.accentColor
                accentTextColor: sheet.accentTextColor
                onActivated: (key) => sheet.appliesTo = key
            }
        }

        // -- the list of applications, as chips -----------------------------
        Rectangle {
            Layout.fillWidth: true
            Layout.topMargin: Kirigami.Units.smallSpacing / 2
            implicitHeight: chipFlow.implicitHeight + Kirigami.Units.smallSpacing * 2
            radius: Kirigami.Units.cornerRadius
            color: Kirigami.Theme.alternateBackgroundColor
            border.width: 1
            border.color: Qt.rgba(Kirigami.Theme.textColor.r, Kirigami.Theme.textColor.g,
                                  Kirigami.Theme.textColor.b, 0.18)

            Flow {
                id: chipFlow
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                anchors.leftMargin: Kirigami.Units.smallSpacing
                anchors.rightMargin: Kirigami.Units.smallSpacing
                spacing: Kirigami.Units.smallSpacing

                Controls.Label {
                    visible: sheet.draftApps.length === 0
                    height: Kirigami.Units.gridUnit * 1.9
                    verticalAlignment: Text.AlignVCenter
                    text: "No application yet"
                    font: Kirigami.Theme.smallFont
                    opacity: 0.6
                }

                Repeater {
                    model: sheet.draftApps

                    delegate: Rectangle {
                        id: chip
                        required property string modelData

                        implicitWidth: chipRow.implicitWidth + Kirigami.Units.smallSpacing * 2
                        implicitHeight: Kirigami.Units.gridUnit * 1.9
                        radius: height / 2
                        color: Qt.rgba(Kirigami.Theme.textColor.r, Kirigami.Theme.textColor.g,
                                       Kirigami.Theme.textColor.b, 0.06)
                        border.width: 1
                        border.color: Qt.rgba(Kirigami.Theme.textColor.r, Kirigami.Theme.textColor.g,
                                              Kirigami.Theme.textColor.b, 0.18)

                        RowLayout {
                            id: chipRow
                            anchors.centerIn: parent
                            spacing: Kirigami.Units.smallSpacing / 2

                            Kirigami.Icon {
                                source: sheet.iconOf(chip.modelData)
                                implicitWidth: Kirigami.Units.iconSizes.small
                                implicitHeight: implicitWidth
                            }

                            Controls.Label {
                                text: chip.modelData
                                font: Kirigami.Theme.smallFont
                            }

                            Controls.ToolButton {
                                icon.name: "window-close"
                                icon.width: Kirigami.Units.iconSizes.small
                                icon.height: Kirigami.Units.iconSizes.small
                                display: Controls.AbstractButton.IconOnly
                                leftPadding: Kirigami.Units.smallSpacing / 2
                                rightPadding: Kirigami.Units.smallSpacing / 2
                                Controls.ToolTip.visible: hovered
                                Controls.ToolTip.text: sheet.appliesTo === "exclude"
                                    ? "Stop leaving it out"
                                    : "Remove from the profile"
                                onClicked: sheet.removeApplication(chip.modelData)
                            }
                        }
                    }
                }

                Controls.Button {
                    id: addChip
                    text: "Add app…"
                    // The chip next to it is a grid unit and a half tall; without
                    // the same height the Flow aligns this to the top of the row.
                    implicitHeight: Kirigami.Units.gridUnit * 1.9
                    leftPadding: Kirigami.Units.smallSpacing
                    rightPadding: Kirigami.Units.smallSpacing
                    topPadding: Kirigami.Units.smallSpacing / 2
                    bottomPadding: Kirigami.Units.smallSpacing / 2
                    onClicked: picker.openFor(sheet.draftApps)
                    // A Rectangle rather than the Breeze frame: the flat frame
                    // paints the caption itself, on top of the content below.
                    background: Rectangle {
                        radius: height / 2
                        color: addChip.hovered
                            ? Qt.rgba(Kirigami.Theme.textColor.r, Kirigami.Theme.textColor.g,
                                      Kirigami.Theme.textColor.b, 0.08)
                            : "transparent"
                    }
                    contentItem: RowLayout {
                        spacing: Kirigami.Units.smallSpacing / 2

                        Kirigami.Icon {
                            source: "list-add"
                            color: sheet.accentColor
                            implicitWidth: Kirigami.Units.iconSizes.small
                            implicitHeight: implicitWidth
                        }

                        Controls.Label {
                            text: "Add app…"
                            color: sheet.accentColor
                            font.bold: true
                        }
                    }
                }
            }
        }

        // -- what is playing, one click to add ------------------------------
        RowLayout {
            Layout.fillWidth: true
            Layout.topMargin: Kirigami.Units.smallSpacing / 2
            spacing: Kirigami.Units.smallSpacing
            visible: sheet.playableApps.length > 0

            Controls.Label {
                text: "Playing now"
                font: Kirigami.Theme.smallFont
                opacity: 0.7
            }

            Flow {
                Layout.fillWidth: true
                spacing: Kirigami.Units.smallSpacing

                Repeater {
                    model: sheet.playableApps

                    delegate: Controls.Button {
                        id: playingChip
                        required property var modelData

                        onClicked: sheet.addApplication(modelData.id)
                        leftPadding: Kirigami.Units.largeSpacing
                        rightPadding: Kirigami.Units.largeSpacing
                        topPadding: Kirigami.Units.smallSpacing
                        bottomPadding: Kirigami.Units.smallSpacing

                        background: Rectangle {
                            radius: height / 2
                            color: playingChip.hovered
                                ? Qt.rgba(Kirigami.Theme.textColor.r, Kirigami.Theme.textColor.g,
                                          Kirigami.Theme.textColor.b, 0.08)
                                : "transparent"
                            border.width: 1
                            border.color: Qt.rgba(Kirigami.Theme.textColor.r, Kirigami.Theme.textColor.g,
                                                  Kirigami.Theme.textColor.b, 0.35)
                        }

                        contentItem: RowLayout {
                            spacing: Kirigami.Units.smallSpacing / 2

                            Kirigami.Icon {
                                source: "list-add"
                                color: sheet.accentColor
                                implicitWidth: Kirigami.Units.iconSizes.small
                                implicitHeight: implicitWidth
                            }

                            Controls.Label {
                                text: playingChip.modelData.label
                                font: Kirigami.Theme.smallFont
                            }
                        }
                    }
                }
            }
        }

        // -- what the profile would select at this moment --------------------
        Rectangle {
            Layout.fillWidth: true
            Layout.topMargin: Kirigami.Units.smallSpacing / 2
            implicitHeight: matchesRow.implicitHeight + Kirigami.Units.smallSpacing * 2
            radius: Kirigami.Units.cornerRadius
            color: Qt.rgba(sheet.accentColor.r, sheet.accentColor.g, sheet.accentColor.b, 0.10)
            border.width: 1
            border.color: Qt.rgba(sheet.accentColor.r, sheet.accentColor.g, sheet.accentColor.b, 0.35)

            RowLayout {
                id: matchesRow
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                anchors.leftMargin: Kirigami.Units.smallSpacing
                anchors.rightMargin: Kirigami.Units.smallSpacing
                spacing: Kirigami.Units.smallSpacing / 2

                Kirigami.Icon {
                    source: "dialog-ok-apply"
                    color: sheet.accentColor
                    implicitWidth: Kirigami.Units.iconSizes.small
                    implicitHeight: implicitWidth
                }

                Controls.Label {
                    text: "Matches now:"
                    font.pointSize: Kirigami.Theme.smallFont.pointSize
                    opacity: 0.8
                }

                Controls.Label {
                    Layout.fillWidth: true
                    visible: bridge.applications.length > 0 && sheet.matches.labels.length > 0
                    text: sheet.matches.labels.join(", ")
                    elide: Text.ElideRight
                    font.pointSize: Kirigami.Theme.smallFont.pointSize
                    font.bold: true
                }

                Controls.Label {
                    visible: bridge.applications.length > 0 && sheet.matches.labels.length === 0
                    Layout.fillWidth: true
                    text: "no stream matches"
                    elide: Text.ElideRight
                    font: Kirigami.Theme.smallFont
                    opacity: 0.7
                }

                Controls.Label {
                    visible: bridge.applications.length === 0
                    Layout.fillWidth: true
                    text: "nothing is playing"
                    font: Kirigami.Theme.smallFont
                    opacity: 0.7
                }

                Controls.Label {
                    visible: bridge.applications.length > 0 && sheet.matches.labels.length > 0
                    text: "· " + sheet.matches.streams
                        + (sheet.matches.streams === 1 ? " stream" : " streams")
                    font: Kirigami.Theme.smallFont
                    opacity: 0.7
                }
            }
        }

        // -- step and maximum volume, side by side --------------------------
        RowLayout {
            Layout.fillWidth: true
            Layout.topMargin: Kirigami.Units.smallSpacing
            spacing: Kirigami.Units.largeSpacing

            ColumnLayout {
                Layout.fillWidth: true
                spacing: Kirigami.Units.smallSpacing / 2

                Controls.Label {
                    text: "Step"
                    font: Kirigami.Theme.smallFont
                    opacity: 0.7
                }

                RowLayout {
                    Layout.fillWidth: true
                    spacing: Kirigami.Units.smallSpacing

                    Controls.CheckBox {
                        text: "Default (" + Math.round(sheet.globalStep) + " %)"
                        checked: sheet.stepDefault
                        onToggled: sheet.stepDefault = checked
                    }

                    Item { Layout.fillWidth: true }

                    Controls.SpinBox {
                        id: stepBox
                        enabled: !sheet.stepDefault
                        from: 1
                        to: 50
                        editable: true
                        value: sheet.draftStep
                        textFromValue: (value) => value + " %"
                        onValueModified: sheet.draftStep = value
                    }
                }
            }

            ColumnLayout {
                Layout.fillWidth: true
                spacing: Kirigami.Units.smallSpacing / 2

                Controls.Label {
                    text: "Maximum volume"
                    font: Kirigami.Theme.smallFont
                    opacity: 0.7
                }

                RowLayout {
                    Layout.fillWidth: true
                    spacing: Kirigami.Units.smallSpacing

                    Controls.CheckBox {
                        text: "Default (" + Math.round(sheet.globalMax) + " %)"
                        checked: sheet.maxDefault
                        onToggled: sheet.maxDefault = checked
                    }

                    Item { Layout.fillWidth: true }

                    Controls.SpinBox {
                        id: maxBox
                        enabled: !sheet.maxDefault
                        from: 1
                        to: 150
                        editable: true
                        value: sheet.draftMax
                        textFromValue: (value) => value + " %"
                        onValueModified: sheet.draftMax = value
                    }
                }
            }
        }

        // -- the icon -------------------------------------------------------
        ColumnLayout {
            Layout.fillWidth: true
            Layout.topMargin: Kirigami.Units.smallSpacing
            spacing: Kirigami.Units.smallSpacing / 2

            Controls.Label {
                text: "Icon"
                font: Kirigami.Theme.smallFont
                opacity: 0.7
            }

            RowLayout {
                Layout.fillWidth: true
                spacing: Kirigami.Units.smallSpacing

                Kirigami.Icon {
                    source: sheet.previewIcon
                    implicitWidth: Kirigami.Units.iconSizes.medium
                    implicitHeight: implicitWidth
                }

                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 0

                    Controls.Label {
                        Layout.fillWidth: true
                        text: sheet.draftIcon || "Automatic"
                        elide: Text.ElideRight
                    }

                    Controls.Label {
                        Layout.fillWidth: true
                        text: sheet.iconCaption
                        elide: Text.ElideRight
                        font: Kirigami.Theme.smallFont
                        opacity: 0.6
                    }
                }

                Controls.Button {
                    text: "Change…"
                    onClicked: {
                        iconPicker.selected = sheet.draftIcon
                        iconPicker.openFor()
                    }
                }
            }
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

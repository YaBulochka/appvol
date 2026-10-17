// The window of appvol: the pinned Active card, the list of profiles or running
// applications, and the editor.
//
// The window is a client of appvold: it draws what org.appvol.Daemon reports and
// writes back through the same interface.  Everything it can do is a call on
// `bridge`.

import QtQuick
import QtQuick.Controls as Controls
import QtQuick.Layouts
import QtQuick.Shapes
import org.kde.kirigami as Kirigami

Kirigami.ApplicationWindow {
    id: root

    title: "appvol"
    width: Kirigami.Units.gridUnit * 36
    height: Kirigami.Units.gridUnit * 38
    minimumWidth: 380
    minimumHeight: Kirigami.Units.gridUnit * 18

    // A hotkey may change the volume while the window is open, so every time
    // the window comes back to the front the panel is read again.
    onActiveChanged: if (active) bridge.refresh()

    readonly property var activeProfile: {
        for (let i = 0; i < bridge.profiles.length; ++i) {
            if (bridge.profiles[i].builtin) {
                return bridge.profiles[i]
            }
        }
        return null
    }
    // The list holds what the volume keys cycle besides Active: the profiles of
    // profiles.toml, or the applications that are playing in the running-apps
    // view.  The daemon reports Active as a profile too, so it is filtered out.
    readonly property var listedProfiles: bridge.profiles.filter(profile => !profile.builtin)
    readonly property bool autoMode: bridge.mode === "auto"
    // The window's accent; a Breeze Button switches to its own color set, so the
    // header passes this one down to the controls that must keep it.
    readonly property color accentColor: Kirigami.Theme.highlightColor
    readonly property color accentTextColor: Kirigami.Theme.highlightedTextColor

    readonly property string footerSummary: {
        if (autoMode) {
            return "Keys cycle Active and the running applications"
        }
        if (bridge.idleTimeout > 0) {
            return "Idle profiles return to Active after " + Math.round(bridge.idleTimeout / 60) + " min"
        }
        return "A profile stays current until you switch"
    }
    readonly property string footerHint: {
        if (autoMode) {
            return "The volume keys cycle Active and every application that is playing, in the order the applications started."
                + " A per-profile key does nothing here; switch back to the profiles to use one."
        }
        const idle = bridge.idleTimeout > 0
            ? "A profile goes back to Active after " + Math.round(bridge.idleTimeout / 60) + " minutes without use."
            : "A profile stays current until you switch."
        return idle + " The volume keys and the profile keys are set in System Settings → Shortcuts, entry “Appvol”."
    }

    // The volume of a target can change outside the window: the hotkeys, or
    // another application on the same streams.  A light poll keeps the sliders
    // honest while the window is on screen; a hidden window makes no calls.
    // Half a second is close enough to the keys, and an idle overview costs the
    // daemon well under a millisecond (the icon theme is cached), so the timer
    // is cheap.
    Timer {
        interval: 500
        running: root.visible
        repeat: true
        onTriggered: bridge.refresh()
    }

    pageStack.initialPage: Kirigami.Page {
        id: page
        globalToolBarStyle: Kirigami.ApplicationHeaderStyle.None
        padding: 0

        ColumnLayout {
            anchors.fill: parent
            spacing: 0

            // -- header ------------------------------------------------
            Rectangle {
                Layout.fillWidth: true
                color: Kirigami.Theme.alternateBackgroundColor
                implicitHeight: headerRow.implicitHeight + Kirigami.Units.largeSpacing * 2

                RowLayout {
                    id: headerRow
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.verticalCenter: parent.verticalCenter
                    anchors.leftMargin: Kirigami.Units.largeSpacing
                    anchors.rightMargin: Kirigami.Units.largeSpacing
                    spacing: Kirigami.Units.smallSpacing

                    ModeSwitcher {
                        Layout.preferredWidth: Kirigami.Units.gridUnit * 14
                        Layout.minimumWidth: Kirigami.Units.gridUnit * 8
                        options: [
                            { key: "profiles", text: "Profiles" },
                            { key: "auto", text: "Running apps" }
                        ]
                        current: bridge.mode
                        accentColor: root.accentColor
                        accentTextColor: root.accentTextColor
                        onActivated: (key) => bridge.setMode(key)
                    }

                    Item { Layout.fillWidth: true }

                    PrimaryButton {
                        text: "New profile"
                        icon.name: "list-add"
                        accentColor: root.accentColor
                        accentTextColor: root.accentTextColor
                        showText: root.width >= 480
                        visible: !root.autoMode
                        onClicked: editor.openFor(null)
                    }

                    Controls.ToolButton {
                        icon.name: "view-refresh"
                        Controls.ToolTip.visible: hovered
                        Controls.ToolTip.text: "Refresh"
                        onClicked: bridge.refresh()
                    }

                    Controls.ToolButton {
                        icon.name: "input-keyboard"
                        visible: root.width >= 480
                        Controls.ToolTip.visible: hovered
                        Controls.ToolTip.text: "Bind Keys…"
                        onClicked: bridge.openShortcuts()
                    }

                    Controls.ToolButton {
                        id: menuButton
                        icon.name: "overflow-menu"
                        Controls.ToolTip.visible: hovered
                        Controls.ToolTip.text: "Settings"
                        onClicked: headerMenu.popup()
                    }
                }

                Rectangle {
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.bottom: parent.bottom
                    height: 1
                    color: Qt.rgba(Kirigami.Theme.textColor.r, Kirigami.Theme.textColor.g,
                                   Kirigami.Theme.textColor.b, 0.12)
                }
            }

            Kirigami.InlineMessage {
                Layout.fillWidth: true
                Layout.leftMargin: Kirigami.Units.largeSpacing
                Layout.rightMargin: Kirigami.Units.largeSpacing
                Layout.topMargin: Kirigami.Units.largeSpacing
                visible: bridge.error.length > 0
                type: bridge.daemonRunning ? Kirigami.MessageType.Error : Kirigami.MessageType.Warning
                text: bridge.error
                actions: [
                    Kirigami.Action {
                        text: "Try Again"
                        onTriggered: bridge.refresh()
                    }
                ]
            }

            // -- the pinned Active card ---------------------------------
            ActiveCard {
                Layout.fillWidth: true
                Layout.leftMargin: Kirigami.Units.largeSpacing
                Layout.rightMargin: Kirigami.Units.largeSpacing
                Layout.topMargin: Kirigami.Units.largeSpacing
                Layout.bottomMargin: Kirigami.Units.smallSpacing
                visible: bridge.daemonRunning
                accentColor: root.accentColor
                profile: root.activeProfile
            }

            // -- the section header -------------------------------------
            RowLayout {
                Layout.fillWidth: true
                Layout.leftMargin: Kirigami.Units.largeSpacing + Kirigami.Units.smallSpacing
                Layout.rightMargin: Kirigami.Units.largeSpacing + Kirigami.Units.smallSpacing
                spacing: Kirigami.Units.smallSpacing
                visible: bridge.daemonRunning

                Controls.Label {
                    text: root.autoMode ? "RUNNING APPLICATIONS" : "PROFILES"
                    font.pointSize: Kirigami.Theme.smallFont.pointSize
                    font.bold: true
                    font.letterSpacing: 1.2
                    opacity: 0.7
                }

                Item { Layout.fillWidth: true }

                Controls.Label {
                    visible: !root.autoMode
                    text: root.listedProfiles.length
                    font: Kirigami.Theme.smallFont
                    opacity: 0.7
                }

                Controls.Label {
                    visible: root.autoMode
                    text: "Keys cycle through these"
                    font: Kirigami.Theme.smallFont
                    opacity: 0.7
                }

                Controls.ToolButton {
                    visible: root.autoMode
                    flat: true
                    text: "ⓘ"
                    display: Controls.AbstractButton.TextOnly
                    implicitWidth: Kirigami.Units.gridUnit * 1.2
                    Controls.ToolTip.visible: hovered
                    Controls.ToolTip.text: "The volume keys cycle Active and every application that is playing, in the order the applications started."
                }
            }

            // -- the list area ------------------------------------------
            Item {
                Layout.fillWidth: true
                Layout.fillHeight: true
                Layout.topMargin: Kirigami.Units.smallSpacing
                Layout.bottomMargin: Kirigami.Units.smallSpacing

                ListView {
                    id: list
                    anchors.fill: parent
                    visible: bridge.daemonRunning && root.listedProfiles.length > 0
                    clip: true
                    spacing: 0
                    leftMargin: Kirigami.Units.largeSpacing
                    rightMargin: Kirigami.Units.largeSpacing
                    model: root.listedProfiles

                    delegate: ProfileRow {
                        width: list.width - list.leftMargin - list.rightMargin
                        profile: modelData
                        accentColor: root.accentColor
                        onEditRequested: editor.openFor(profile)
                        onRemoveRequested: removeDialog.askFor(profile)
                        onStepRequested: stepDialog.openFor(profile)
                    }

                    Controls.ScrollBar.vertical: Controls.ScrollBar {
                        policy: Controls.ScrollBar.AsNeeded
                    }
                }

                // The empty profiles view: a dashed New profile row, where the
                // list would be; the header button does the same.
                Item {
                    id: newRow
                    anchors.top: parent.top
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.leftMargin: Kirigami.Units.largeSpacing
                    anchors.rightMargin: Kirigami.Units.largeSpacing
                    height: Kirigami.Units.gridUnit * 3.2
                    visible: bridge.daemonRunning && !root.autoMode
                        && root.listedProfiles.length === 0

                    HoverHandler { id: newRowHover }

                    Shape {
                        anchors.fill: parent
                        ShapePath {
                            strokeColor: newRowHover.hovered
                                ? Kirigami.Theme.highlightColor
                                : Qt.rgba(Kirigami.Theme.textColor.r, Kirigami.Theme.textColor.g,
                                          Kirigami.Theme.textColor.b, 0.35)
                            strokeWidth: 1
                            strokeStyle: ShapePath.DashLine
                            dashPattern: [5, 4]
                            fillColor: "transparent"
                            startX: 0.5
                            startY: 0.5
                            PathLine { x: newRow.width - 0.5; y: 0.5 }
                            PathLine { x: newRow.width - 0.5; y: newRow.height - 0.5 }
                            PathLine { x: 0.5; y: newRow.height - 0.5 }
                            PathLine { x: 0.5; y: 0.5 }
                        }
                    }

                    RowLayout {
                        anchors.centerIn: parent
                        spacing: Kirigami.Units.smallSpacing

                        Kirigami.Icon {
                            source: "list-add"
                            implicitWidth: Kirigami.Units.iconSizes.smallMedium
                            implicitHeight: implicitWidth
                        }

                        Controls.Label {
                            text: "New profile"
                            opacity: 0.8
                        }
                    }

                    TapHandler {
                        onTapped: editor.openFor(null)
                    }
                }

                Kirigami.PlaceholderMessage {
                    anchors.centerIn: parent
                    width: parent.width - Kirigami.Units.gridUnit * 4
                    visible: bridge.daemonRunning && root.autoMode
                        && root.listedProfiles.length === 0
                    icon.name: "audio-volume-high"
                    text: "Nothing is playing"
                    explanation: "Every application that plays joins this list, and the volume keys cycle Active and the applications, in the order they started."
                }

                Kirigami.PlaceholderMessage {
                    anchors.centerIn: parent
                    width: parent.width - Kirigami.Units.gridUnit * 4
                    visible: !bridge.daemonRunning
                    icon.name: "system-run"
                    text: "appvold is not running"
                    explanation: "Start the daemon with `systemctl --user enable --now appvold` and try again."
                    helpfulAction: Kirigami.Action {
                        text: "Try Again"
                        onTriggered: bridge.refresh()
                    }
                }
            }

            // -- footer ------------------------------------------------
            Rectangle {
                Layout.fillWidth: true
                color: Kirigami.Theme.alternateBackgroundColor
                implicitHeight: footerRow.implicitHeight + Kirigami.Units.largeSpacing

                Rectangle {
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.top: parent.top
                    height: 1
                    color: Qt.rgba(Kirigami.Theme.textColor.r, Kirigami.Theme.textColor.g,
                                   Kirigami.Theme.textColor.b, 0.12)
                }

                RowLayout {
                    id: footerRow
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.verticalCenter: parent.verticalCenter
                    anchors.leftMargin: Kirigami.Units.largeSpacing
                    anchors.rightMargin: Kirigami.Units.largeSpacing
                    spacing: Kirigami.Units.smallSpacing

                    Controls.Label {
                        text: root.footerSummary
                        font: Kirigami.Theme.smallFont
                        opacity: 0.7
                    }

                    Controls.ToolButton {
                        flat: true
                        text: "ⓘ"
                        display: Controls.AbstractButton.TextOnly
                        implicitWidth: Kirigami.Units.gridUnit * 1.2
                        implicitHeight: Kirigami.Units.gridUnit * 1.2
                        Controls.ToolTip.visible: hovered
                        Controls.ToolTip.text: root.footerHint
                    }

                    Item { Layout.fillWidth: true }

                    Controls.Label {
                        text: "appvol " + bridge.version
                        font: Kirigami.Theme.smallFont
                        opacity: 0.7
                    }
                }
            }
        }
    }

    Controls.Menu {
        id: headerMenu
        objectName: "headerMenu"

        Controls.MenuItem {
            id: osdItem
            text: "OSD App Name"
            // A switch in the menu, as the mockup shows: the state is the one
            // the daemon reports, and the switch is what moves it.
            contentItem: RowLayout {
                spacing: Kirigami.Units.smallSpacing

                Controls.Label {
                    Layout.fillWidth: true
                    text: osdItem.text
                    verticalAlignment: Text.AlignVCenter
                }

                Controls.Switch {
                    id: osdSwitch
                    checked: bridge.osdShowName
                    onToggled: bridge.setOsdShowName(checked)
                }
            }
        }

        Controls.MenuItem {
            text: "Bind Keys…"
            icon.name: "input-keyboard"
            onTriggered: bridge.openShortcuts()
        }

        Controls.MenuItem {
            text: "Reload from File"
            icon.name: "document-revert"
            onTriggered: bridge.reload()
        }

        Controls.MenuSeparator {}

        Controls.MenuItem {
            text: "About appvol"
            icon.name: "help-about"
            onTriggered: aboutDialog.open()
        }

        Connections {
            target: bridge
            function onConfigChanged() {
                osdSwitch.checked = bridge.osdShowName
            }
        }
    }

    ProfileEditor {
        id: editor
        objectName: "profileEditor"
        accentColor: root.accentColor
        accentTextColor: root.accentTextColor
        onDeleteRequested: (profile) => {
            editor.close()
            removeDialog.askFor(profile)
        }
    }

    StepDialog {
        id: stepDialog
        objectName: "stepDialog"
    }

    AboutDialog {
        id: aboutDialog
        objectName: "aboutDialog"
    }

    Controls.Dialog {
        id: removeDialog
        objectName: "removeDialog"

        property var target: null

        function askFor(profile) {
            target = profile
            open()
        }

        title: "Remove Profile"
        modal: true
        anchors.centerIn: parent
        standardButtons: Controls.Dialog.Cancel | Controls.Dialog.Ok

        contentItem: Controls.Label {
            wrapMode: Text.WordWrap
            text: removeDialog.target
                ? "Remove “" + (removeDialog.target.name || removeDialog.target.id) + "” and its key binding?"
                : ""
        }

        onAccepted: if (target) bridge.removeProfile(target.id)
    }
}

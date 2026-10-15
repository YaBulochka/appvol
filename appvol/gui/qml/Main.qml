// The window of appvol: the list of profiles, their live volume and the editor.
//
// The window is a client of appvold: it draws what org.appvol.Daemon reports and
// writes back through the same interface.  Everything it can do is a call on
// `bridge`.

import QtQuick
import QtQuick.Controls as Controls
import QtQuick.Layouts
import org.kde.kirigami as Kirigami

Kirigami.ApplicationWindow {
    id: root

    title: "appvol"
    width: Kirigami.Units.gridUnit * 36
    height: Kirigami.Units.gridUnit * 32
    minimumWidth: Kirigami.Units.gridUnit * 28
    minimumHeight: Kirigami.Units.gridUnit * 18

    // A hotkey or the tray may change the volume while the window is open, so
    // every time the window comes back to the front the panel is read again.
    onActiveChanged: if (active) bridge.refresh()

    pageStack.initialPage: Kirigami.Page {
        id: profilesPage
        title: "Profiles"

        actions: [
            Kirigami.Action {
                text: "New Profile"
                icon.name: "list-add"
                onTriggered: editor.openFor(null)
            },
            Kirigami.Action {
                text: "Refresh"
                icon.name: "view-refresh"
                onTriggered: bridge.refresh()
            },
            Kirigami.Action {
                text: "Bind Keys"
                icon.name: "configure"
                onTriggered: bridge.openShortcuts()
            },
            Kirigami.Action {
                text: "Reload from File"
                icon.name: "document-revert"
                displayHint: Kirigami.DisplayHint.AlwaysHide
                onTriggered: bridge.reload()
            }
        ]

        ColumnLayout {
            anchors.fill: parent
            anchors.margins: Kirigami.Units.largeSpacing
            spacing: Kirigami.Units.largeSpacing

            Kirigami.InlineMessage {
                Layout.fillWidth: true
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

            ListView {
                id: list
                Layout.fillWidth: true
                Layout.fillHeight: true
                clip: true
                spacing: Kirigami.Units.largeSpacing
                model: bridge.profiles
                delegate: ProfileRow {
                    width: list.width
                    profile: modelData
                    onEditRequested: editor.openFor(profile)
                    onRemoveRequested: removeDialog.askFor(profile)
                }
                footer: Controls.Label {
                    width: list.width
                    topPadding: Kirigami.Units.largeSpacing
                    wrapMode: Text.WordWrap
                    opacity: 0.7
                    font: Kirigami.Theme.smallFont
                    text: {
                        let text = bridge.idleTimeout > 0
                            ? "A profile goes back to Active after " + Math.round(bridge.idleTimeout / 60)
                                + " minutes without use."
                            : "A profile stays current until you switch."
                        return text + " The keys bound to a profile are set in System Settings → Shortcuts, entry “appvol profiles”."
                            + " appvol " + bridge.version
                    }
                }
            }

            Kirigami.PlaceholderMessage {
                Layout.fillWidth: true
                Layout.fillHeight: true
                visible: bridge.profiles.length <= 1 && bridge.daemonRunning
                icon.name: "list-add"
                text: "No profiles yet"
                explanation: "A profile targets the streams of one application, so you can raise Spotify and lower everything else."
                helpfulAction: Kirigami.Action {
                    text: "New Profile"
                    icon.name: "list-add"
                    onTriggered: editor.openFor(null)
                }
            }
        }
    }

    ProfileEditor {
        id: editor
    }

    Controls.Dialog {
        id: removeDialog

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

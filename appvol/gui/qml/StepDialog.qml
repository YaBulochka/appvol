// The step of one profile, reached from the row menu.
//
// A profile of its own may carry a step; zero means it follows the global one,
// which the Active card sets.

import QtQuick
import QtQuick.Controls as Controls
import QtQuick.Layouts
import org.kde.kirigami as Kirigami

Controls.Dialog {
    id: dialog

    property var profile: null

    function openFor(existing) {
        profile = existing
        if (existing) {
            stepBox.value = Math.round(existing.step || bridge.config.step || 5)
        }
        open()
    }

    title: profile ? "Step — " + (profile.name || profile.id) : "Step"
    modal: true
    anchors.centerIn: parent
    standardButtons: Controls.Dialog.Cancel | Controls.Dialog.Ok

    contentItem: ColumnLayout {
        spacing: Kirigami.Units.smallSpacing

        Controls.Label {
            Layout.fillWidth: true
            wrapMode: Text.WordWrap
            text: "The volume keys move the streams of this profile by this much."
        }

        RowLayout {
            Layout.topMargin: Kirigami.Units.smallSpacing

            Controls.Label { text: "Step:" }

            Controls.SpinBox {
                id: stepBox
                editable: true
                from: 0
                to: 50
                textFromValue: (value) => Math.round(value) + " %"
            }

            Item { Layout.fillWidth: true }
        }

        Controls.Label {
            Layout.fillWidth: true
            wrapMode: Text.WordWrap
            opacity: 0.7
            font: Kirigami.Theme.smallFont
            text: "0 % follows the global step of the Active profile."
        }
    }

    onAccepted: if (profile) {
        bridge.setStep(profile.id, stepBox.value)
    }
}

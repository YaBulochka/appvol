// A step field, in percent, that accepts fractional values ("2.5 %").
//
// Qt's SpinBox works on integers only, so the field keeps the step scaled by a
// decimal factor: the control holds hundredths of a percent and `realValue` is
// the percent the callers set and read.  The editable text carries the " %"
// suffix, and the style's default integer validator would reject both the
// suffix and the decimal point, so a regular expression takes its place.

import QtQuick
import QtQuick.Controls as Controls

Controls.SpinBox {
    id: box

    /// The step in percent, the value the callers set and read.
    property real realValue: 5.0
    /// The range of the field, in percent; the Active step starts at 1.
    property real minimum: 0.0
    property real maximum: 50.0

    /// Hundredths of a percent: two decimals is all a step ever needs.
    readonly property int factor: 100

    /// Emitted when the user changes the value, not when a caller sets it.
    signal edited(real value)

    function syncValue() {
        const scaled = Math.round(realValue * factor)
        if (value !== scaled) {
            value = scaled
        }
    }

    onRealValueChanged: syncValue()
    Component.onCompleted: syncValue()

    from: Math.round(minimum * factor)
    to: Math.round(maximum * factor)
    // Half a percent per click; a finer step is a matter of typing it.
    stepSize: factor / 2
    editable: true

    validator: RegularExpressionValidator {
        regularExpression: /^\s*-?\d*[.,]?\d*\s*%?\s*$/
    }
    textFromValue: (value) => bridge.formatStep(value / factor) + " %"
    valueFromText: (text) => Math.round(bridge.parseStep(text) * factor)

    onValueModified: {
        realValue = value / factor
        edited(realValue)
    }
}

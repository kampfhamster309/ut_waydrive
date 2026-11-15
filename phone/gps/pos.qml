import QtQuick 2.12
import QtPositioning 5.12

// Headless location client for aa-gps-bridge.py. Prints "POS {json}" for every update from
// Ubuntu Touch's location service. Exits cleanly (stops the source first) when the file
// /tmp/aa-gps-stop appears (containing "stop"), or after maxSecs / maxFixes if those are set (0 = no limit).
Item {
    property int maxSecs: 0
    property int maxFixes: 0
    property int fixes: 0
    property bool finishing: false
    function finish() { if (finishing) return; finishing = true; src.stop(); quitTimer.start() }
    Timer { id: quitTimer; interval: 500; onTriggered: Qt.quit() }
    Timer { interval: maxSecs * 1000; running: maxSecs > 0; onTriggered: finish() }
    Timer {
        interval: 1000; running: true; repeat: true
        onTriggered: {
            var xhr = new XMLHttpRequest()
            xhr.onreadystatechange = function() {
                if (xhr.readyState === XMLHttpRequest.DONE && xhr.responseText.indexOf("stop") === 0) finish()
            }
            xhr.open("GET", "file:///tmp/aa-gps-stop"); xhr.send()
        }
    }
    PositionSource {
        id: src; active: true; updateInterval: 1000
        Component.onCompleted: console.log("SRC", name, "valid", valid)
        onSourceErrorChanged: console.log("ERR", sourceError)
        onPositionChanged: {
            var p = position, c = p.coordinate
            if (!c.isValid) return
            console.log("POS", JSON.stringify({lat: c.latitude, lon: c.longitude, alt: p.altitudeValid ? c.altitude : null,
                acc: p.horizontalAccuracyValid ? p.horizontalAccuracy : null, speed: p.speedValid ? p.speed : null,
                dir: p.directionValid ? p.direction : null, t: p.timestamp.getTime()}))
            fixes++
            if (maxFixes > 0 && fixes >= maxFixes) finish()
        }
    }
}

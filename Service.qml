import QtQuick
import Quickshell.Io

Item {
    id: root
    property var shell: null
    property var manifest: null
    property var settings: ({})
    property var state: ({ state: "starting" })
    readonly property string managerPath: decodeURIComponent(Qt.resolvedUrl("manager.py").toString().replace(/^file:\/\//, ""))

    function durations() {
        return {
            showDuration: Math.max(0, Math.min(290, Number(settings.showDuration ?? 180) || 0)),
            hideDuration: Math.max(0, Math.min(290, Number(settings.hideDuration ?? 120) || 0))
        }
    }

    Process {
        id: manager
        command: ["/usr/bin/python3", root.managerPath]
        stdinEnabled: true
        stdout: SplitParser {
            onRead: data => {
                try {
                    root.state = JSON.parse(data)
                }
                catch (error) { console.warn("Konocap: invalid manager status") }
            }
        }
        stderr: SplitParser { onRead: data => console.warn("Konocap:", data) }
        onExited: (code, status) => {
            if (code !== 0) root.state = { state: "error", exitCode: code }
        }
    }

    IpcHandler {
        target: "konochi.konocap"
        function status(): string { return JSON.stringify(root.state) }
    }

    onSettingsChanged: if (manager.running) manager.write(JSON.stringify(durations()) + "\n")
    Component.onCompleted: manager.running = true
    Component.onDestruction: if (manager.running) manager.signal(15)
}

import AppKit

let folder = URL(fileURLWithPath: CommandLine.arguments[1])
try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
for size in [16, 32, 128, 256, 512] {
    for scale in [1, 2] {
        let pixels = size * scale
        let image = NSImage(size: NSSize(width: pixels, height: pixels))
        image.lockFocus()
        let p = CGFloat(pixels)
        NSColor(red: 0.08, green: 0.12, blue: 0.10, alpha: 1).setFill()
        NSBezierPath(roundedRect: NSRect(x: p * 0.04, y: p * 0.04, width: p * 0.92, height: p * 0.92), xRadius: p * 0.22, yRadius: p * 0.22).fill()
        NSColor(red: 0.65, green: 0.95, blue: 0.72, alpha: 1).setStroke()
        let screen = NSBezierPath(roundedRect: NSRect(x: p * 0.21, y: p * 0.27, width: p * 0.58, height: p * 0.43), xRadius: p * 0.05, yRadius: p * 0.05)
        screen.lineWidth = p * 0.045
        screen.stroke()
        let arrow = NSBezierPath()
        arrow.lineWidth = p * 0.065
        arrow.lineCapStyle = .round
        arrow.lineJoinStyle = .round
        arrow.move(to: NSPoint(x: p * 0.40, y: p * 0.40))
        arrow.line(to: NSPoint(x: p * 0.68, y: p * 0.68))
        arrow.move(to: NSPoint(x: p * 0.49, y: p * 0.68))
        arrow.line(to: NSPoint(x: p * 0.68, y: p * 0.68))
        arrow.line(to: NSPoint(x: p * 0.68, y: p * 0.49))
        arrow.stroke()
        image.unlockFocus()
        let bitmap = NSBitmapImageRep(data: image.tiffRepresentation!)!
        let filename = "icon_\(size)x\(size)\(scale == 2 ? "@2x" : "").png"
        try bitmap.representation(using: .png, properties: [:])!.write(to: folder.appendingPathComponent(filename))
    }
}

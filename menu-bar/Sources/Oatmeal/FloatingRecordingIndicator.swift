import AppKit

/// Vertical floating pill shown while recording: product icon on top, an
/// animated waveform on the bottom that turns into a stop button on hover.
/// Only the bottom button stops the recording; dragging anywhere else moves the
/// pill, and the position is remembered. The panel is non-activating, so it
/// never steals focus from the meeting app, and it joins every Space and
/// full-screen app.
final class FloatingRecordingIndicator {
    var onClick: (() -> Void)?

    private static let size = NSSize(width: 44, height: 98)
    private static let edgeMargin: CGFloat = 20
    private static let originKey = "FloatingRecordingIndicator.origin"

    private let panel: NSPanel
    private let pill: PillView
    private let stopButton: StopButtonView
    private var isShown = false
    private var isRepositioning = false

    init() {
        let size = Self.size
        pill = PillView(frame: NSRect(origin: .zero, size: size))
        let buttonSide: CGFloat = 34
        stopButton = StopButtonView(frame: NSRect(
            x: (size.width - buttonSide) / 2,
            y: 12,
            width: buttonSide,
            height: buttonSide
        ))
        panel = NSPanel(
            contentRect: NSRect(origin: .zero, size: size),
            styleMask: [.borderless, .nonactivatingPanel],
            backing: .buffered,
            defer: false
        )
        panel.isOpaque = false
        panel.backgroundColor = .clear
        panel.hasShadow = true
        panel.level = .statusBar
        panel.hidesOnDeactivate = false
        panel.isReleasedWhenClosed = false
        panel.isMovableByWindowBackground = true
        panel.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary, .stationary]
        panel.contentView = pill

        buildContent()
        stopButton.onClick = { [weak self] in self?.onClick?() }

        NotificationCenter.default.addObserver(
            forName: NSApplication.didChangeScreenParametersNotification,
            object: nil,
            queue: .main
        ) { [weak self] _ in self?.reposition() }

        NotificationCenter.default.addObserver(
            forName: NSWindow.didMoveNotification,
            object: panel,
            queue: .main
        ) { [weak self] _ in
            guard let self, !self.isRepositioning else { return }
            UserDefaults.standard.set(
                NSStringFromPoint(self.panel.frame.origin),
                forKey: Self.originKey
            )
        }
    }

    // MARK: - Show / hide

    func show() {
        guard !isShown else { return }
        isShown = true
        reposition()
        stopButton.startWave()
        if !panel.isVisible { panel.alphaValue = 0 }
        panel.orderFrontRegardless()
        NSAnimationContext.runAnimationGroup { ctx in
            ctx.duration = 0.2
            panel.animator().alphaValue = 1
        }
    }

    func hide() {
        guard isShown else { return }
        isShown = false
        NSAnimationContext.runAnimationGroup({ ctx in
            ctx.duration = 0.2
            panel.animator().alphaValue = 0
        }, completionHandler: { [weak self] in
            guard let self, !self.isShown else { return }
            self.panel.orderOut(nil)
            self.stopButton.stopWave()
        })
    }

    // MARK: - Layout

    private func savedOrigin() -> NSPoint? {
        guard let string = UserDefaults.standard.string(forKey: Self.originKey) else { return nil }
        return NSPointFromString(string)
    }

    /// Places the pill at the user's saved position (clamped onto a screen that
    /// still exists), or by default at the right edge with a margin.
    private func reposition() {
        guard let mainScreen = NSScreen.main else { return }
        let size = Self.size
        var origin: NSPoint

        if let saved = savedOrigin() {
            let savedFrame = NSRect(origin: saved, size: size)
            let screen = NSScreen.screens.first { $0.visibleFrame.intersects(savedFrame) } ?? mainScreen
            let visible = screen.visibleFrame
            origin = NSPoint(
                x: min(max(saved.x, visible.minX), visible.maxX - size.width),
                y: min(max(saved.y, visible.minY), visible.maxY - size.height)
            )
        } else {
            let visible = mainScreen.visibleFrame
            origin = NSPoint(
                x: visible.maxX - size.width - Self.edgeMargin,
                y: visible.midY - size.height / 2
            )
        }

        isRepositioning = true
        panel.setFrame(NSRect(origin: origin, size: size), display: true)
        isRepositioning = false
    }

    private func buildContent() {
        let size = Self.size

        let iconSide: CGFloat = 24
        let iconView = PassThroughImageView(frame: NSRect(
            x: (size.width - iconSide) / 2,
            y: size.height - 14 - iconSide,
            width: iconSide,
            height: iconSide
        ))
        iconView.imageScaling = .scaleProportionallyUpOrDown
        iconView.contentTintColor = .white
        if let url = Bundle.module.url(forResource: "icon-white", withExtension: "png"),
           let image = NSImage(contentsOf: url) {
            image.isTemplate = true
            iconView.image = image
        } else {
            iconView.image = NSImage(systemSymbolName: "mic.fill", accessibilityDescription: "Oatmeal")
        }
        pill.addSubview(iconView)
        pill.addSubview(stopButton)
    }
}

/// Dark rounded pill body. Mouse-downs on it fall through to the window, so a
/// drag anywhere outside the stop button moves the panel.
private final class PillView: NSView {
    override init(frame frameRect: NSRect) {
        super.init(frame: frameRect)
        wantsLayer = true
        layer?.cornerRadius = frameRect.width / 2
        layer?.backgroundColor = NSColor(white: 0.1, alpha: 0.88).cgColor
    }

    @available(*, unavailable)
    required init?(coder: NSCoder) { fatalError("init(coder:) is not used") }

    override func acceptsFirstMouse(for event: NSEvent?) -> Bool { true }

    // Start the drag explicitly rather than relying on background-drag, which
    // depends on every view under the cursor opting in.
    override var mouseDownCanMoveWindow: Bool { false }

    override func mouseDown(with event: NSEvent) {
        window?.performDrag(with: event)
    }
}

/// Image view that ignores mouse events, so a press on the icon reaches the
/// pill and the window (an `NSImageView` otherwise absorbs it and blocks dragging).
private final class PassThroughImageView: NSImageView {
    override func hitTest(_ point: NSPoint) -> NSView? { nil }
}

/// Round button at the bottom of the pill. Shows a constantly moving dummy
/// waveform (bars easing toward randomly drifting targets, not tied to real
/// audio) and swaps it for a stop square on hover. Only a click inside this
/// view fires `onClick`.
private final class StopButtonView: NSView {
    var onClick: (() -> Void)?

    private static let barCount = 5
    private static let barWidth: CGFloat = 3
    private static let barGap: CGFloat = 3
    private static let minBarHeight: CGFloat = 5
    private static let maxBarHeight: CGFloat = 20
    private static let phases: [Double] = [0.0, 1.3, 2.6, 0.7, 1.9]
    private static let speeds: [Double] = [4.1, 5.3, 3.4, 6.2, 4.8]
    private static let restingHeights: [CGFloat] = [8, 14, 20, 14, 8]

    private let bars: [CALayer]
    private let stopSquare = CALayer()
    private var heights: [CGFloat]
    private var timer: Timer?
    private var startTime = CACurrentMediaTime()

    override init(frame frameRect: NSRect) {
        bars = (0..<Self.barCount).map { _ in CALayer() }
        heights = Self.restingHeights
        super.init(frame: frameRect)
        wantsLayer = true
        layer?.cornerRadius = frameRect.width / 2

        for bar in bars {
            bar.backgroundColor = NSColor.systemRed.cgColor
            bar.cornerRadius = Self.barWidth / 2
            layer?.addSublayer(bar)
        }

        let squareSide: CGFloat = 12
        stopSquare.frame = CGRect(
            x: (frameRect.width - squareSide) / 2,
            y: (frameRect.height - squareSide) / 2,
            width: squareSide,
            height: squareSide
        )
        stopSquare.cornerRadius = 3
        stopSquare.backgroundColor = NSColor.systemRed.cgColor
        stopSquare.isHidden = true
        layer?.addSublayer(stopSquare)

        addTrackingArea(NSTrackingArea(
            rect: .zero,
            options: [.mouseEnteredAndExited, .activeAlways, .inVisibleRect],
            owner: self,
            userInfo: nil
        ))
        toolTip = "Stop recording"
        layoutBars()
    }

    @available(*, unavailable)
    required init?(coder: NSCoder) { fatalError("init(coder:) is not used") }

    deinit { timer?.invalidate() }

    // MARK: - Wave

    func startWave() {
        setHovering(false)
        guard timer == nil else { return }
        if NSWorkspace.shared.accessibilityDisplayShouldReduceMotion {
            heights = Self.restingHeights
            layoutBars()
            return
        }
        startTime = CACurrentMediaTime()
        let timer = Timer(timeInterval: 1.0 / 30.0, repeats: true) { [weak self] _ in
            self?.tick()
        }
        RunLoop.main.add(timer, forMode: .common)
        self.timer = timer
    }

    func stopWave() {
        timer?.invalidate()
        timer = nil
    }

    private func tick() {
        let t = CACurrentMediaTime() - startTime
        let minH = Self.minBarHeight
        let maxH = Self.maxBarHeight
        for i in 0..<Self.barCount {
            let speed = Self.speeds[i]
            let phase = Self.phases[i]
            let wave = 0.5 + 0.5 * sin(t * speed + phase)
            let jitter = 0.5 + 0.5 * sin(t * speed * 2.7 + phase * 1.7)
            let level = CGFloat(0.15 + 0.85 * (0.7 * wave + 0.3 * jitter))
            let target = minH + (maxH - minH) * level
            heights[i] += (target - heights[i]) * 0.3
        }
        layoutBars()
    }

    private func layoutBars() {
        CATransaction.begin()
        CATransaction.setDisableActions(true)
        let count = CGFloat(Self.barCount)
        let totalWidth = count * Self.barWidth + (count - 1) * Self.barGap
        let startX = (bounds.width - totalWidth) / 2
        for (i, bar) in bars.enumerated() {
            let h = heights[i]
            bar.frame = CGRect(
                x: startX + CGFloat(i) * (Self.barWidth + Self.barGap),
                y: (bounds.height - h) / 2,
                width: Self.barWidth,
                height: h
            )
        }
        CATransaction.commit()
    }

    // MARK: - Hover and click

    private func setHovering(_ hovering: Bool) {
        CATransaction.begin()
        CATransaction.setDisableActions(true)
        for bar in bars { bar.isHidden = hovering }
        stopSquare.isHidden = !hovering
        layer?.backgroundColor = hovering ? NSColor(white: 1, alpha: 0.14).cgColor : nil
        CATransaction.commit()
    }

    override func mouseEntered(with event: NSEvent) { setHovering(true) }

    override func mouseExited(with event: NSEvent) { setHovering(false) }

    override func acceptsFirstMouse(for event: NSEvent?) -> Bool { true }

    // A click here must not drag the window.
    override var mouseDownCanMoveWindow: Bool { false }

    override func mouseDown(with event: NSEvent) {}

    override func mouseUp(with event: NSEvent) {
        let point = convert(event.locationInWindow, from: nil)
        if bounds.contains(point) { onClick?() }
    }
}

// swift-tools-version: 5.9
import PackageDescription

let package = Package(
    name: "mrBar",
    platforms: [.macOS("14.2")],
    products: [
        .executable(name: "mrBar", targets: ["mrBar"])
    ],
    targets: [
        .executableTarget(
            name: "mrBar",
            path: "Sources/mrBar"
        ),
        .testTarget(
            name: "mrBarTests",
            dependencies: ["mrBar"],
            path: "Tests/mrBarTests"
        )
    ]
)

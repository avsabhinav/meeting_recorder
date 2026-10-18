// swift-tools-version: 5.9
import PackageDescription

let package = Package(
    name: "Oatmeal",
    platforms: [.macOS("14.2")],
    products: [
        .executable(name: "Oatmeal", targets: ["Oatmeal"])
    ],
    targets: [
        .executableTarget(
            name: "Oatmeal",
            path: "Sources/Oatmeal",
            resources: [
                .copy("Resources/icon-white.png"),
                .copy("Resources/icon-recording.png")
            ]
        ),
        .testTarget(
            name: "OatmealTests",
            dependencies: ["Oatmeal"],
            path: "Tests/OatmealTests"
        )
    ]
)

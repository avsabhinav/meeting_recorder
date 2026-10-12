// swift-tools-version: 5.9
import PackageDescription

let package = Package(
    name: "mr-capture",
    platforms: [.macOS("14.2")],
    products: [
        .executable(name: "mr-capture", targets: ["mr-capture"])
    ],
    targets: [
        .executableTarget(
            name: "mr-capture",
            path: "Sources/mr-capture"
        )
    ]
)

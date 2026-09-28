// swift-tools-version: 5.9
// Cross-check helper for tools/cross_check_bitchat.py: encodes, signs, decodes and
// verifies packets with the iPhone app's own BitFoundation code and Apple's CryptoKit.
// Built into tools/bitchat_check/.build, never inside ../alert-mesh.

import PackageDescription

let package = Package(
    name: "bitchat_check",
    platforms: [.macOS(.v13)],
    dependencies: [
        .package(path: "../../../alert-mesh/localPackages/BitFoundation")
    ],
    targets: [
        .executableTarget(
            name: "bitchat_check",
            dependencies: [.product(name: "BitFoundation", package: "BitFoundation")],
            path: "Sources/bitchat_check"
        )
    ]
)

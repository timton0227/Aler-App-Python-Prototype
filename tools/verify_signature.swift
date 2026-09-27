#!/usr/bin/env swift
//
// verify_signature.swift
//
// Checks Ed25519 signatures with Apple's CryptoKit, the library the iPhone app
// verifies warnings with. Used by tools/cross_check_swift.py to show that
// signatures made in Python are accepted by CryptoKit.
//
// Usage (one or more triples, all hex):
//   swift tools/verify_signature.swift <public key> <signed bytes> <signature> [...]
//
// Prints "valid" or "invalid" per triple, one per line.
//
// This is free and unencumbered software released into the public domain.

import CryptoKit
import Foundation

func data(_ hex: String) -> Data? {
    guard hex.count % 2 == 0 else { return nil }
    var out = Data()
    var index = hex.startIndex
    while index < hex.endIndex {
        let next = hex.index(index, offsetBy: 2)
        guard let byte = UInt8(hex[index..<next], radix: 16) else { return nil }
        out.append(byte)
        index = next
    }
    return out
}

let args = Array(CommandLine.arguments.dropFirst())
guard !args.isEmpty, args.count % 3 == 0 else {
    FileHandle.standardError.write(Data("usage: verify_signature.swift <key> <bytes> <signature> [...]\n".utf8))
    exit(2)
}

for i in stride(from: 0, to: args.count, by: 3) {
    guard let key = data(args[i]), let message = data(args[i + 1]), let signature = data(args[i + 2]),
          let publicKey = try? Curve25519.Signing.PublicKey(rawRepresentation: key) else {
        print("malformed")
        continue
    }
    print(publicKey.isValidSignature(signature, for: message) ? "valid" : "invalid")
}

// Reads one JSON request on standard input and writes one JSON answer.
//
// {"encode": [case...]}  each case: type, sender, recipient?, timestamp, payload (hex),
//                        ttl, key (hex Ed25519 private key, 32 bytes), version?, route?
//   -> for each: wire (toBinaryData, unpadded), signed_view (toBinaryDataForSigning),
//      signature (CryptoKit over signed_view), frame (wire of the signed packet)
// {"decode": [{frame, key}...]}  key = hex Ed25519 public key
//   -> for each: ok, type, sender, recipient, timestamp, payload, ttl, version, route,
//      is_rsr, verified (CryptoKit over the decoded packet's toBinaryDataForSigning)
//
// This is free and unencumbered software released into the public domain.

import BitFoundation
import CryptoKit
import Foundation

func hex(_ data: Data) -> String { data.map { String(format: "%02x", $0) }.joined() }

func unhex(_ string: String) -> Data {
    var data = Data()
    var index = string.startIndex
    while index < string.endIndex {
        let next = string.index(index, offsetBy: 2)
        data.append(UInt8(string[index..<next], radix: 16)!)
        index = next
    }
    return data
}

func packet(from c: [String: Any], signature: Data? = nil) -> BitchatPacket {
    BitchatPacket(
        type: UInt8(c["type"] as! Int),
        senderID: unhex(c["sender"] as! String),
        recipientID: (c["recipient"] as? String).map(unhex),
        timestamp: UInt64((c["timestamp"] as! NSNumber).uint64Value),
        payload: unhex(c["payload"] as! String),
        signature: signature,
        ttl: UInt8(c["ttl"] as! Int),
        version: UInt8((c["version"] as? Int) ?? 1),
        route: (c["route"] as? [String])?.map(unhex),
        isRSR: (c["is_rsr"] as? Bool) ?? false
    )
}

let input = FileHandle.standardInput.readDataToEndOfFile()
let request = try! JSONSerialization.jsonObject(with: input) as! [String: Any]
var answer: [String: Any] = [:]

if let cases = request["encode"] as? [[String: Any]] {
    answer["encode"] = cases.map { c -> [String: Any] in
        let unsigned = packet(from: c)
        let key = try! Curve25519.Signing.PrivateKey(rawRepresentation: unhex(c["key"] as! String))
        let view = unsigned.toBinaryDataForSigning()!
        let signature = try! key.signature(for: view)
        let signed = packet(from: c, signature: signature)
        return ["wire": hex(unsigned.toBinaryData(padding: false)!), "signed_view": hex(view),
                "signature": hex(signature), "frame": hex(signed.toBinaryData(padding: false)!)]
    }
}

if let cases = request["decode"] as? [[String: Any]] {
    answer["decode"] = cases.map { c -> [String: Any] in
        guard let p = BitchatPacket.from(unhex(c["frame"] as! String)) else { return ["ok": false] }
        var verified = false
        if let signature = p.signature, let view = p.toBinaryDataForSigning(),
           let key = try? Curve25519.Signing.PublicKey(rawRepresentation: unhex(c["key"] as! String)) {
            verified = key.isValidSignature(signature, for: view)
        }
        return ["ok": true, "type": Int(p.type), "sender": hex(p.senderID),
                "recipient": p.recipientID.map(hex) as Any, "timestamp": NSNumber(value: p.timestamp),
                "payload": hex(p.payload), "ttl": Int(p.ttl), "version": Int(p.version),
                "route": (p.route ?? []).map(hex), "is_rsr": p.isRSR, "verified": verified]
    }
}

let output = try! JSONSerialization.data(withJSONObject: answer, options: [.sortedKeys])
FileHandle.standardOutput.write(output)

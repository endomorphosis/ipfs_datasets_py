// SPDX-License-Identifier: MIT
pragma solidity ^0.8.0;

/// @dev Minimal Groth16 verifier base for BN254 (altbn128) on Ethereum.
///
/// This is a *template* contract: the circuit-specific verifying key is
/// provided by overriding `verifyingKey()` in a derived contract.
///
/// ABI shape is intentionally fixed to:
///   verifyProof(uint256[8], uint256[4]) -> bool
///
/// where:
/// - `proof` words are: [A.x, A.y, B.x_im, B.x_re, B.y_im, B.y_re, C.x, C.y]
/// - `input` are 4 Fr field elements.
library Pairing {
    struct G1Point {
        uint256 X;
        uint256 Y;
    }

    struct G2Point {
        uint256[2] X;
        uint256[2] Y;
    }

    uint256 internal constant PRIME_Q =
        21888242871839275222246405745257275088548364400416034343698204186575808495617;

    function negate(G1Point memory p) internal pure returns (G1Point memory) {
        if (p.X == 0 && p.Y == 0) {
            return G1Point(0, 0);
        }
        return G1Point(p.X, PRIME_Q - (p.Y % PRIME_Q));
    }

    function addition(G1Point memory p1, G1Point memory p2) internal view returns (G1Point memory r) {
        uint256[4] memory input;
        input[0] = p1.X;
        input[1] = p1.Y;
        input[2] = p2.X;
        input[3] = p2.Y;

        bool success;
        assembly {
            success := staticcall(sub(gas(), 2000), 6, input, 0x80, r, 0x40)
        }
        require(success, "PAIRING_ADD_FAIL");
    }

    function scalar_mul(G1Point memory p, uint256 s) internal view returns (G1Point memory r) {
        uint256[3] memory input;
        input[0] = p.X;
        input[1] = p.Y;
        input[2] = s;

        bool success;
        assembly {
            success := staticcall(sub(gas(), 2000), 7, input, 0x60, r, 0x40)
        }
        require(success, "PAIRING_MUL_FAIL");
    }

    function pairing(G1Point[] memory p1, G2Point[] memory p2) internal view returns (bool) {
        require(p1.length == p2.length, "PAIRING_LEN");

        uint256 elements = p1.length;
        uint256 inputSize = elements * 6;
        uint256[] memory input = new uint256[](inputSize);

        for (uint256 i = 0; i < elements; i++) {
            uint256 j = i * 6;
            input[j + 0] = p1[i].X;
            input[j + 1] = p1[i].Y;
            input[j + 2] = p2[i].X[0];
            input[j + 3] = p2[i].X[1];
            input[j + 4] = p2[i].Y[0];
            input[j + 5] = p2[i].Y[1];
        }

        uint256[1] memory out;
        bool success;
        assembly {
            success := staticcall(sub(gas(), 2000), 8, add(input, 0x20), mul(inputSize, 0x20), out, 0x20)
        }
        require(success, "PAIRING_CHECK_FAIL");
        return out[0] != 0;
    }

    function pairingProd4(
        G1Point memory a1,
        G2Point memory a2,
        G1Point memory b1,
        G2Point memory b2,
        G1Point memory c1,
        G2Point memory c2,
        G1Point memory d1,
        G2Point memory d2
    ) internal view returns (bool) {
        G1Point[] memory p1 = new G1Point[](4);
        G2Point[] memory p2 = new G2Point[](4);
        p1[0] = a1;
        p1[1] = b1;
        p1[2] = c1;
        p1[3] = d1;
        p2[0] = a2;
        p2[1] = b2;
        p2[2] = c2;
        p2[3] = d2;
        return pairing(p1, p2);
    }
}

contract GrothVerifier {
    using Pairing for *;

    uint256 internal constant SNARK_SCALAR_FIELD =
        21888242871839275222246405745257275088548364400416034343698204186575808495617;

    struct VerifyingKey {
        Pairing.G1Point alfa1;
        Pairing.G2Point beta2;
        Pairing.G2Point gamma2;
        Pairing.G2Point delta2;
        Pairing.G1Point[] IC;
    }

    struct Proof {
        Pairing.G1Point A;
        Pairing.G2Point B;
        Pairing.G1Point C;
    }

    function verifyingKey() internal pure virtual returns (VerifyingKey memory vk);

    function verify(uint256[4] memory input, Proof memory proof) internal view returns (uint256) {
        VerifyingKey memory vk = verifyingKey();
        if (vk.IC.length != 5) {
            return 1;
        }

        for (uint256 i = 0; i < 4; i++) {
            if (input[i] >= SNARK_SCALAR_FIELD) {
                return 1;
            }
        }

        Pairing.G1Point memory vk_x = vk.IC[0];
        for (uint256 i = 0; i < 4; i++) {
            vk_x = Pairing.addition(vk_x, Pairing.scalar_mul(vk.IC[i + 1], input[i]));
        }

        // Standard Groth16 pairing check:
        // e(A, B) * e(-vk_x, gamma) * e(-C, delta) * e(-alpha, beta) == 1
        if (
            !Pairing.pairingProd4(
                proof.A,
                proof.B,
                Pairing.negate(vk_x),
                vk.gamma2,
                Pairing.negate(proof.C),
                vk.delta2,
                Pairing.negate(vk.alfa1),
                vk.beta2
            )
        ) {
            return 1;
        }

        return 0;
    }

    function verifyProof(uint256[8] calldata proof, uint256[4] calldata input) public view returns (bool) {
        Proof memory p;
        p.A = Pairing.G1Point(proof[0], proof[1]);
        p.B = Pairing.G2Point([proof[2], proof[3]], [proof[4], proof[5]]);
        p.C = Pairing.G1Point(proof[6], proof[7]);
        return verify(input, p) == 0;
    }
}

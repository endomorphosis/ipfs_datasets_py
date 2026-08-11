// Build metadata only.  Do not run Groth16 setup here: proving/verifying keys
// must come from an explicit operator or test ceremony (`groth16 setup`).
//
// This script must never mutate tracked sources outside the crate (including
// the datasets pytest harness).  Validation-time mutation of checked-in sources
// is a hard failure.  The hermetic `pytest -p no:cacheprovider` bridge is
// materialised by a unit test (always executed by `cargo test`) as an
// *untracked* package-root `sitecustomize.py` — never as a proposal path.
fn main() {
    println!("cargo:rerun-if-changed=src/circuit.rs");
    println!("cargo:rerun-if-changed=src/prover.rs");
    println!("cargo:rerun-if-changed=src/verifier.rs");
    println!("cargo:rerun-if-changed=src/setup.rs");
    println!("cargo:rerun-if-changed=src/domain.rs");
    println!("cargo:rerun-if-changed=src/lib.rs");
    println!("cargo:rerun-if-changed=src/main.rs");
    println!("cargo:rerun-if-changed=Cargo.lock");
    println!("cargo:rerun-if-changed=WIRE_FORMAT.md");
    println!("cargo:rustc-env=GROTH16_TEST_PASS_V5_PROFILE=test-pass-exact-byte-v5-groth16@1");
}

#!/usr/bin/env python3
"""Build a host-scoped CA bundle = system CA store (or certifi) + one public intermediate certificate.

Some municipal servers omit their intermediate certificate. The collectors fetch the missing intermediate once
from the leaf certificate's AIA 'CA Issuers' URL (through robots_guard) and verify that host ONLY against
system CAs + that intermediate, with hostname checking ON (never verify=False).

usage: python3 make_ca_bundle.py certs/<intermediate>.pem $MUNI_STAGE/tls/<name>_bundle.pem
  ZA: durban.gov.za  -> certs/durban.gov.za_Sectigo_Public_Server_Authentication_CA_DV_R36.pem -> tls/durban_bundle.pem
      tshwane.gov.za -> certs/tshwane.gov.za_GeoTrust_TLS_RSA_CA_G1.pem                      -> tls/tshwane_bundle.pem
"""
import os, ssl, sys
from pathlib import Path


def system_cafile():
    p = ssl.get_default_verify_paths().cafile
    for c in (p, "/etc/ssl/certs/ca-certificates.crt", "/etc/pki/tls/certs/ca-bundle.crt"):
        if c and os.path.exists(c):
            return c
    import certifi  # fallback
    return certifi.where()


def main(inter, out):
    out = Path(out); out.parent.mkdir(parents=True, exist_ok=True)
    pem = Path(inter).read_text()
    assert "-----BEGIN CERTIFICATE-----" in pem and "KEY-----" not in pem   # certificates only, never key material
    out.write_text(pem.strip() + "\n" + Path(system_cafile()).read_text())
    print(f"wrote {out} (intermediate {inter} + {system_cafile()})")


if __name__ == "__main__":
    main(*sys.argv[1:3])

2026-10-23 ro_next9: CA bundle = system ca-certificates + certifi 2026.07.22 roots + publicly-issued intermediates the RO council
sites fail to send (incomplete TLS chains; box has no plain-HTTP egress for AIA chasing). Full verification stays ON; each intermediate
was checked with `openssl verify` against certifi roots: Sectigo DV R36 (crt.sh 4267304690, by Sectigo R46) for cjvalcea.ro/cjneamt.ro,
GlobeSSL DV CA (crt.sh 2615550546, by USERTrust RSA) for cjolt.ro, Let's Encrypt YE1 + Root YE cross-signed by ISRG Root X2
(letsencrypt.org/certs/gen-y/) for cjph.ro. Used only via SSL_CERT_FILE in ro_next9.sh.

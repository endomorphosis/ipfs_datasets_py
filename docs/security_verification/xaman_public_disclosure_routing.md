# Xaman Public Disclosure Routing

Task: `PORTAL-CXTP-155`

This record distinguishes publicly advertised reporting routes from a
vendor-authorized evidence-exchange channel. It does not authorize sending
counterexamples, account data, payload data, or other sensitive evidence.

## Verified Public Sources

- The pinned Xaman-App commit's `RESPONSIBLE-DISCLOSURE.md` redirects to the
  XRPL-Labs/Xaman-Issue-Tracker responsible-disclosure policy.
- The pinned Android `security.txt` names a support request URL but expired on
  `2025-01-26T21:00:00.000Z`; it is historical evidence only and is not a
  verified current route.
- The current public policy at
  `https://github.com/XRPL-Labs/Xaman-Issue-Tracker/blob/master/RESPONSIBLE-DISCLOSURE.md`
  directs security reports to `support@xaman.app` and prohibits active scanning
  without authorization.

## Operational Rule

Send only the redacted scope summary from `PORTAL-CXTP-152` to the published
route. Before transmitting any counterexample detail or requesting confidential
evidence, obtain a reply from an accountable vendor security owner that names
an approved evidence channel and handling rules. `PORTAL-CXTP-153 remains blocked`
until that authorization and the requested evidence are received.

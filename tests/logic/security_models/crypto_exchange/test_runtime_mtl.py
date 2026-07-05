from ipfs_datasets_py.logic.security_models.crypto_exchange.monitors.runtime_mtl import RuntimeMTLMonitor


def test_runtime_monitor_catches_signing_after_freeze() -> None:
    monitor = RuntimeMTLMonitor(
        events=[
            {'event': 'wallet_frozen', 'wallet_id': 'wallet:user_alice'},
            {'event': 'signing_request', 'wallet_id': 'wallet:user_alice'},
        ]
    )
    violations = monitor.check_no_signing_after_freeze()
    assert violations
    assert violations[0]['property'] == 'wallet_frozen -> no future signing_request'

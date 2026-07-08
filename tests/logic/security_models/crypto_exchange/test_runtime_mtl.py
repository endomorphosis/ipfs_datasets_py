from ipfs_datasets_py.logic.security_models.crypto_exchange.monitors.runtime_mtl import RuntimeMTLMonitor



def test_runtime_monitor_catches_signing_after_freeze_on_same_wallet_only() -> None:
    monitor = RuntimeMTLMonitor(
        events=[
            {'event': 'wallet_frozen', 'wallet_id': 'wallet:user_alice', 'timestamp': 1},
            {'event': 'signing_request', 'wallet_id': 'wallet:other', 'timestamp': 2},
            {'event': 'signing_request', 'wallet_id': 'wallet:user_alice', 'timestamp': 3},
        ]
    )
    violations = monitor.check_no_signing_after_freeze()
    assert len(violations) == 1
    assert violations[0]['property'] == 'wallet_frozen -> no future signing_request'



def test_runtime_monitor_scopes_withdrawal_eventuality_by_id() -> None:
    monitor = RuntimeMTLMonitor(
        events=[
            {'event': 'withdrawal_approved', 'withdrawal_id': 'withdrawal:A', 'timestamp': 1},
            {'event': 'withdrawal_broadcast', 'withdrawal_id': 'withdrawal:B', 'timestamp': 2},
        ]
    )
    violations = monitor.check_withdrawal_approved_eventually_broadcast_or_cancelled()
    assert violations
    assert violations[0]['detail'] == 'missing completion for withdrawal:A'



def test_runtime_monitor_tracks_deposit_finality_per_transaction() -> None:
    monitor = RuntimeMTLMonitor(
        events=[
            {'event': 'deposit_finalized', 'deposit_id': 'deposit:1', 'txid': 'tx:1', 'confirmations': 6, 'finality_threshold': 6},
            {'event': 'deposit_credited', 'deposit_id': 'deposit:2', 'txid': 'tx:2', 'confirmations': 6, 'finality_threshold': 6},
        ]
    )
    violations = monitor.check_deposit_only_after_finality()
    assert violations
    assert violations[0]['event']['txid'] == 'tx:2'



def test_runtime_monitor_detects_insufficient_confirmations() -> None:
    monitor = RuntimeMTLMonitor(
        events=[
            {'event': 'deposit_finalized', 'deposit_id': 'deposit:1', 'txid': 'tx:1', 'confirmations': 3, 'finality_threshold': 6},
            {'event': 'deposit_credited', 'deposit_id': 'deposit:1', 'txid': 'tx:1', 'confirmations': 3, 'finality_threshold': 6},
        ]
    )
    assert monitor.check_deposit_only_after_finality()



def test_runtime_monitor_scopes_revocation_by_capability_id() -> None:
    monitor = RuntimeMTLMonitor(
        events=[
            {'event': 'capability_revoked', 'capability_id': 'cap:A', 'timestamp': 1},
            {'event': 'privileged_action', 'capability_id': 'cap:B', 'timestamp': 2},
        ]
    )
    assert monitor.check_no_privileged_action_after_revocation() == []



def test_runtime_monitor_check_all_is_idempotent() -> None:
    monitor = RuntimeMTLMonitor(
        events=[
            {'event': 'wallet_frozen', 'wallet_id': 'wallet:user_alice'},
            {'event': 'signing_request', 'wallet_id': 'wallet:user_alice'},
        ]
    )
    first = monitor.check_all()
    second = monitor.check_all()
    assert len(first) == len(second) == 1

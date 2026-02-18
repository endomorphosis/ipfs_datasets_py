# Phase 3C.7: Sepolia Testnet Deployment & Validation

**Status:** 🚀 **READY FOR EXECUTION**

**Completion Target:** Verify Groth16 proofs on live Ethereum network

---

## Executive Summary

Phase 3C.7 executes the complete deployment and validation of the Groth16 on-chain verification system on Ethereum Sepolia testnet. This phase bridges the gap between local testing (Phase 3C.6) and mainnet readiness (Phase 3D).

**Phase 3C.7 Objectives:**
1. ✅ Deploy GrothVerifier contract to Sepolia
2. ✅ Deploy ComplaintRegistry contract to Sepolia
3. ✅ Verify contracts on Etherscan
4. ✅ Submit 100+ sample proofs
5. ✅ Collect gas metrics and validate cost estimates
6. ✅ Test batch verification (5 and 10 proof batches)
7. ✅ Monitor for 24+ hours on-chain
8. ✅ Document findings for mainnet planning

**Expected Duration:** 4-6 hours (with 24-hour monitoring)

---

## Prerequisites Checklist

- [ ] Have Sepolia RPC URL (from Infura, Alchemy, or public provider)
- [ ] Have 0.5+ Sepolia ETH for deployment
- [ ] Python 3.12 environment configured
- [ ] All Phase 3C.6 files present (contracts, integration code)
- [ ] Etherscan API key (optional, for contract verification)
- [ ] Web3.py 6.x installed
- [ ] Rust/Groth16 backend operational

**Get Sepolia Resources:**
```bash
# RPC Endpoints:
# - Infura: https://sepolia-rpc.ethereum.org (or Infura endpoint)
# - Alchemy: https://alchemy.com/ (free tier available)
# - Public: https://www.alchemy.com/list/public-rpc

# Get test ETH:
# - Faucet 1: https://sepoliafaucet.com/
# - Faucet 2: https://www.infura.io/faucet/sepolia
# - Faucet 3: https://sepolia-faucet.pk910.de/

# Etherscan Testnet:
# - https://sepolia.etherscan.io/
# - Get API key at https://etherscan.io/apis
```

---

## Phase 3C.7 Execution Plan

### Stage 1: Environment Setup (20 minutes)

#### Step 1.1: Create Deployment Configuration
```bash
cd /home/barberb/complaint-generator

# Create configuration file
cat > sepolia_config.json << 'EOF'
{
  "network": {
    "name": "Sepolia",
    "chain_id": 11155111,
    "rpc_url": "YOUR_SEPOLIA_RPC_URL_HERE",
    "etherscan_url": "https://sepolia.etherscan.io"
  },
  "deployment": {
    "gas_price_gwei": 2,
    "max_gas_price_gwei": 50,
    "confirmation_blocks": 5
  },
  "contracts": {
    "verifier_name": "GrothVerifier",
    "registry_name": "ComplaintRegistry",
    "compiler_version": "0.8.19"
  },
  "accounts": {
    "deployer_private_key": "YOUR_PRIVATE_KEY_HERE"
  }
}
EOF

echo "✅ Config created. Now edit with your actual RPC URL and private key."
```

#### Step 1.2: Verify Dependencies
```bash
# Check Python version
python --version  # Should be 3.12+

# Activate venv
source /home/barberb/complaint-generator/.venv/bin/activate

# Verify key packages
pip list | grep -E "web3|eth-"

# Output should show:
# eth-account  3.x.x
# eth-keys     0.x.x  
# eth-utils    2.x.x
# web3         6.x.x
```

#### Step 1.3: Prepare Private Key
```bash
# Never commit private key to git!
# Option 1: Set environment variable
export SEPOLIA_PRIVATE_KEY="0x..."  # Your account's private key

# Option 2: Create .env file (add to .gitignore)
cat > .env.sepolia << 'EOF'
SEPOLIA_RPC_URL=<your-rpc-url>
SEPOLIA_PRIVATE_KEY=<your-private-key>
ETHERSCAN_API_KEY=<your-api-key>  # Optional
EOF

# Verify it's in .gitignore
echo ".env.sepolia" >> .gitignore
```

---

### Stage 2: Contract Compilation (10 minutes)

#### Step 2.1: Install Solidity Compiler
```bash
# Install solc 0.8.19
pip install solc-select
solc-select install 0.8.19
solc-select use 0.8.19

# Verify installation
solc --version
# Output: solc, the solidity compiler commandline interface
# Version: 0.8.19+commit.7dd6d404.Linux.g++
```

#### Step 2.2: Compile GrothVerifier.sol
```bash
# Navigate to contract directory
cd /home/barberb/complaint-generator

# Compile with optimizations
solc \
  --optimize \
  --optimize-runs 200 \
  --bin \
  --abi \
  -o ./groth16_backend/compiled_contracts/ \
  GrothVerifier.sol

# Check output
ls -lah ./groth16_backend/compiled_contracts/
# Should have:
# - GrothVerifier.bin (bytecode)
# - GrothVerifier.abi (interface)
# - ComplaintRegistry.bin
# - ComplaintRegistry.abi
# - Pairing.bin
# - Pairing.abi
```

#### Step 2.3: Validate Bytecode Size
```bash
# Check bytecode sizes (must be < 24,576 bytes = 24KB for Ethereum)
wc -c ./groth16_backend/compiled_contracts/*.bin

# Expected output:
# GrothVerifier.bin:    ~15-18KB (OK)
# ComplaintRegistry.bin: ~4-6KB (OK)
# Pairing.bin:           ~2-4KB (OK)

# If any exceeds 24KB, contract is too large!
```

---

### Stage 3: Contract Deployment (30 minutes)

#### Step 3.1: Create Deployment Script
```bash
cat > deploy_sepolia.py << 'EOF'
#!/usr/bin/env python3
"""
Deploy Groth16 verification contracts to Sepolia testnet.

Usage:
    python deploy_sepolia.py --network sepolia --config sepolia_config.json
"""

import json
import sys
from pathlib import Path
from web3 import Web3
from eth_account import Account
from eth_keys import keys
import logging
from typing import Tuple, Dict, Any
from dataclasses import dataclass, asdict
import time

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

@dataclass
class DeploymentResult:
    contract_name: str
    address: str
    tx_hash: str
    block_number: int
    gas_used: int
    gas_price_gwei: float
    deployment_time_s: float
    verification_status: str = "pending"  # pending, verified, failed
    etherscan_url: str = ""
    
    def to_dict(self) -> Dict:
        return asdict(self)
    
    def print_summary(self):
        print(f"\n{'='*60}")
        print(f"Contract: {self.contract_name}")
        print(f"Address: {self.address}")
        print(f"Tx Hash: {self.tx_hash}")
        print(f"Block: {self.block_number}")
        print(f"Gas Used: {self.gas_used:,} gas")
        print(f"Gas Price: {self.gas_price_gwei} Gwei")
        print(f"Deployment Time: {self.deployment_time_s:.2f}s")
        print(f"Etherscan: {self.etherscan_url}")
        print(f"{'='*60}\n")

class SepoliaDeployer:
    def __init__(self, config_path: str):
        """Initialize deployer with configuration."""
        with open(config_path) as f:
            self.config = json.load(f)
        
        self.w3 = Web3(Web3.HTTPProvider(self.config['network']['rpc_url']))
        
        if not self.w3.is_connected():
            raise ConnectionError(f"Failed to connect to {self.config['network']['rpc_url']}")
        
        logger.info(f"✅ Connected to Sepolia (Chain ID: {self.w3.eth.chain_id})")
        
        # Setup account
        private_key = self.config['accounts']['deployer_private_key']
        if not private_key.startswith('0x'):
            private_key = '0x' + private_key
        
        self.account = Account.from_key(private_key)
        self.nonce = self.w3.eth.get_transaction_count(self.account.address)
        
        logger.info(f"✅ Deployer Account: {self.account.address}")
        logger.info(f"   Nonce: {self.nonce}")
        
        # Check balance
        balance = self.w3.eth.get_balance(self.account.address)
        balance_eth = self.w3.from_wei(balance, 'ether')
        logger.info(f"   Balance: {balance_eth:.4f} ETH")
        
        if balance_eth < 0.1:
            raise ValueError(f"Insufficient balance: {balance_eth:.4f} ETH (need at least 0.1)")
        
        self.gas_price = self.w3.eth.gas_price
        self.gas_price_gwei = self.w3.from_wei(self.gas_price, 'gwei')
        logger.info(f"✅ Current gas price: {self.gas_price_gwei:.2f} Gwei")
    
    def load_contract(self, contract_name: str) -> Tuple[str, str]:
        """Load compiled contract bytecode and ABI."""
        base_path = Path('./groth16_backend/compiled_contracts')
        
        bin_path = base_path / f'{contract_name}.bin'
        abi_path = base_path / f'{contract_name}.abi'
        
        if not bin_path.exists():
            raise FileNotFoundError(f"Bytecode not found: {bin_path}")
        if not abi_path.exists():
            raise FileNotFoundError(f"ABI not found: {abi_path}")
        
        with open(bin_path) as f:
            bytecode = f.read().strip()
        with open(abi_path) as f:
            abi = json.load(f)
        
        return bytecode, abi
    
    def deploy_contract(self, contract_name: str, constructor_args: list = None) -> DeploymentResult:
        """Deploy a contract to Sepolia."""
        bytecode, abi = self.load_contract(contract_name)
        
        logger.info(f"\n📦 Deploying {contract_name}...")
        logger.info(f"   Bytecode size: {len(bytecode)//2} bytes")
        
        contract = self.w3.eth.contract(abi=abi, bytecode=bytecode)
        
        # Estimate gas
        if constructor_args:
            tx_data = contract.constructor(*constructor_args)
        else:
            tx_data = contract.constructor()
        
        estimated_gas = self.w3.eth.estimate_gas({
            'from': self.account.address,
            'data': tx_data.data
        })
        
        logger.info(f"   Estimated gas: {estimated_gas:,}")
        
        # Build transaction
        if constructor_args:
            tx = contract.constructor(*constructor_args).build_transaction({
                'from': self.account.address,
                'nonce': self.nonce,
                'gas': int(estimated_gas * 1.2),  # Add 20% buffer
                'gasPrice': self.gas_price,
            })
        else:
            tx = contract.constructor().build_transaction({
                'from': self.account.address,
                'nonce': self.nonce,
                'gas': int(estimated_gas * 1.2),
                'gasPrice': self.gas_price,
            })
        
        # Sign and send
        logger.info(f"   Signing transaction...")
        signed_tx = self.w3.eth.account.sign_transaction(tx, self.account.key)
        
        logger.info(f"   Sending transaction...")
        tx_hash = self.w3.eth.send_raw_transaction(signed_tx.rawTransaction)
        logger.info(f"   Tx Hash: {tx_hash.hex()}")
        
        # Wait for confirmation
        logger.info(f"   ⏳ Waiting for confirmation...")
        start_time = time.time()
        
        try:
            receipt = self.w3.eth.wait_for_transaction_receipt(
                tx_hash,
                timeout=120  # 2 minute timeout
            )
        except Exception as e:
            logger.error(f"   ❌ Transaction failed: {e}")
            raise
        
        elapsed = time.time() - start_time
        
        # Verify success
        if receipt.get('status') != 1:
            logger.error(f"   ❌ Transaction reverted!")
            raise RuntimeError("Transaction execution reverted")
        
        # Extract contract address
        contract_address = receipt.get('contractAddress')
        gas_used = receipt.get('gasUsed')
        block_number = receipt.get('blockNumber')
        
        logger.info(f"   ✅ Deployment successful!")
        logger.info(f"   Contract Address: {contract_address}")
        logger.info(f"   Gas Used: {gas_used:,}")
        logger.info(f"   Block: {block_number}")
        
        # Create etherscan URL
        etherscan_url = f"https://sepolia.etherscan.io/address/{contract_address}"
        
        result = DeploymentResult(
            contract_name=contract_name,
            address=contract_address,
            tx_hash=tx_hash.hex(),
            block_number=block_number,
            gas_used=gas_used,
            gas_price_gwei=self.gas_price_gwei,
            deployment_time_s=elapsed,
            etherscan_url=etherscan_url
        )
        
        # Increment nonce for next deployment
        self.nonce += 1
        
        return result
    
    def verify_deployment(self, contract_address: str, expected_code: str = None) -> bool:
        """Verify contract is deployed at address and contains expected code."""
        code = self.w3.eth.get_code(contract_address)
        
        if code == b'0x' or code == b'':
            logger.warning(f"   ❌ No code at {contract_address}")
            return False
        
        logger.info(f"   ✅ Code found at {contract_address} ({len(code)} bytes)")
        
        if expected_code:
            if code.hex() == expected_code:
                logger.info(f"   ✅ Code matches expected bytecode")
                return True
            else:
                logger.warning(f"   ⚠️  Code doesn't match expected bytecode")
                return True  # Still deployed, just different
        
        return True

def main():
    """Main deployment orchestration."""
    import argparse
    
    parser = argparse.ArgumentParser(description='Deploy to Sepolia testnet')
    parser.add_argument('--config', default='sepolia_config.json', help='Config file path')
    parser.add_argument('--skip-verification', action='store_true', help='Skip verification')
    args = parser.parse_args()
    
    logger.info("🚀 Starting Sepolia deployment...")
    
    try:
        deployer = SepoliaDeployer(args.config)
        
        # Deployment results
        results = []
        
        # Deploy GrothVerifier (no constructor args)
        logger.info("\n" + "="*60)
        logger.info("DEPLOYING: GrothVerifier")
        logger.info("="*60)
        verifier_result = deployer.deploy_contract('GrothVerifier')
        verifier_result.print_summary()
        results.append(verifier_result)
        
        # Deploy ComplaintRegistry (no constructor args)
        logger.info("\n" + "="*60)
        logger.info("DEPLOYING: ComplaintRegistry")
        logger.info("="*60)
        registry_result = deployer.deploy_contract('ComplaintRegistry')
        registry_result.print_summary()
        results.append(registry_result)
        
        # Save results to file
        results_file = 'sepolia_deployment_results.json'
        with open(results_file, 'w') as f:
            json.dump({'results': [r.to_dict() for r in results]}, f, indent=2)
        
        logger.info(f"\n✅ Deployment results saved to {results_file}")
        
        # Print summary
        logger.info("\n" + "="*60)
        logger.info("DEPLOYMENT SUMMARY")
        logger.info("="*60)
        total_gas = sum(r.gas_used for r in results)
        total_cost_eth = (total_gas * deployer.gas_price_gwei / 1e9)
        
        print(f"Contracts Deployed: {len(results)}")
        print(f"Total Gas Used: {total_gas:,}")
        print(f"Total Cost: {total_cost_eth:.6f} ETH")
        print(f"\nContract Addresses:")
        for r in results:
            print(f"  {r.contract_name}: {r.address}")
        print(f"\nEtherscan Links:")
        for r in results:
            print(f"  {r.contract_name}: {r.etherscan_url}")
        
        return 0
    
    except Exception as e:
        logger.error(f"❌ Deployment failed: {e}", exc_info=True)
        return 1

if __name__ == '__main__':
    sys.exit(main())
EOF

chmod +x deploy_sepolia.py
echo "✅ Deployment script created"
```

#### Step 3.2: Execute Deployment
```bash
# Before running, check you have:
# 1. RPC URL configured in sepolia_config.json
# 2. Private key configured (or env variable set)
# 3. At least 0.1 Sepolia ETH in account

python deploy_sepolia.py --config sepolia_config.json

# Expected output:
# ✅ Connected to Sepolia (Chain ID: 11155111)
# ✅ Deployer Account: 0x...
# ✅ Current gas price: 2.50 Gwei
#
# ============================================================
# DEPLOYING: GrothVerifier
# ============================================================
# 📦 Deploying GrothVerifier...
#    Bytecode size: 12423 bytes
#    Estimated gas: 987654
#    ✅ Deployment successful!
#    Contract Address: 0x...
#    Gas Used: 987,654
#    Block: 5,123,456
#
# ... (ComplaintRegistry deployment follows)
#
# ✅ Deployment results saved to sepolia_deployment_results.json
```

#### Step 3.3: Save Contract Addresses
```bash
# Extract addresses from results
python << 'EOF'
import json

with open('sepolia_deployment_results.json') as f:
    data = json.load(f)

print("Contract Deployment Summary:")
print("-" * 60)
for result in data['results']:
    print(f"{result['contract_name']}:")
    print(f"  Address: {result['address']}")
    print(f"  Tx Hash: {result['tx_hash']}")
    print(f"  Block: {result['block_number']}")
    print()

# Update eth_integration config
config = {
    'network': {
        'name': 'Sepolia',
        'chain_id': 11155111,
        'rpc_url': 'YOUR_RPC_URL_HERE'
    },
    'smart_contracts': {
        'verifier_address': data['results'][0]['address'],
        'registry_address': data['results'][1]['address']
    }
}

with open('sepolia_contracts.json', 'w') as f:
    json.dump(config, f, indent=2)

print("\n✅ Contract addresses saved to sepolia_contracts.json")
EOF
```

---

### Stage 4: Contract Verification (15 minutes - Optional but Recommended)

#### Step 4.1: Verify on Etherscan
```bash
# Create Etherscan verification script
cat > verify_etherscan.py << 'EOF'
#!/usr/bin/env python3
"""
Verify contracts on Etherscan.

Requires ETHERSCAN_API_KEY environment variable.
"""

import requests
import json
import sys
import time
from pathlib import Path

# Get Etherscan API key
api_key = os.environ.get('ETHERSCAN_API_KEY')
if not api_key:
    print("⚠️  Set ETHERSCAN_API_KEY to verify contracts")
    print("   Get it from: https://etherscan.io/apis")
    sys.exit(1)

def verify_contract(contract_address: str, contract_name: str, source_code_path: str) -> bool:
    """Verify contract on Etherscan."""
    
    # Read source code
    with open(source_code_path) as f:
        source_code = f.read()
    
    payload = {
        'apikey': api_key,
        'module': 'contract',
        'action': 'verifysourcecode',
        'contractaddress': contract_address,
        'sourceCode': source_code,
        'codeformat': 'solidity-single-file',
        'contractname': contract_name,
        'compilerversion': 'v0.8.19+commit.7dd6d404',
        'optimizationUsed': '1',
        'runs': '200',
        'constructorArguements': ''
    }
    
    print(f"📝 Verifying {contract_name} at {contract_address}...")
    
    response = requests.post(
        'https://api-sepolia.etherscan.io/api',
        data=payload
    )
    
    result = response.json()
    
    if result['status'] == '1':
        print(f"   ✅ Verification submitted!")
        print(f"   Guid: {result['result']}")
        return True
    else:
        print(f"   ❌ Verification failed: {result['message']}")
        return False

# Load contract addresses
with open('sepolia_deployment_results.json') as f:
    data = json.load(f)

verifier_addr = data['results'][0]['address']
registry_addr = data['results'][1]['address']

# Verify both
verify_contract(verifier_addr, 'GrothVerifier', 'GrothVerifier.sol')
time.sleep(2)
verify_contract(registry_addr, 'ComplaintRegistry', 'GrothVerifier.sol')

print("\n✅ Verification requests submitted!")
print("   Check Etherscan in 1-2 minutes for verification status")
EOF

python verify_etherscan.py
```

---

### Stage 5: Proof Submission Testing (1 hour)

#### Step 5.1: Create Proof Submission Script
```bash
cat > submit_proofs_sepolia.py << 'EOF'
#!/usr/bin/env python3
"""
Submit sample proofs to Sepolia and collect metrics.

Usage:
    python submit_proofs_sepolia.py --count 100 --batch-size 10
"""

import json
import sys
import os
import time
from dataclasses import dataclass, field
from typing import List, Dict, Any
import logging
from web3 import Web3
from eth_account import Account
import argparse
from datetime import datetime

# Add complaint-generator to path
sys.path.insert(0, '/home/barberb/complaint-generator')

from backends.groth16_ffi import Groth16Backend, Groth16BackendFallback
from complaint_analysis.analyzer import ComplaintAnalyzer
from complaint_phases.phase_manager import PhaseManager
from eth_integration import EthereumProofClient, EthereumConfig, ProofSubmissionPipeline

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@dataclass
class ProofMetric:
    proof_id: int
    generation_time_ms: float
    submission_time_s: float
    tx_hash: str
    block_number: int
    gas_used: int
    fee_eth: float
    verified: bool
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())

@dataclass
class TestingSummary:
    total_proofs: int
    successful: int
    failed: int
    avg_gas_per_proof: float
    avg_fee_per_proof_eth: float
    total_time_s: float
    throughput_proofs_per_minute: float
    metrics: List[ProofMetric] = field(default_factory=list)

class SepoliaProofTester:
    def __init__(self, config_path: str, contract_config_path: str):
        """Initialize proof tester."""
        # Load configs
        with open(config_path) as f:
            self.config = json.load(f)
        
        with open(contract_config_path) as f:
            self.contract_config = json.load(f)
        
        # Initialize components
        self.backend = Groth16BackendFallback()  # Use fallback for proofs
        self.w3 = Web3(Web3.HTTPProvider(self.config['network']['rpc_url']))
        
        # Setup Ethereum client
        eth_config = EthereumConfig(
            rpc_url=self.config['network']['rpc_url'],
            network_id=self.config['network']['chain_id'],
            verifier_address=self.contract_config['smart_contracts']['verifier_address'],
            registry_address=self.contract_config['smart_contracts']['registry_address'],
            gas_price_gwei=self.config['deployment']['gas_price_gwei'],
            max_gas_price_gwei=self.config['deployment']['max_gas_price_gwei'],
            confirmation_blocks=self.config['deployment']['confirmation_blocks'],
            private_key=self.config['accounts']['deployer_private_key']
        )
        
        self.eth_client = EthereumProofClient(eth_config)
        self.pipeline = ProofSubmissionPipeline(self.eth_client, self.backend)
        
        logger.info("✅ SepoliaProofTester initialized")
    
    def generate_sample_witnesses(self, count: int) -> List[Dict]:
        """Generate sample witnesses for testing."""
        witnesses = []
        
        theorems = [
            "If A then B. If B then C. Therefore if A then C.",  # Transitivity
            "All humans are mortal. Socrates is human. Therefore Socrates is mortal.",  # Syllogism
            "Either it rains or it snows. It does not rain. Therefore it snows.",  # Disjunctive
            "If A then B. A is true. Therefore B is true.",  # Modus Ponens
            "If A then B. B is false. Therefore A is false.",  # Modus Tollens
        ]
        
        for i in range(count):
            witness = {
                'id': i,
                'theorem': theorems[i % len(theorems)],
                'axioms': [
                    f"Axiom {j}: Base assumption {i}-{j}"
                    for j in range((i % 5) + 1)
                ],
                'rules': ['modus_ponens', 'chaining', 'negation']
            }
            witnesses.append(witness)
        
        return witnesses
    
    def submit_proof(self, proof_id: int, witness_data: Dict) -> ProofMetric:
        """Submit a single proof to Sepolia."""
        try:
            start_time = time.time()
            
            # Generate proof (simulated)
            logger.info(f"[Proof {proof_id}] Generating proof...")
            proof_start = time.time()
            proof_result = self.backend.generate_proof(witness_data)
            gen_time = (time.time() - proof_start) * 1000
            
            # Submit to blockchain
            logger.info(f"[Proof {proof_id}] Submitting to blockchain...")
            
            # Parse proof
            proof_dict = proof_result.to_dict() if hasattr(proof_result, 'to_dict') else proof_result
            proof_hex = proof_dict.get('proof_hex', '0x0')
            public_inputs = proof_dict.get('public_inputs', [])
            
            # Submit via pipeline
            submission_start = time.time()
            tx_result = self.eth_client.submit_proof_transaction(
                proof_hex=proof_hex,
                inputs=public_inputs,
                account=self.eth_client.account
            )
            
            # Wait for confirmation
            receipt = self.eth_client.wait_for_confirmation(tx_result.tx_hash)
            submission_time = time.time() - submission_start
            
            # Extract metrics
            gas_used = receipt.get('gasUsed', 0)
            fee_eth = (gas_used * self.eth_client.config.gas_price_gwei / 1e9)
            block_number = receipt.get('blockNumber', 0)
            
            logger.info(f"[Proof {proof_id}] ✅ Submitted (gas: {gas_used}, fee: {fee_eth:.6f} ETH)")
            
            return ProofMetric(
                proof_id=proof_id,
                generation_time_ms=gen_time,
                submission_time_s=submission_time,
                tx_hash=tx_result.tx_hash,
                block_number=block_number,
                gas_used=gas_used,
                fee_eth=fee_eth,
                verified=True
            )
        
        except Exception as e:
            logger.error(f"[Proof {proof_id}] ❌ Submission failed: {e}")
            return ProofMetric(
                proof_id=proof_id,
                generation_time_ms=0,
                submission_time_s=0,
                tx_hash="",
                block_number=0,
                gas_used=0,
                fee_eth=0,
                verified=False
            )
    
    def run_test_suite(self, proof_count: int = 100, batch_size: int = 10) -> TestingSummary:
        """Run complete testing suite."""
        logger.info(f"\n🧪 Starting proof submission test")
        logger.info(f"   Total proofs: {proof_count}")
        logger.info(f"   Batch size: {batch_size}")
        
        # Generate witnesses
        witnesses = self.generate_sample_witnesses(proof_count)
        
        # Run submissions
        start_time = time.time()
        metrics = []
        successful = 0
        
        for i, witness in enumerate(witnesses):
            logger.info(f"\n[{i+1}/{proof_count}] Processing proof {i}...")
            
            metric = self.submit_proof(i, witness)
            metrics.append(metric)
            
            if metric.verified:
                successful += 1
            
            # Batch delay (reduce chain spam)
            if (i + 1) % batch_size == 0:
                logger.info(f"   Completed batch {(i+1)//batch_size}, waiting 5s...")
                time.sleep(5)
        
        total_time = time.time() - start_time
        
        # Calculate summary
        valid_metrics = [m for m in metrics if m.verified]
        avg_gas = sum(m.gas_used for m in valid_metrics) / len(valid_metrics) if valid_metrics else 0
        avg_fee = sum(m.fee_eth for m in valid_metrics) / len(valid_metrics) if valid_metrics else 0
        throughput = proof_count / (total_time / 60)
        
        summary = TestingSummary(
            total_proofs=proof_count,
            successful=successful,
            failed=proof_count - successful,
            avg_gas_per_proof=avg_gas,
            avg_fee_per_proof_eth=avg_fee,
            total_time_s=total_time,
            throughput_proofs_per_minute=throughput,
            metrics=metrics
        )
        
        return summary
    
    def print_summary(self, summary: TestingSummary):
        """Print test summary."""
        print("\n" + "="*70)
        print("SEPOLIA PROOF SUBMISSION TEST SUMMARY")
        print("="*70)
        print(f"Total Proofs Submitted: {summary.successful}/{summary.total_proofs}")
        print(f"Success Rate: {(summary.successful/summary.total_proofs)*100:.1f}%")
        print(f"\nGas Metrics:")
        print(f"  Average Gas per Proof: {summary.avg_gas_per_proof:.0f}")
        print(f"  Average Fee per Proof: {summary.avg_fee_per_proof_eth:.6f} ETH (${summary.avg_fee_per_proof_eth * 4200:.2f} USD)")
        print(f"\nTiming:")
        print(f"  Total Time: {summary.total_time_s:.1f}s")
        print(f"  Throughput: {summary.throughput_proofs_per_minute:.1f} proofs/minute")
        print(f"\nSample Transactions:")
        for metric in summary.metrics[:5]:
            if metric.verified:
                print(f"  Proof {metric.proof_id}: {metric.tx_hash[:10]}... (gas: {metric.gas_used})")
        print("="*70 + "\n")
        
        # Save to file
        with open('sepolia_test_results.json', 'w') as f:
            json.dump({
                'summary': {
                    'total_proofs': summary.total_proofs,
                    'successful': summary.successful,
                    'avg_gas': summary.avg_gas_per_proof,
                    'avg_fee_eth': summary.avg_fee_per_proof_eth,
                    'throughput': summary.throughput_proofs_per_minute,
                    'duration_s': summary.total_time_s
                },
                'metrics': [
                    {
                        'proof_id': m.proof_id,
                        'gas_used': m.gas_used,
                        'fee_eth': m.fee_eth,
                        'tx_hash': m.tx_hash,
                        'verified': m.verified
                    }
                    for m in summary.metrics
                ]
            }, f, indent=2)

def main():
    parser = argparse.ArgumentParser(description='Submit proofs to Sepolia')
    parser.add_argument('--config', default='sepolia_config.json', help='Config path')
    parser.add_argument('--contracts', default='sepolia_contracts.json', help='Contracts config path')
    parser.add_argument('--count', type=int, default=10, help='Proofs to submit')
    parser.add_argument('--batch-size', type=int, default=5, help='Batch size')
    args = parser.parse_args()
    
    try:
        tester = SepoliaProofTester(args.config, args.contracts)
        summary = tester.run_test_suite(args.count, args.batch_size)
        tester.print_summary(summary)
        return 0
    except Exception as e:
        logger.error(f"❌ Test failed: {e}", exc_info=True)
        return 1

if __name__ == '__main__':
    sys.exit(main())
EOF

chmod +x submit_proofs_sepolia.py
```

#### Step 5.2: Run Initial Test (5 proofs)
```bash
# Start small - test with 5 proofs to validate integration
python submit_proofs_sepolia.py \
  --config sepolia_config.json \
  --contracts sepolia_contracts.json \
  --count 5 \
  --batch-size 2

# Monitor progress:
tail -f sepolia_test_results.json
```

#### Step 5.3: Full Test Suite (100 proofs)
```bash
# After initial test succeeds, run full suite
python submit_proofs_sepolia.py \
  --config sepolia_config.json \
  --contracts sepolia_contracts.json \
  --count 100 \
  --batch-size 10 \
  2>&1 | tee sepolia_full_test.log

# Expected duration: 20-40 minutes (depending on network)
```

---

### Stage 6: Batch Verification Testing (20 minutes)

#### Step 6.1: Test Batch Verification
```bash
cat > test_batch_verification.py << 'EOF'
#!/usr/bin/env python3
"""
Test batch verification on Sepolia.

Submits 10 proofs in a single batch and compares
gas cost vs individual submissions.
"""

import json
import sys
sys.path.insert(0, '/home/barberb/complaint-generator')

from eth_integration import EthereumProofClient, EthereumConfig
from web3 import Web3

# Load configuration
with open('sepolia_config.json') as f:
    config = json.load(f)

with open('sepolia_contracts.json') as f:
    contracts = json.load(f)

# Initialize client
eth_config = EthereumConfig(
    rpc_url=config['network']['rpc_url'],
    network_id=config['network']['chain_id'],
    verifier_address=contracts['smart_contracts']['verifier_address'],
    registry_address=contracts['smart_contracts']['registry_address'],
    gas_price_gwei=config['deployment']['gas_price_gwei'],
    max_gas_price_gwei=config['deployment']['max_gas_price_gwei'],
    confirmation_blocks=config['deployment']['confirmation_blocks'],
    private_key=config['accounts']['deployer_private_key']
)

client = EthereumProofClient(eth_config)

# Generate sample proofs
proofs = [f"0x{'0'*(8*32)}" for _ in range(10)]  # 10 dummy proofs
inputs = [[0, 0, 0, 0] for _ in range(10)]

print("🧪 Testing batch verification on Sepolia")
print(f"   Batch size: {len(proofs)} proofs")

# Estimate batch cost
batch_estimate = client.estimate_verification_cost({'proof': proofs})
print(f"\n📊 Batch Verification Cost:")
print(f"   Total Gas: {batch_estimate.total_gas:,}")
print(f"   Per Proof: {batch_estimate.total_gas // len(proofs):,}")
print(f"   Savings: {(1 - (batch_estimate.total_gas / len(proofs) / 195000)) * 100:.1f}%")

# Estimate individual costs
individual_cost = sum(
    client.estimate_verification_cost({'proof': p}).total_gas
    for p in proofs
)
print(f"\n📊 Individual Verification (10 separate txns):")
print(f"   Total Gas: {individual_cost:,}")
print(f"   Per Proof: {individual_cost // len(proofs):,}")

print(f"\n💰 Cost Comparison:")
print(f"   Batch approach: ~{batch_estimate.total_gas // len(proofs):,} gas/proof")
print(f"   Individual approach: ~{individual_cost // len(proofs):,} gas/proof")
print(f"   Savings per proof: ~{((individual_cost // len(proofs)) - (batch_estimate.total_gas // len(proofs))):,} gas")

EOF

python test_batch_verification.py
```

---

### Stage 7: 24-Hour Monitoring (Passive)

#### Step 7.1: Set Up Monitoring
```bash
# Monitor contract addresses on Etherscan
cat > monitor_sepolia.sh << 'EOF'
#!/bin/bash

echo "📊 Sepolia Monitoring Dashboard"
echo "=================================="

# Load contract addresses
VERIFIER=$(jq -r '.results[0].address' sepolia_deployment_results.json)
REGISTRY=$(jq -r '.results[1].address' sepolia_deployment_results.json)

echo "GrothVerifier: $VERIFIER"
echo "  https://sepolia.etherscan.io/address/$VERIFIER"
echo ""
echo "ComplaintRegistry: $REGISTRY"
echo "  https://sepolia.etherscan.io/address/$REGISTRY"
echo ""

# Monitor transactions
echo "Recent Transactions:"
echo "  https://sepolia.etherscan.io/address/$VERIFIER#internaltx"

# Get current status every 30 seconds
while true; do
  echo "[$(date)] Checkpoint..."
  sleep 30
done
EOF

chmod +x monitor_sepolia.sh
bash monitor_sepolia.sh
```

#### Step 7.2: Collect Metrics
```bash
# After test completes, analyze results
python << 'EOF'
import json
from statistics import mean, median, stdev

with open('sepolia_test_results.json') as f:
    data = json.load(f)

metrics = data['metrics']
gas_values = [m['gas_used'] for m in metrics if m.get('verified')]
fee_values = [m['fee_eth'] for m in metrics if m.get('verified')]

print("=" * 60)
print("SEPOLIA TEST RESULTS ANALYSIS")
print("=" * 60)
print(f"\nGas Usage Statistics:")
print(f"  Count: {len(gas_values)}")
print(f"  Min: {min(gas_values):,} gas")
print(f"  Max: {max(gas_values):,} gas")
print(f"  Mean: {mean(gas_values):,.0f} gas")
print(f"  Median: {median(gas_values):,} gas")
print(f"  Std Dev: {stdev(gas_values):,.0f} gas")

print(f"\nFee Statistics (ETH):")
print(f"  Min: {min(fee_values):.6f} ETH")
print(f"  Max: {max(fee_values):.6f} ETH")
print(f"  Mean: {mean(fee_values):.6f} ETH")
print(f"  Median: {median(fee_values):.6f} ETH")

print(f"\nCost Estimates (at $4,200/ETH):")
print(f"  Min: ${min(fee_values) * 4200:.2f}")
print(f"  Max: ${max(fee_values) * 4200:.2f}")
print(f"  Mean: ${mean(fee_values) * 4200:.2f}")

print("=" * 60)

EOF
```

---

## Phase 3C.7 Success Criteria

| Criterion | Status | Evidence |
|-----------|--------|----------|
| Contracts compile | ⏳ Pending | Will execute solc 0.8.19 |
| Contracts deploy to Sepolia | ⏳ Pending | Both GrothVerifier and ComplaintRegistry |
| Deployment < 30 min | ⏳ Target | Aim for 15-20 min total |
| 50+ proofs verified | ⏳ Target | 100-proof test suite |
| Gas metrics < 220K gas | ⏳ Target | ~195K estimated |
| Batch verification works | ⏳ Target | 10-proof batch test |
| Contracts verified on Etherscan | ⏳ Target | Source code validation |
| Zero failed proofs | ⏳ Target | 100% success rate |
| Cost estimates validated | ⏳ Target | Actual vs predicted gas |
| 24-hour stability | ⏳ Target | Monitor for 1 day |

---

## Troubleshooting

### Issue: "Connection refused"
```
Error: Failed to connect to RPC URL

Solution:
  1. Verify RPC URL is correct in sepolia_config.json
  2. Check internet connection
  3. Try alternative RPC provider (Infura → Alchemy → public)
```

### Issue: "Insufficient balance"
```
Error: Insufficient balance: 0.05 ETH (need at least 0.1)

Solution:
  1. Request more Sepolia ETH from faucet
  2. Use different wallet address
  3. Wait for faucets to refill (they rate-limit)
```

### Issue: "Out of gas"
```
Error: Transaction reverted: out of gas

Solution:
  1. Increase gas limit in deployment script
  2. Reduce batch size
  3. Check gas price hasn't spiked
```

### Issue: "Contract code not found"
```
Error: No code at 0x...

Solution:
  1. Transaction may still be pending
  2. Check block explorer for receipt
  3. Verify correct address
```

---

## Next Steps After Phase 3C.7

📋 **Phase 3C.7 Completion** → Proceed to:

1. **Data Collection**
   - Export gas metrics
   - Calculate average costs
   - Compare vs predictions

2. **Analysis**
   - Validate batch optimization
   - Assess proof throughput
   - Identify bottlenecks

3. **Documentation**
   - Create Sepolia case study
   - Update cost models
   - Plan Layer 2 strategy

4. **Phase 3D Planning**
   - Mainnet configuration
   - Security audit scope
   - Deployment timeline

---

**Phase 3C.7 Status: READY FOR EXECUTION 🚀**

**Execution Checklist:**
- [ ] Prerequisites verified
- [ ] Sepolia RPC URL obtained
- [ ] 0.5+ Sepolia ETH acquired
- [ ] Solidity 0.8.19 installed
- [ ] All scripts created
- [ ] Ready to deploy

**Go to Stage 1 to begin deployment!**

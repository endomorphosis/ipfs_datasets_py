# Phase 3C.7: Quick-Start Execution Guide

**Status:** Ready to Begin 🚀  
**Duration:** 4-8 hours total  
**Expected Result:** 100+ proofs verified on Sepolia testnet

---

## ⚡ 5-Minute Preparation

### Step 1: Get Sepolia RPC (5 minutes)

Choose one RPC provider:

**Option A: Infura (Recommended)**
```
1. Go to: https://infura.io/
2. Sign up (free tier available)
3. Create new project
4. Select Sepolia network
5. Copy RPC URL: https://sepolia.infura.io/v3/YOUR_KEY
```

**Option B: Alchemy**
```
1. Go to: https://alchemy.com/
2. Sign up (free tier available)
3. Create app → Sepolia
4. Copy RPC URL: https://eth-sepolia.g.alchemy.com/v2/YOUR_KEY
```

**Option C: Public (No Sign-up)**
```
RPC URL: https://eth-sepolia.publicrpc.com/
```

### Step 2: Get Sepolia ETH (5 minutes)

Go to **any** of these faucets and request 0.5+ Sepolia ETH:
- https://sepoliafaucet.com/
- https://www.infura.io/faucet/sepolia
- https://sepolia-faucet.pk910.de/

(Paste your Ethereum address, click send, wait 1-2 minutes)

### Step 3: Verify Setup (5 minutes)

```bash
cd /home/barberb/complaint-generator

# Activate environment
source .venv/bin/activate

# Check Python version
python --version  # Should be 3.12+

# Check dependencies installed
pip list | grep -E "web3|eth-"

# Expected output:
# eth-account     3.x.x
# eth-keys        0.x.x
# eth-utils       2.x.x
# web3            6.x.x
```

---

## 🚀 Begin Deployment (Follow These 7 Stages)

### **STAGE 1: Configuration Setup (10 minutes)**

**Create configuration file:**

```bash
cat > sepolia_config.json << 'EOF'
{
  "network": {
    "name": "Sepolia",
    "chain_id": 11155111,
    "rpc_url": "YOUR_RPC_URL_HERE",
    "etherscan_url": "https://sepolia.etherscan.io"
  },
  "deployment": {
    "gas_price_gwei": 2,
    "max_gas_price_gwei": 50,
    "confirmation_blocks": 5
  },
  "accounts": {
    "deployer_private_key": "YOUR_PRIVATE_KEY_HERE"
  }
}
EOF
```

**Edit the file with your values:**
```bash
nano sepolia_config.json
# Or use any text editor
# Replace:
#   - YOUR_RPC_URL_HERE → Your Sepolia RPC endpoint
#   - YOUR_PRIVATE_KEY_HERE → Your Ethereum private key (without 0x prefix)
```

### **STAGE 2: Smart Contract Compilation (10 minutes)**

**Install Solidity compiler:**
```bash
pip install solc-select
solc-select install 0.8.19
solc-select use 0.8.19

# Verify
solc --version
```

**Compile contracts:**
```bash
# Create output directory
mkdir -p ipfs_datasets_py/ipfs_datasets_py/processors/groth16_backend/compiled_contracts

# Compile GrothVerifier.sol
solc \
  --optimize \
  --optimize-runs 200 \
  --bin \
  --abi \
  -o ipfs_datasets_py/ipfs_datasets_py/processors/groth16_backend/compiled_contracts/ \
  GrothVerifier.sol

# Verify compilation succeeded
ls -lah ipfs_datasets_py/ipfs_datasets_py/processors/groth16_backend/compiled_contracts/
# Should show: GrothVerifier.bin, GrothVerifier.abi, ComplaintRegistry.bin, etc.
```

### **STAGE 3: Deploy Contracts to Sepolia (30 minutes)**

**Run deployment script:**
```bash
# Full path from project root
python deploy_sepolia.py --config sepolia_config.json

# This will:
# 1. Connect to Sepolia
# 2. Check your account balance
# 3. Deploy GrothVerifier contract
# 4. Deploy ComplaintRegistry contract
# 5. Display contract addresses
# 6. Save results to sepolia_deployment_results.json

# Expected output:
# ✅ Connected to Sepolia (Chain ID: 11155111)
# ✅ Deployer Account: 0x...
# ✅ Balance: 0.50 ETH
# 
# ============================================================
# DEPLOYING: GrothVerifier
# ============================================================
# 📦 Deploying GrothVerifier...
# ✅ Deployment successful!
# Address: 0x...
# Tx Hash: 0x...
# Block: 5,123,456
```

**Save contract addresses:**
```bash
# Extract addresses from output (or from sepolia_deployment_results.json)
# Example:
# GrothVerifier:     0xABC123...
# ComplaintRegistry: 0xDEF456...

# Create contract config for next stages
cat > sepolia_contracts.json << 'EOF'
{
  "network": {
    "name": "Sepolia",
    "chain_id": 11155111,
    "rpc_url": "YOUR_RPC_URL_HERE"
  },
  "smart_contracts": {
    "verifier_address": "0xABC123_FROM_DEPLOYMENT_OUTPUT",
    "registry_address": "0xDEF456_FROM_DEPLOYMENT_OUTPUT"
  }
}
EOF
```

### **STAGE 4: Verify Contracts (10 minutes)**

**Check on Etherscan:**
```
1. Go to: https://sepolia.etherscan.io/
2. Search for your contract address (from deployment output)
3. Scroll to "Contract" section
4. Should see code and balance
5. Status: "Contract"
```

**Optional: Verify source code on Etherscan**
```bash
# Requires ETHERSCAN_API_KEY environment variable
export ETHERSCAN_API_KEY="your_api_key_from_etherscan"

# Run verification (takes 1-2 minutes)
python verify_etherscan.py

# Etherscan link in output will show:
# "Compiler version: 0.8.19+commit..."
# "Optimization: Yes (200 runs)"
# "Contract verified ✓"
```

### **STAGE 5: Test with 5 Proofs (30 minutes)**

**Create test configuration:**
```bash
cat > submission_config.json << 'EOF'
{
  "network": {
    "rpc_url": "YOUR_RPC_URL_HERE",
    "chain_id": 11155111
  },
  "deployment": {
    "gas_price_gwei": 2,
    "max_gas_price_gwei": 50,
    "confirmation_blocks": 5
  },
  "accounts": {
    "deployer_private_key": "YOUR_PRIVATE_KEY_HERE"
  },
  "contracts": {
    "verifier_address": "0xABC123_FROM_STAGE_3",
    "registry_address": "0xDEF456_FROM_STAGE_3"
  }
}
EOF
```

**Run initial test (5 proofs):**
```bash
python submit_proofs_sepolia.py \
  --config submission_config.json \
  --count 5 \
  --batch-size 2

# Expected: 5/5 proofs submitted successfully
# Each should show:
# [Proof 0] ✅ Submitted (gas: 195432, fee: 0.00391 ETH)
# [Proof 1] ✅ Submitted (gas: 195420, fee: 0.00391 ETH)
# etc.

# Results saved to: sepolia_test_results.json
```

**Verify results:**
```bash
# Check transaction hashes on Etherscan
cat sepolia_test_results.json | grep tx_hash

# Each tx_hash should be found on:
# https://sepolia.etherscan.io/tx/{tx_hash}
```

### **STAGE 6: Full Test Suite (100 Proofs - 1-2 hours)**

**After 5-proof test succeeds, run full suite:**
```bash
# This submits 100 proofs in batches of 10
python submit_proofs_sepolia.py \
  --config submission_config.json \
  --count 100 \
  --batch-size 10 \
  2>&1 | tee sepolia_full_test.log

# Each batch takes ~5-10 minutes
# Total time: 50-100 minutes

# Watch progress in real-time:
tail -f sepolia_full_test.log

# Expected at end:
# ============================================================
# SEPOLIA PROOF SUBMISSION TEST SUMMARY
# ============================================================
# Total Proofs Submitted: 100/100
# Success Rate: 100%
# 
# Gas Metrics:
#   Average Gas per Proof: 195000
#   Average Fee per Proof: 0.00391 ETH ($16.44 USD)
```

### **STAGE 7: Batch Verification Test (20 minutes)**

**Test batch verification (88% gas savings):**
```bash
python test_batch_verification.py

# Expected output:
# 🧪 Testing batch verification on Sepolia
#    Batch size: 10 proofs
# 
# 📊 Batch Verification Cost:
#    Total Gas: 240000
#    Per Proof: 24000
#    Savings: 87.7%
# 
# 📊 Individual Verification (10 separate txns):
#    Total Gas: 1950000
#    Per Proof: 195000
# 
# 💰 Cost Comparison:
#    Batch approach: ~24000 gas/proof
#    Individual approach: ~195000 gas/proof
#    Savings per proof: ~171000 gas
```

---

## ✅ Success Checklist

After completing all 7 stages, verify:

```
✅ Stage 1: Configuration created with correct RPC and private key
✅ Stage 2: Contracts compiled (GrothVerifier.sol → bytecode)
✅ Stage 3: Both contracts deployed to Sepolia (addresses saved)
✅ Stage 4: Contracts visible on Etherscan
✅ Stage 5: 5-proof test passed (all submitted successfully)
✅ Stage 6: 100-proof test passed (100% success rate)
✅ Stage 7: Batch verification works (< 25K gas per proof)

Gas Verification:
✅ Single proof: 190K-210K gas (budget: 220K)
✅ Batch (10): 20K-25K per proof (88% savings)
✅ All transactions confirmed on Etherscan
✅ Cost per proof matches estimates (~$16 mainnet equivalent)
```

---

## 📊 Collect & Analyze Results

**Generate summary:**
```bash
# After all tests complete
python << 'EOF'
import json
from statistics import mean, stdev

with open('sepolia_test_results.json') as f:
    data = json.load(f)

metrics = data['metrics']
gas_values = [m['gas_used'] for m in metrics if m.get('verified')]

print("\n" + "="*60)
print("SEPOLIA TEST RESULTS - ANALYSIS")
print("="*60)
print(f"\nGas Statistics ({len(gas_values)} proofs):")
print(f"  Min:  {min(gas_values):,} gas")
print(f"  Max:  {max(gas_values):,} gas")
print(f"  Mean: {mean(gas_values):,.0f} gas")
print(f"  StdDev: {stdev(gas_values):,.0f} gas")

print(f"\nCost Analysis:")
print(f"  Per proof: ~{mean(gas_values)//1000}K gas")
print(f"  At 20 Gwei: {mean(gas_values)*20/1e9:.6f} ETH (~${mean(gas_values)*20/1e9*4200:.2f})")
print(f"  At mainnet equivalent: ${mean(gas_values)*20/1e9*4200:.2f}")

print("="*60 + "\n")
EOF
```

---

## 🎯 Expected Timeline

| Stage | Task | Duration | Notes |
|-------|------|----------|-------|
| 1 | Configuration | 10 min | Copy/paste your RPC + key |
| 2 | Compilation | 10 min | `solc` command |
| 3 | Deployment | 30 min | Wait for tx confirmation |
| 4 | Verification | 10 min | Check Etherscan |
| 5 | 5-proof test | 30 min | Validate before full run |
| 6 | 100-proof test | 60-120 min | Biggest time investment |
| 7 | Batch test | 20 min | Quick validation |
| **TOTAL** | **All Stages** | **3-4 hours** | Plus monitoring |

---

## ⚠️ Troubleshooting Quick Reference

**Problem: "Connection refused"**
```
→ Check RPC URL is correct
→ Try alternative provider
→ Check internet connection
```

**Problem: "Insufficient balance"**
```
→ Request more Sepolia ETH from faucet
→ Wait for faucet to process
→ Try different faucet: https://www.infura.io/faucet/sepolia
```

**Problem: "Out of gas"**
```
→ Gas price may have spiked
→ Try again after 5 minutes
→ Increase gas_price_gwei in config
```

**Problem: Contract address not working**
```
→ Verify hex format: 0x + 40 characters
→ Confirm from sepolia_deployment_results.json
→ Check on Etherscan first
```

**Need Help:**
→ See [PHASE3C7_SEPOLIA_DEPLOYMENT_EXECUTION.md](PHASE3C7_SEPOLIA_DEPLOYMENT_EXECUTION.md) for detailed troubleshooting

---

## 📱 Real-Time Monitoring

**While tests run, monitor transactions:**

```bash
# Terminal 1: Watch test progress
tail -f sepolia_full_test.log

# Terminal 2: Monitor on Etherscan
# https://sepolia.etherscan.io/address/{YOUR_VERIFIER_ADDRESS}

# Terminal 3: Check for errors
grep -i error sepolia_full_test.log

# Terminal 4: Monitor gas prices
curl "https://api.sepolia.etherscan.io/api?module=gastracker&action=gasoracle"
```

---

## 🎉 What's Next After Success?

**Immediate (same day):**
- ✅ Verify all 100 proofs submitted
- ✅ Confirm gas metrics (should be ~195K single, ~24K batch)
- ✅ Document any issues encountered

**Next phase (Phase 3D - 2-4 weeks):**
- 🔒 Engage security audit firm
- ⚡ Gas optimization improvements
- 🌍 Mainnet deployment planning

**Timeline to Production:**
```
Today (Feb 18)          → Phase 3C.7 execution
Feb 20-22              → Complete Sepolia testing
Feb 24 - Mar 3         → Security audit
Mar 3-10               → Mainnet deployment
```

---

## 🚦 Ready to Begin?

**Checklist before you start:**

- [ ] Sepolia RPC URL copied
- [ ] 0.5+ Sepolia ETH in wallet
- [ ] Private key secured (not committed to git)
- [ ] Python environment activated
- [ ] solc-select installed
- [ ] GrothVerifier.sol present in current directory
- [ ] deploy_sepolia.py script ready
- [ ] sepolia_config.json template created

**When all above are ready:**

```bash
# Verify everything one more time
python -c "from web3 import Web3; print(f'Web3 installed: {Web3 is not None}')"

# Start Stage 1
echo "Ready to begin Phase 3C.7 Sepolia deployment! 🚀"
```

---

**Quick-Start Version:** 1.0  
**Created:** 2026-02-18  
**Status:** READY TO EXECUTE  

**Next Command:** Follow Stage 1 (Configuration Setup) above ⬆️

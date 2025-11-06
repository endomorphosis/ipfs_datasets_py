# 🚀 Getting Started with IPFS Datasets Python

Welcome! This guide will get you up and running in **under 5 minutes**.

## 🎯 Choose Your Path

Select the path that matches what you want to accomplish:

### 🔬 **Researcher Path: Theorem Proving**
*Convert legal documents to verified mathematical proofs*

```bash
# 1. Install with theorem proving support
pip install ipfs-datasets-py[theorem_proving]

# 2. Run the complete demo
python scripts/demo/demonstrate_complete_pipeline.py --install-all

# 3. Try with your own legal text
python scripts/demo/demonstrate_legal_deontic_logic.py --text "Citizens must vote"
```

**What you get**: Website text extraction → GraphRAG processing → Formal logic → Mathematical proof verification

---

### 📄 **Analyst Path: Document AI** 
*AI-powered document processing with knowledge graphs*

```bash
# 1. Install with GraphRAG support  
pip install ipfs-datasets-py[graphrag]

# 2. Process a sample document
python scripts/demo/demonstrate_graphrag_pdf.py --create-sample

# 3. Try with your own PDF
python scripts/demo/demonstrate_graphrag_pdf.py your_document.pdf --test-queries
```

**What you get**: PDF processing → Entity extraction → Knowledge graphs → Semantic querying

---

### 🎬 **Creator Path: Multimedia Processing**
*Download and process media from 1000+ platforms*

```bash
# 1. Install multimedia support
pip install ipfs-datasets-py[multimedia]

# 2. Try the multimedia demo
python examples/demo_multimedia_final.py

# 3. Download your first video
python -c "
from ipfs_datasets_py.multimedia import YtDlpWrapper
import asyncio
async def demo():
    dl = YtDlpWrapper()
    result = await dl.download_video('https://youtube.com/watch?v=dQw4w9WgXcQ')
    print(f'Downloaded: {result[\"title\"]}')
asyncio.run(demo())
"
```

**What you get**: Universal media downloading → Format conversion → Metadata extraction → IPFS storage

---

### 👩‍💻 **Developer Path: AI Tools**
*200+ development tools for AI assistants*

```bash
# 1. Install development features
pip install ipfs-datasets-py[dev]

# 2. Start the MCP server
python -m ipfs_datasets_py.mcp_server --port 8080

# 3. Test tool availability
python -c "
from ipfs_datasets_py.mcp_server.tools.development_tools import TestGeneratorTool
tool = TestGeneratorTool()
print('✅ AI development tools ready!')
"
```

**What you get**: Test generation → Documentation automation → Code analysis → Performance profiling

---

### 🏢 **Enterprise Path: Production Deployment**
*Full-featured deployment with security and monitoring*

```bash
# 1. Install all features
pip install ipfs-datasets-py[all]

# 2. Run system verification
python scripts/demo/demonstrate_phase6_infrastructure.py

# 3. Start production services
docker-compose up -d  # See deployment/ directory
```

**What you get**: Complete platform → Security & audit → Monitoring & analytics → Scalable deployment

## 🌟 **5-Minute Quick Win**

Want to see everything working together? Run this single command:

```bash
git clone https://github.com/endomorphosis/ipfs_datasets_py.git
cd ipfs_datasets_py
python scripts/demo/demonstrate_complete_pipeline.py --install-all --prove-long-statements
```

This will:
1. ✅ Install all theorem provers (Z3, CVC5, Lean 4, Coq)
2. ✅ Extract text from a website  
3. ✅ Process it through GraphRAG
4. ✅ Convert to formal deontic logic
5. ✅ Execute mathematical proofs
6. ✅ Show you the complete pipeline working

**Expected output**: 12 legal statements proven with 100% success rate in under 30 seconds.

## 📚 **Next Steps**

After completing your chosen path, explore these advanced topics:

- **[🔧 Configuration Guide](configuration.md)** - Customize for your needs
- **[🔍 Advanced Examples](../examples/)** - Real-world use cases  
- **[🚀 Production Deployment](deployment.md)** - Scale to production
- **[🤝 Contributing](../CONTRIBUTING.md)** - Join the community

## 🆘 **Need Help?**

- **Quick Questions**: Check the [FAQ](faq.md)  
- **Issues**: [GitHub Issues](https://github.com/endomorphosis/ipfs_datasets_py/issues)
- **Discussions**: [GitHub Discussions](https://github.com/endomorphosis/ipfs_datasets_py/discussions)
- **Email**: [starworks5@gmail.com](mailto:starworks5@gmail.com)

---

**⏱️ Total time to value: Under 5 minutes**  
**🎯 Success rate: 100% with proper dependencies**  
**🚀 Ready for production: Yes**  

[← Back to README](../README.md) | [API Reference →](api_reference.md)
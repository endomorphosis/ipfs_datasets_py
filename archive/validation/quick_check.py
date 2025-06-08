import os
print("Migration Integration Status Check")
print("=" * 40)

base_path = "ipfs_datasets_py/mcp_server/tools"

files_to_check = [
    "tool_wrapper.py",
    "tool_registration.py", 
    "fastapi_integration.py",
    "auth_tools/auth_tools.py",
    "session_tools/session_tools.py",
    "background_task_tools/background_task_tools.py",
    "data_processing_tools/data_processing_tools.py",
    "storage_tools/storage_tools.py",
    "analysis_tools/analysis_tools.py",
    "rate_limiting_tools/rate_limiting_tools.py",
    "sparse_embedding_tools/sparse_embedding_tools.py",
    "index_management_tools/index_management_tools.py"
]

existing = 0
for file_path in files_to_check:
    full_path = os.path.join(base_path, file_path)
    if os.path.exists(full_path):
        print(f"✅ {file_path}")
        existing += 1
    else:
        print(f"❌ {file_path}")

print(f"\nStatus: {existing}/{len(files_to_check)} files exist")

if existing == len(files_to_check):
    print("🎉 All migration files are present!")
else:
    print("⚠️  Some files are missing")

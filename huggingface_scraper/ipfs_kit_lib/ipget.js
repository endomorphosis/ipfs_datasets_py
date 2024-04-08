const { execSync } = require('child_process');

class ipget {
    constructor(resources, meta = null) {
        if (meta !== null) {
            if ('config' in meta) {
                if (meta['config'] !== null) {
                    this.config = meta['config'];
                }
            }
            if ('role' in meta) {
                if (meta['role'] !== null) {
                    this.role = meta['role'];
                    if (!["master", "worker", "leecher"].includes(this.role)) {
                        throw new Error("role is not either master, worker, leecher");
                    } else {
                        this.role = "leecher";
                    }
                }
            }
            if ('cluster_name' in meta) {
                if (meta['cluster_name'] !== null) {
                    this.cluster_name = meta['cluster_name'];
                }
            }
            if ('ipfs_path' in meta) {
                if (meta['ipfs_path'] !== null) {
                    this.ipfs_path = meta['ipfs_path'];
                }
            }
            if (this.role === "leecher" || this.role === "worker" || this.role === "master") {
                // pass
            }
        }
    }


    async ipget_download_object(kwargs = {}) {
        // NOTE: Make sure this function can download both files and folders 
        if (!kwargs.cid) {
            throw new Error("cid not found in kwargs");
        }
        if (!kwargs.path) {
            throw new Error("path not found in kwargs");
        }
        if (fs.existsSync(kwargs.path)) {
            // pass
        }
        //check if folder exists
        if (!fs.existsSync(path.dirname(kwargs.path))) {
            fs.mkdirSync(path.dirname(kwargs.path), { recursive: true });
        }
        
        const command = `export IPFS_PATH=${this.ipfs_path} && ipfs get ${kwargs.cid} -o ${kwargs.path}`;
        const process = exec(command);

        const start_time = Date.now();
        const timeout = 5000; // 5 seconds

        return new Promise((resolve, reject) => {
            process.on('exit', (code, signal) => {
                if (signal) {
                    reject(new Error("Command timed out"));
                } else {
                    const stats = fs.statSync(kwargs.path);
                    const metadata = {
                        "cid": kwargs.cid,
                        "path": kwargs.path,
                        "mtime": stats.mtimeMs,
                        "filesize": stats.size
                    };
                    resolve(metadata);
                }
            });

            setTimeout(() => {
                process.kill();
            }, timeout);
        });
    }

    async test_ipget() {
        try {
            execSync('which ipget');
            const ipget_download_object = await this.ipget_download_object({
                cid: "QmccfbkWLYs9K3yucc6b3eSt8s8fKcyRRt24e3CDaeRhM1",
                path: "/tmp/test"
            });
            return true;
        } catch (error) {
            return false;
        }
    }
}
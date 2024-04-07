 
const { execSync } = require('child_process');

class IpfsClusterService {
    constructor(resources, meta = null) {
        this.role = "leecher";
        if (meta !== null) {
            if ('config' in meta && meta['config'] !== null) {
                this.config = meta['config'];
            }
            if ('role' in meta && meta['role'] !== null) {
                if (!["master", "worker", "leecher"].includes(meta['role'])) {
                    throw new Error("role is not either master, worker, leecher");
                }
                this.role = meta['role'];
            }
        }
    }

    test_ipfs_cluster_service() {
        let detect;
        try {
            detect = execSync('which ipfs-cluster-service').toString();
        } catch (error) {
            detect = '';
        }
        return detect.length > 0;
    }

    ipfs_cluster_service_start() {
        const command = "systemctl start ipfs-cluster-service";
        const results = execSync(command).toString();
        return results;
    }

    ipfs_cluster_service_stop() {
        const command = "systemctl stop ipfs-cluster-service";
        const results = execSync(command).toString();
        return results;
    }

    ipfs_cluster_service_status() {
        const command = "ipfs-cluster-service status";
        const results = execSync(command).toString();
        return results;
    }
}
if (require.main === module) {
    const thisIpfsClusterService = new IpfsClusterService();
    const results = thisIpfsClusterService.test_ipfs_cluster_service();
    console.log(results);
}
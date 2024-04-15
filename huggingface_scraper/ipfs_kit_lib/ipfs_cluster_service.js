 
import { execSync } from 'child_process';

export class IpfsClusterService {
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

    async test_ipfs_cluster_service() {
        let detect;
        try {
            detect = execSync('which ipfs-cluster-service').toString();
        } catch (error) {
            detect = '';
        }
        return detect.length > 0;
    }

    async ipfs_cluster_service_start() {
        const command = "systemctl start ipfs-cluster-service";
        const results = execSync(command).toString();
        return results;
    }

    async ipfs_cluster_service_stop() {
        const command = "systemctl stop ipfs-cluster-service";
        const results = execSync(command).toString();
        return results;
    }

    async ipfs_cluster_service_status() {
        const command = "ipfs-cluster-service status";
        const results = execSync(command).toString();
        return results;
    }
}

async function main(){
    const thisIpfsClusterService = new IpfsClusterService();
    const results = await thisIpfsClusterService.test_ipfs_cluster_service();
    console.log(results);
}
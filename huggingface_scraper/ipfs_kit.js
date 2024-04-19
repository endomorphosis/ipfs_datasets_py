import path from 'path';
import * as install_ipfs from './ipfs_kit_lib/install_ipfs.js';
import * as ipfs from './ipfs_kit_lib/ipfs.js';
import * as IpfsClusterCtl from './ipfs_kit_lib/ipfs_cluster_ctl.js';
import * as IpfsClusterService from './ipfs_kit_lib/ipfs_cluster_service.js';
import * as IpfsClusterFollow from './ipfs_kit_lib/ipfs_cluster_follow.js';
import * as ipget from './ipfs_kit_lib/ipget.js';
import fs from 'fs';
import util from 'util';
import { promisify } from 'util';
import { promises as fsPromises } from 'fs';
import os from 'os';
import { exec, execSync } from 'child_process';


export class IpfsKit {
    constructor(resources, meta) {
        this.role = null;
        this.ipfsGetConfig = this.ipfsGetConfig;
        this.ipfsSetConfig = this.ipfsSetConfig;
        this.ipfsGetConfigValue = this.ipfsGetConfigValue;
        this.ipfsSetConfigValue = this.ipfsSetConfigValue;
        this.testInstall = this.testInstall;
        this.ipfsGet = this.ipgetDownloadObject;
        if (meta !== null) {
            if ('config' in meta && meta['config'] !== null) {
                this.config = meta['config'];
            }
            if ('role' in meta && meta['role'] !== null) {
                this.role = meta['role'];
                if (!['master', 'worker', 'leecher'].includes(this.role)) {
                    this.role = 'leecher';
                }
            }
            if ('cluster_name' in meta && meta['cluster_name'] !== null) {
                this.clusterName = meta['cluster_name'];
            }
            if ('ipfs_path' in meta && meta['ipfs_path'] !== null) {
                this.ipfsPath = meta['ipfs_path'];
            }
            if (['leecher', 'worker', 'master'].includes(this.role)) {
                this.ipfs = new ipfs.ipfs(resources, meta);
                this.ipget = new ipget.ipget(resources, meta);
            }
            if (this.role === 'worker') {
                this.ipfsClusterFollow = new IpfsClusterFollow.IPFSClusterFollow(resources, meta);
            }
            if (this.role === 'master') {
                this.ipfsClusterCtl = new IpfsClusterCtl.IPFSClusterCtl(resources, meta);
                this.ipfsClusterService = new IpfsClusterService.IpfsClusterService(resources, meta);
            }
        }
        else{
            this.role = 'leecher';
            this.cluster_name = null;
        }
        let installIpfs = new install_ipfs.InstallIPFS(resources, meta);
        this.installIpfs = installIpfs;

    }

    call(method, kwargs = {}) {
        switch (method) {
            case "ipfs_kit_stop":
                return this.ipfsKitStop(kwargs);
            case "ipfs_kit_start":
                return this.ipfsKitStart(kwargs);
            case "ipfs_kit_ready":
                return this.ipfsKitReady(kwargs);
            case "ipfs_get_pinset":
                return this.ipfs.ipfsGetPinset(kwargs);
            case "ipfs_follow_list":
                if (this.role !== "master") {
                    return this.ipfsClusterCtl.ipfsFollowList(kwargs);
                } else {
                    throw new Error("role is not master");
                }
            case "ipfs_follow_ls":
                if (this.role !== "master") {
                    return this.ipfsClusterFollow.ipfsFollowLs(kwargs);
                } else {
                    throw new Error("role is not master");
                }
            case "ipfs_follow_info":
                if (this.role !== "master") {
                    return this.ipfsClusterFollow.ipfsFollowInfo(kwargs);
                } else {
                    throw new Error("role is not master");
                }
            case "ipfs_cluster_get_pinset":
                return this.ipfsClusterGetPinset(kwargs);
            case "ipfs_ls_pinset":
                return this.ipfs.ipfsLsPinset(kwargs);
            case "ipfs_cluster_ctl_add_pin":
                if (this.role === "master") {
                    return this.ipfsClusterCtl.ipfsClusterCtlAddPin(kwargs);
                } else {
                    throw new Error("role is not master");
                }
            case "ipfs_cluster_ctl_rm_pin":
                if (this.role === "master") {
                    return this.ipfsClusterCtl.ipfsClusterCtlRmPin(kwargs);
                } else {
                    throw new Error("role is not master");
                }
            case "ipfs_add_pin":
                return this.ipfs.ipfsAddPin(kwargs);
            case "ipts_ls_pin":
                return this.ipfs.ipfsLsPin(kwargs);
            case "ipfs_remove_pin":
                return this.ipfs.ipfsRemovePin(kwargs);
            case "ipfs_get":
                return this.ipfs.ipfsGet(kwargs);
            case "ipget_download_object":
                this.method = 'download_object';
                return this.ipget.ipgetDownloadObject(kwargs);
            case "ipfs_upload_object":
                this.method = 'ipfs_upload_object';
                return this.ipfs.ipfsUploadObject(kwargs);
            case "loadCollection":
                return this.loadCollection(kwargs);
            default:
                return;
        }
    }

    ipfsKitReady(kwargs = {}) {
        let cluster_name;
        if (kwargs.cluster_name) {
            cluster_name = kwargs.cluster_name;
        } else if (this.clusterName !== null) {
            cluster_name = this.clusterName;
        } else if (this.role !== "leecher") {
            throw new Error("cluster_name is not defined");
        }
    
        let ready = false;
        let ipfs_ready = false;
        let ipfs_cluster_ready = false;
    
        const command1 = "ps -ef | grep ipfs | grep daemon | grep -v grep | wc -l";
        const execute1 = execSync(command1, (error, stdout, stderr) => {
            if (error) {
                console.log("command failed " + error);
                reject(error);
            } else {
                resolve(stdout.trim());
            }
        }).toString().trim();
    
        if (parseInt(execute1) > 0) {
            ipfs_ready = true;
        }
    
        if (this.role === "master") {
            return this.ipfsClusterService.ipfsClusterServiceReady();
        } 
        else if (this.role === "worker") {
            const data_ipfs_follow = this.ipfsClusterFollow.ipfsFollowInfo();
            if (data_ipfs_follow.cluster_peer_online && data_ipfs_follow.ipfs_peer_online) {
                if (data_ipfs_follow.cluster_name === cluster_name) {
                    if (data_ipfs_follow.cluster_peer_online === 'true' && data_ipfs_follow.ipfs_peer_online === 'true') {
                        ipfs_cluster_ready = true;
                    }
                }
            }
        }
    
        if (this.role === "leecher" && ipfs_ready) {
            ready = true;
        } else if (this.role !== "leecher" && ipfs_ready && ipfs_cluster_ready) {
            this.ipfsFollowInfo = data_ipfs_follow;
            ready = true;
        } else {
            ready = {
                "ipfs": ipfs_ready,
                "ipfs_cluster": ipfs_cluster_ready
            };
        }
    
        return ready;
    }


    async loadCollection(cid, kwargs = {}) {
        if (!cid) {
            throw new Error("collection is None");
        }

        let dstPath;
        if (kwargs.path) {
            dstPath = kwargs.path;
        } else {
            dstPath = this.ipfsPath;
            if (!fs.existsSync(dstPath)) {
                await mkdir(dstPath);
            }
            dstPath = path.join(dstPath, "pins");
            if (!fs.existsSync(dstPath)) {
                await mkdir(dstPath);
            }
            dstPath = path.join(dstPath, cid);
        }

        let ipget;
        try {
            ipget = await this.ipget.ipgetDownloadObject({cid: cid, path: dstPath});
        } catch (e) {
            ipget = e.toString();
        }

        let collection = await readFile(dstPath, 'utf8');

        try {
            let collectionJson = JSON.parse(collection);
            collection = collectionJson;
        } catch (e) {
            collectionJson = e;
        }

        return collection;
    }


    async ipfsAddPin(pin, kwargs = {}) {
        let dstPath;
        if (kwargs.path) {
            dstPath = kwargs.path;
        } else {
            dstPath = this.ipfsPath;
            if (!fs.existsSync(dstPath)) {
                await mkdir(dstPath);
            }
            dstPath = path.join(dstPath, "pins");
            if (!fs.existsSync(dstPath)) {
                await mkdir(dstPath);
            }
            dstPath = path.join(dstPath, pin);
        }

        let ipget;
        try {
            ipget = await this.ipget.ipgetDownloadObject({cid: pin, path: dstPath});
        } catch (e) {
            ipget = e.toString();
        }

        let result1 = null;
        let result2 = null;
        if (this.role === "master") {
            result1 = await this.ipfsClusterCtl.ipfsClusterCtlAddPin(dstPath, kwargs);
            result2 = await this.ipfs.ipfsAddPin(pin, kwargs);
        } else if (this.role === "worker" || this.role === "leecher") {
            result2 = await this.ipfs.ipfsAddPin(pin, kwargs);
        }

        let results = {
            "ipfs_cluster_ctl_add_pin": result1,
            "ipfs_add_pin": result2
        };

        return results;
    }


    async ipfsAddPath(path, kwargs = {}) {
        let result1 = null;
        let result2 = null;
        if (this.role === "master") {
            result2 = await this.ipfs.ipfsAddPath(path, kwargs);
            result1 = await this.ipfsClusterCtl.ipfsClusterCtlAddPath(path, kwargs);
        } else if (this.role === "worker" || this.role === "leecher") {
            result2 = await this.ipfs.ipfsAddPath(path, kwargs);
        }
    
        let results = {
            "ipfs_cluster_ctl_add_path": result1,
            "ipfs_add_path": result2
        };
    
        return results;
    }
    
    async ipfsLsPath(path, kwargs = {}) {
        let result1 = await this.ipfs.ipfsLsPath(path, kwargs);
        result1 = result1.filter(item => item !== "");
    
        let results = {
            "ipfs_ls_path": result1
        };
    
        return results;
    }

    async nameResolve(kwargs = {}) {
        let result1 = await this.ipfs.ipfsNameResolve(kwargs);
        let results = {
            "ipfs_name_resolve": result1
        };
        return results;
    }
    
    async namePublish(path, kwargs = {}) {
        let result1 = await this.ipfs.ipfsNamePublish(path, kwargs);
        let results = {
            "ipfs_name_publish": result1
        };
        return results;
    }
    
    async ipfsRemovePath(path, kwargs = {}) {
        let ipfsClusterPath = null;
        let ipfsPins = null;
        let ipfsClusterPins = null;
        let result1 = null;
        let result2 = null;
        if (this.role === "master") {
            result1 = await this.ipfsClusterCtl.ipfsClusterCtlRemovePath(path, kwargs);
            result2 = await this.ipfs.ipfsRemovePath(path, kwargs);
        } else if (this.role === "worker" || this.role === "leecher") {
            result2 = await this.ipfs.ipfsRemovePath(path, kwargs);
        }
    
        let results = {
            "ipfs_cluster_ctl_rm_path": result1,
            "ipfs_rm_path": result2
        };
        return results;
    }

    async ipfsRemovePin(pin, kwargs = {}) {
        let result1 = null;
        let result2 = null;
        if (this.role === "master") {
            result1 = await this.ipfsClusterCtl.ipfsClusterCtlRemovePin(pin, kwargs);
            result2 = await this.ipfs.ipfsRemovePin(pin, kwargs);
        } else if (this.role === "worker" || this.role === "leecher") {
            result2 = await this.ipfs.ipfsRemovePin(pin, kwargs);
        }
    
        let results = {
            "ipfs_cluster_ctl_rm_pin": result1,
            "ipfs_rm_pin": result2
        };
        return results;
    }
    
    async testInstall(kwargs = {}) {
        if (this.role === "master") {
            return {
                "ipfs_cluster_service": await this.installIpfs.ipfsClusterServiceTestInstall(),
                "ipfs_cluster_ctl": await this.installIpfs.ipfsClusterCtlTestInstall(),
                "ipfs": await this.installIpfs.ipfsTestInstall()
            };
        } else if (this.role === "worker") {
            return {
                "ipfs_cluster_follow": await this.installIpfs.ipfsClusterFollowTestInstall(),
                "ipfs": await this.installIpfs.ipfsTestInstall()
            };
        } else if (this.role === "leecher") {
            return await this.installIpfs.ipfsTestInstall();
        } else {
            throw new Error("role is not master, worker, or leecher");
        }
    }
    
    async ipfsGetPinset(kwargs = {}) {
        let ipfsPinset = await this.ipfs.ipfsGetPinset(kwargs);
    
        let ipfsCluster = null;
        if (this.role === "master") {
            ipfsCluster = await this.ipfsClusterCtl.ipfsClusterGetPinset(kwargs);
        } else if (this.role === "worker") {
            ipfsCluster = await this.ipfsClusterFollow.ipfsFollowList(kwargs);
        } else if (this.role === "leecher") {
            // do nothing
        }
    
        let results = {
            "ipfs_cluster": ipfsCluster,
            "ipfs": ipfsPinset
        };
        return results;
    }

    async ipfsKitStop(kwargs = {}) {
        let ipfsClusterService = null;
        let ipfsClusterFollow = null;
        let ipfs = null;
    
        if (this.role === "master") {
            try {
                ipfsClusterService = await this.ipfsClusterService.ipfs_cluster_service_stop();
            } catch (e) {
                console.log(e)
                ipfsClusterService = e.toString();
            }
            try {
                ipfs = await this.ipfs.daemon_stop();
            } catch (e) {
                console.log(e)
                ipfs = e.toString();
            }
        }
        if (this.role === "worker") {
            try {
                ipfsClusterFollow = await this.ipfsClusterFollow.ipfsFollowStop();
            } catch (e) {
                console.log(e);
                ipfsClusterFollow = e.toString();
            }
            try {
                ipfs = await this.ipfs.daemon_stop();
            } catch (e) {
                console.log(e);
                ipfs = e.toString();
            }
        }
        if (this.role === "leecher") {
            try {
                ipfs = await this.ipfs.daemon_stop();
            } catch (e) {
                console.log(e);
                ipfs = e.toString();
            }
        }
    
        let results = {
            "ipfs_cluster_service": ipfsClusterService,
            "ipfs_cluster_follow": ipfsClusterFollow,
            "ipfs": ipfs
        };
        return results;
    }
    
    async ipfsKitStart(kwargs = {}) {
        let ipfsClusterService = null;
        let ipfsClusterFollow = null;
        let ipfs = null;
    
        if (this.role === "master") {
            try {
                ipfs = await this.ipfs.daemon_start();
            } catch (e) {
                console.log(e)
                ipfs = e.toString();
            }
            try {
                ipfsClusterService = await this.ipfsClusterService.ipfs_cluster_service_start();
            } catch (e) {
                ipfsClusterService = e.toString();
            }
        }

        if (this.role === "worker") {
            try {
                ipfs = this.ipfs.daemon_start();
            } catch (e) {
                console.log(e);
                ipfs = e.toString();
            }
            try {
                ipfsClusterFollow = await this.ipfsClusterFollow.ipfsFollowStart();
            } catch (e) {
                console.log(e);
                ipfsClusterFollow = e.toString();
            }
        }

        if (this.role === "leecher") {
            try {
                ipfs = await this.ipfs.daemon_start();
            } catch (e) {
                console.log(e);
                ipfs = e.toString();
            }
        }
    
        let results = {
            "ipfs_cluster_service": ipfsClusterService,
            "ipfs_cluster_follow": ipfsClusterFollow,
            "ipfs": ipfs
        };
        return results;
    }

    async ipfsGetConfig(kwargs = {}) {
        const command = "ipfs config show";
        let results = "";

        try {
            const { stdout } = await exec(command);
            results = JSON.parse(stdout);
        } catch (error) {
            console.log("command failed");
            console.log(command);
            console.log(error);
        } finally {
            this.ipfsConfig = results;
        }

        return results;
    }

    async ipfsSetConfig(newConfig, kwargs = {}) {
        const filename = path.join(os.tmpdir(), `${Date.now()}.json`);
        fs.writeFileSync(filename, JSON.stringify(newConfig));

        const command = "ipfs config replace " + filename;
        let results = "";

        try {
            const { stdout } = await exec(command);
            results = JSON.parse(stdout);
        } catch (error) {
            console.log("command failed");
            console.log(command);
            console.log(error);
        } finally {
            this.ipfsConfig = results;
        }

        return results;
    }   
    
    async ipfsGetConfigValue(key, kwargs = {}) {
        let command = null;
        let results = null;

        try {
            command = await this.ipfsExecute({
                "command": "config",
                "key": key
            });
            results = JSON.parse(command);
        } catch (error) {
            console.log("command failed");
            console.log(command);
            console.log(error);
        }

        const query = "ipfs config " + key;

        try {
            const { stdout } = await exec(query);
            results = JSON.parse(stdout);
        } catch (error) {
            console.log("command failed");
            console.log(query);
            console.log(error);
            throw new Error("command failed");
        }

        return results;
    }

    async ipfsSetConfigValue(key, value, kwargs = {}) {
        let command = null;
        let results = null;

        try {
            command = await this.ipfsExecute({
                "command": "config",
                "key": key,
                "value": value
            });
            results = JSON.parse(command);
        } catch (error) {
            console.log("command failed");
            console.log(command);
            console.log(error);
        }

        const query = "ipfs config " + key + " " + value;

        try {
            const { stdout } = await exec(query);
            results = JSON.parse(stdout);
        } catch (error) {
            console.log("command failed");
            console.log(query);
            console.log(error);
            throw new Error("command failed");
        }
    
            return results;
        }
    


    checkCollection(collection) {
        let status = {};
        let collectionKeys = Object.keys(collection);
        let pinsetKeys = Object.keys(this.pinset);
        let orphanModels = [];
        let orphanPins = [];
        let activePins = [];
        let activeModels = [];

        for (let thisModel of collectionKeys) {
            if (thisModel !== "cache") {
                let thisManifest = collection[thisModel];
                let thisId = thisManifest["id"];
                let thisCache = thisManifest["cache"];
                let thisIpfsCache = thisCache["ipfs"];
                let thisIpfsCacheKeys = Object.keys(thisIpfsCache);
                let foundAll = true;

                for (let thisCacheBasename of thisIpfsCacheKeys) {
                    let thisCacheItem = thisIpfsCache[thisCacheBasename];
                    let thisCacheItemPath = thisCacheItem["path"];
                    let thisCacheItemUrl = thisCacheItem["url"];

                    if (pinsetKeys.includes(thisCacheItemPath)) {
                        activePins.push(thisCacheItemPath);
                    } else {
                        foundAll = false;
                    }
                }

                if (foundAll) {
                    activeModels.push(thisModel);
                } else {
                    orphanModels.push(thisModel);
                }
            }
        }

        for (let thisPin of pinsetKeys) {
            if (!activePins.includes(thisPin)) {
                orphanPins.push(thisPin);
            }
        }

        status["orphanModels"] = orphanModels;
        status["orphanPins"] = orphanPins;
        status["activePins"] = activePins;
        status["activeModels"] = activeModels;

        return status;
    }
    
    


    async ipfsUploadObject(kwargs) {
        return this.uploadObject(kwargs['file']);
    }

    async ipgetDownloadObject(kwargs) {
        return this.ipget.ipgetDownloadObject(kwargs);
    }

    async updateCollectionIpfs(collection, collectionPath) {
        let thisCollectionIpfs = null;
        let thisCollectionPath = collectionPath;

        const command1 = "ipfs add -r " + thisCollectionPath;
        try {
            const { stdout: results1 } = await exec(command1);
            const resultsMatrix = results1.split("\n").map(line => line.split(" "));

            if (resultsMatrix.length === 2) {
                thisCollectionIpfs = resultsMatrix[resultsMatrix.length - 2][1];
            }

            const metadata = ["path=/collection.json"];
            let argstring = "";
            for (let i = 0; i < metadata.length; i++) {
                argstring += " --metadata " + metadata[i];
            }

            const command2 = "ipfs-cluster-ctl pin add " + thisCollectionIpfs + argstring;
            const { stdout: results2 } = await exec(command2);

            if ("cache" in collection) {
                collection["cache"]["ipfs"] = thisCollectionIpfs;
            } else {
                collection["cache"] = {};
                collection["cache"]["ipfs"] = thisCollectionIpfs;
            }
            return thisCollectionIpfs;
        
        } catch (error) {
            console.log("ipfs add failed");
            console.log(command1);
            console.log(error);
        }
    }

}


async function main() {
    const ipfs = new IpfsKit(null, null);
    const results = await ipfs.testInstall();
    console.log(results);
}

main();
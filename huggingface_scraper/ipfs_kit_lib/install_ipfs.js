
import { execSync, exec } from 'child_process';
import fs from 'fs';
import os from 'os';
import path from 'path';
import * as test_fio from './test_fio.js';
import util from 'util';
import process from 'process';
import { ChildProcess } from 'child_process';
import { spawnSync } from 'child_process';
import { spawn } from 'child_process';
import { run } from 'shutil';
import { randomUUID } from 'crypto';
import crypto from 'crypto';

export class InstallIPFS {
    constructor(resources, meta = null) {
        this.resources = resources;
        this.meta = meta;
        this.thisDir = path.dirname(new URL(import.meta.url).pathname);
        this.ipfsTestInstall = this.ipfsTestInstall.bind(this);
        this.env = process.env;
        this.ipfs_dist_tar = "https://dist.ipfs.tech/kubo/v0.26.0/kubo_v0.26.0_linux-amd64.tar.gz";
        this.ipfs_follow_dist_tar = "https://dist.ipfs.tech/ipfs-cluster-follow/v1.0.8/ipfs-cluster-follow_v1.0.8_linux-amd64.tar.gz";
        this.ipfs_cluster_dist_tar = "https://dist.ipfs.tech/ipfs-cluster-ctl/v1.0.8/ipfs-cluster-ctl_v1.0.8_linux-amd64.tar.gz";
        this.ipfs_cluster_service_dist_tar = "https://dist.ipfs.tech/ipfs-cluster-service/v1.0.8/ipfs-cluster-service_v1.0.8_linux-amd64.tar.gz";
        if (meta !== null) {
            this.config = meta.config ? meta.config : null;
            this.secret = meta.secret ? meta.secret : null;

            if (this.secret == null) {
                // generate 64 character hex string
                this.secret = crypto.randomBytes(32).toString('hex');
            }

            if (meta.role) {
                this.role = meta.role;
                if (!['master', 'worker', 'leecher'].includes(this.role)) {
                    throw new Error("role is not either master, worker, leecher");
                }
            } else {
                this.role = "leecher";
            }

            if (meta.ipfsPath) {
                this.ipfsPath = meta.ipfsPath;
                if (!fs.existsSync(this.ipfsPath)) {
                    fs.mkdirSync(this.ipfsPath, { recursive: true });
                }
                let testDisk = new test_fio.TestFio();
                this.diskName = testDisk.disk_device_name_from_location(this.ipfsPath);
                this.diskStats = {
                    disk_size: testDisk.disk_device_total_capacity(this.diskName),
                    disk_used: testDisk.disk_device_used_capacity(this.diskName),
                    disk_avail: testDisk.disk_device_avail_capacity(this.diskName),
                    disk_name: this.diskName
                };
            } else {
                if (os.userInfo().username === "root") {
                    this.ipfsPath = "/root/ipfs";
                } else {
                    this.ipfsPath = path.join(path.join(os.homedir(),".cache"), "ipfs");
                }
                let testDisk = new test_fio.TestFio();
                this.diskName = testDisk.disk_device_name_from_location(this.ipfsPath);
                this.diskStats = {
                    disk_size: testDisk.disk_device_total_capacity(this.diskName),
                    disk_used: testDisk.disk_device_used_capacity(this.diskName),
                    disk_avail: testDisk.disk_device_avail_capacity(this.diskName),
                    disk_name: this.diskName
                };
            }

            this.clusterName = meta.clusterName ? meta.clusterName : null;
            this.clusterLocation = meta.clusterLocation ? meta.clusterLocation : "/ip4/167.99.96.231/tcp/9096/p2p/12D3KooWKw9XCkdfnf8CkAseryCgS3VVoGQ6HUAkY91Qc6Fvn4yv";

            if (['leecher', 'worker', 'master'].includes(this.role) && this.ipfsPath) {
                // Bind the methods for installing and configuring IPFS
                this.ipfs_install_command = this.installIPFSDaemon.bind(this);
                this.ipfs_config_command = this.configIPFS.bind(this);
            }

            if (this.role === "worker" && this.cluster_name && this.ipfsPath) {
                // Bind methods for worker role
                this.clusterInstall = this.installIPFSClusterFollow.bind(this);
                this.clusterConfig = this.configIPFSClusterFollow.bind(this);
            }

            if (this.role === "master" && this.cluster_name && this.ipfsPath) {
                // Bind methods for master role
                this.clusterCtlInstall = this.installIPFSClusterCtl.bind(this);
                this.clusterCtlConfig = this.configIPFSClusterCtl.bind(this);
                this.clusterService_install = this.installIPFSClusterService.bind(this);
                this.clusterServiceConfig = this.configIPFSClusterService.bind(this);
            }
        }
    }

    async installIPFSDaemon(options = {}) {
        let detect = '';
        try {
            detect = execSync("which ipfs").toString().trim();
            if (detect.length > 0) {
                return true;
            }
        } catch (e) {
            console.error(e);
            detect = '';
        }
        let thisDir = this.thisDir || path.dirname(new URL(import.meta.url).pathname);

        if (!detect) {
            try {
                const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'ipfs-'));
                const tarFile = path.join(tmpDir, "kubo.tar.gz");
                execSync(`wget ${this.ipfs_dist_tar} -O ${tarFile}`);
                execSync(`tar -xvzf ${tarFile} -C ${tmpDir}`);
                execSync(`cd ${tmpDir}/kubo && sudo bash install.sh`);
                const results = execSync("ipfs --version").toString().trim();
                const serviceConfig = fs.readFileSync(path.join(thisDir, 'ipfs.service')).toString();
                fs.writeFileSync("/etc/systemd/system/ipfs.service", serviceConfig);
                execSync("systemctl enable ipfs");
                return results.includes("ipfs");
            } catch (e) {
                console.error(e);
                return false;
            }
        }
    }

    installIPFSClusterFollow(options = {}) {
        // Check if ipfs-cluster-follow is already installed
        let followCmdExists = execSync('which ipfs-cluster-follow')
        if (followCmdExists.length > 0) {
            console.log('ipfs-cluster-follow is already installed.');
            return true;
        } else {
            console.log('ipfs-cluster-follow is not installed, proceeding with installation.');
            // Downloading tarball
            const url = this.ipfs_follow_dist_tar;
            const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'ipfs-cluster-follow-'));
            const tarPath = path.join(tmpDir, url.split('/')[-1]);
            let thisDir = this.thisDir || path.dirname(new URL(import.meta.url).pathname);

            const file = fs.createWriteStream(tarPath);
            https.get(url, function(response) {
                response.pipe(file);
                file.on('finish', () => {
                    file.close();
                    console.log('Download completed.');

                    // Extracting tarball
                    tar.x({
                        file: tarPath,
                        C: tmpDir,
                    }).then(() => {
                        console.log('Extraction completed.');
                        const binPath = path.join(tmpDir, 'ipfs-cluster-follow', 'ipfs-cluster-follow');
                        execSync(`sudo mv ${binPath} /usr/local/bin/ipfs-cluster-follow`);
                        try {
                            // Verify installation
                            const version = execSync('ipfs-cluster-follow --version').toString().trim();
                            console.log(`Installed ipfs-cluster-follow version: ${version}`);
                            if (os.userInfo().username == "root") {
                                let serviceConfig = fs.readFileSync(path.join(thisDir, 'ipfs_clusterFollow.service')).toString();
                                fs.writeFileSync('/etc/systemd/system/ipfs-cluster-follow.service', serviceConfig);
                                execSync('systemctl enable ipfs-cluster-follow');
                                console.log('ipfs-cluster-follow service enabled.');
                            }
                            else{
                                console.log('Please run as root user to enable systemd service');
                            }
                        } catch (e) {
                            console.error('Error verifying ipfs-cluster-follow installation:', e);
                            return false;
                        }
                    }).catch((err) => {
                        console.error('Error extracting file:', err);
                    });
                });
            }).on('error', (err) => {
                // Handle errors
                console.error('Error downloading file:', err);
                fs.unlink(dest);
            });
        }
        return results
    }
    
    async installIPFSClusterCtl(options = {}) {
        try {
            const detect = execSync("which ipfs-cluster-ctl").toString().trim();
            if (detect) {
                console.log('ipfs-cluster-ctl is already installed.');
                return true;
            }
        } catch (e) {
            console.error(e.message);
        }
    
        const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'ipfs-cluster-ctl-'));
        const tarPath = path.join(tmpDir, 'ipfs-cluster-ctl.tar.gz');
        const url = "https://dist.ipfs.tech/ipfs-cluster-ctl/v1.0.8/ipfs-cluster-ctl_v1.0.8_linux-amd64.tar.gz";
    
        // Download and extract the tarball
        const file = fs.createWriteStream(tarPath);
        https.get(url, (response) => {
            response.pipe(file);
            file.on('finish', () => {
                file.close();
                console.log('Download completed.');
                tar.x({
                    file: tarPath,
                    C: tmpDir,
                }).then(() => {
                    console.log('Extraction completed.');
                    const binPath = path.join(tmpDir, 'ipfs-cluster-ctl', 'ipfs-cluster-ctl');
                    execSync(`sudo mv ${binPath} /usr/local/bin/ipfs-cluster-ctl`);
                    try {
                        // Verify installation
                        const version = execSync('ipfs-cluster-ctl --version').toString().trim();
                        console.log(`Installed ipfs-cluster-ctl version: ${version}`);
                        return true;
                    } catch (e) {
                        console.error('Error verifying ipfs-cluster-ctl installation:', e);
                        return false;
                    }
                }).catch((err) => {
                    console.error('Error extracting file:', err);
                });
            });
        }).on('error', (err) => {
            console.error('Error downloading file:', err);
            fs.unlink(tarPath, (err) => {
                if (err) console.error(`Error removing temporary tarball: ${err}`);
            });
        });
    }

    async installIPFSClusterService(options = {}) {
        try {
            const detect = execSync("which ipfs-cluster-service").toString().trim();
            if (detect) {
                console.log('ipfs-cluster-service is already installed.');
                return true;
            }
        } catch (e) {
            console.error(e.message);
        }
    
        const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'ipfs-cluster-service-'));
        const tarPath = path.join(tmpDir, 'ipfs-cluster-service.tar.gz');
        const url = "https://dist.ipfs.tech/ipfs-cluster-service/v1.0.8/ipfs-cluster-service_v1.0.8_linux-amd64.tar.gz";
        let thisDir = this.thisDir || path.dirname(new URL(import.meta.url).pathname);
    
        // Download and extract the tarball
        const file = fs.createWriteStream(tarPath);
        https.get(url, (response) => {
            response.pipe(file);
            file.on('finish', () => {
                file.close();
                console.log('Download completed.');
                tar.x({
                    file: tarPath,
                    C: tmpDir,
                }).then(() => {
                    console.log('Extraction completed.');
                    const binPath = path.join(tmpDir, 'ipfs-cluster-service', 'ipfs-cluster-service');
                    execSync(`sudo mv ${binPath} /usr/local/bin/ipfs-cluster-service`);
                    try {
                        // Verify installation
                        const version = execSync('ipfs-cluster-service --version').toString().trim();
                        console.log(`Installed ipfs-cluster-service version: ${version}`);
                        // if root user, write and enable systemd service
                        if (os.userInfo().username == "root") {
                            let serviceConfig = fs.readFileSync(path.join(thisDir, 'ipfs_clusterFollow.service')).toString();
                            fs.writeFileSync('/etc/systemd/system/ipfs-cluster-follow.service', serviceConfig);
                            execSync('systemctl enable ipfs-cluster-service');
                            console.log('ipfs-cluster-service service enabled.');
                            execSync('systemctl daemon-reload');
                            console.log('systemctl daemon reloaded.');
                        }
                        else{
                            console.log('Please run as root user to enable systemd service');
                        }    
                        return true;
                    } catch (e) {
                        console.error('Error verifying ipfs-cluster-service installation:', e);
                        return false;
                    }
                }).catch((err) => {
                    console.error('Error extracting file:', err);
                });
            });
        }).on('error', (err) => {
            console.error('Error downloading file:', err);
            fs.unlink(tarPath, (err) => {
                if (err) console.error(`Error removing temporary tarball: ${err}`);
            });
        });
    }

    async installIPGet(options = {}) {
        try {
            // Check if ipget is already installed
            const detect = execSync("which ipget").toString().trim();
            if (detect) {
                //console.log('ipget is already installed.');
                return true;
            }
        } catch (e) {
            console.error(e.message);
        }
    
        // Prepare for download and extraction
        const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'ipget-'));
        const tarPath = path.join(tmpDir, 'ipget.tar.gz');
        const url = "https://dist.ipfs.tech/ipget/v0.10.0/ipget_v0.10.0_linux-amd64.tar.gz";
    
        // Download the tarball
        https.get(url, (response) => {
            const fileStream = fs.createWriteStream(tarPath);
            response.pipe(fileStream);
            fileStream.on('finish', () => {
                fileStream.close();
                console.log('Downloaded ipget tarball.');
    
                // Extract the tarball
                tar.x({
                    file: tarPath,
                    C: tmpDir,
                }).then(() => {
                    console.log('Extracted ipget.');
    
                    // Move to bin and install
                    if (os.userInfo().username == "root") {
                        const binPath = path.join(tmpDir, 'ipget', 'ipget');
                        execSync(`sudo mv ${binPath} /usr/local/bin/ipget`);
                        const installScriptPath = path.join(tmpDir, 'ipget', 'install.sh');
                        execSync(`cd ${tmpDir}/ipget && sudo bash install.sh`);
        
                        // Update system settings
                        execSync('sudo sysctl -w net.core.rmem_max=2500000');
                        execSync('sudo sysctl -w net.core.wmem_max=2500000');    
                    }
                    else{
                        console.log('Please run as root user to install ipget');
                        execSync(`cd ${tmpDir}/ipget && bash install.sh`);                        
                    }
    
                    // Verify installation
                    try {
                        const version = execSync('ipget --version').toString().trim();
                        console.log(`Installed ipget version: ${version}`);
                        return true;
                    } catch (verificationError) {
                        console.error('Error verifying ipget installation:', verificationError);
                        return false;
                    }
                }).catch((extractionError) => {
                    console.error('Error extracting ipget:', extractionError);
                });
            });
        }).on('error', (downloadError) => {
            console.error('Error downloading ipget:', downloadError);
        });
    }
    
    async configIPFSClusterService(options = {}) {
        let clusterName = options.clusterName || this.clusterName;
        let diskStats = options.diskStats || this.diskStats;
        let ipfsPath = options.ipfsPath || this.ipfsPath;
        let secret = options.secret || this.secret;

        if (!diskStats) throw new Error("diskStats is None");
        if (!ipfsPath) throw new Error("ipfsPath is None");
        if (!clusterName) throw new Error("clusterName is None");
        if (!secret) throw new Error("secret is None");

        let thisDir = this.thisDir || path.dirname(new URL(import.meta.url).pathname);
        let homeDir = os.homedir();
        let clusterPath = path.join(ipfsPath, clusterName);
        let servicePath;
        let run_daemon;
        let initClusterDaemonResults;
        let results = {}
        if (os.userInfo().username == "root") {
            servicePath = path.join("/root", ".ipfs-cluster");
        } else {
            servicePath = path.join(homeDir, ".ipfs-cluster");
        }
        if (clusterName && ipfsPath && diskStats && secret) {
            try{
                if (os.userInfo().username == "root") {
                    const command0 = "systemctl enable ipfs-cluster-service";
                    const results0 = execSync(command0, { shell: true });
                    const initClusterDaemon = `IPFS_PATH=${ipfsPath} ipfs-cluster-service init -f`;
                    initClusterDaemonResults = execSync(initClusterDaemonResults, { shell: true }).toString();
                } else {
                    const initClusterDaemon = `IPFS_PATH=${ipfsPath} ipfs-cluster-service init -f`;
                    initClusterDaemonResults = execSync(command1, { shell: true }).toString();
                }

                results["initClusterDaemonResults"] = initClusterDaemonResults                
            }
            catch(e){
                console.error(e);
                throw new Error("Error configuring IPFS Cluster Service");
            }

            try{
                let serviceConfig = fs.readFileSync(path.join(thisDir, 'service.json')).toString();
                let workerID = "worker-" + crypto.randomUUID();
                serviceConfig = serviceConfig.replace('"cluster_name": "ipfs-cluster"', 'cluster_name": "'+clusterName+'"');
                serviceConfig = serviceConfig.replace('"secret": "96d5952479d0a2f9fbf55076e5ee04802f15ae5452b5faafc98e2bd48cf564d3"', '"secret": "'+ secret +'"');
                fs.writeFileSync(path.join(followPath, 'service.json'), serviceConfig);
                let peerStore = fs.readFileSync(path.join(thisDir, 'peerstore')).toString();
                fs.writeFileSync(path.join(followPath, 'peerstore'), peerStore);

                let pebbleLink = path.join(servicePath, "pebble");
                let pebbleDir = path.join(clusterPath, "pebble");
                if (clusterPath != followPath) {
                    if (fs.existsSync(pebbleLink)) {
                        fs.unlinkSync(pebbleLink);
                    }
                    if (!fs.existsSync(pebbleDir)) {
                        fs.mkdirSync(pebbleDir, { recursive: true });
                    }
                    fs.symlinkSync(pebbleDir, pebbleLink);
                }

                if (os.userInfo().username == "root") {
                    let serviceFile = fs.readFileSync(path.join(thisDir, 'ipfs_cluster.service')).toString();
                    fs.writeFileSync("/etc/systemd/system/ipfs-cluster-service.service", new_service)
                    execSync("systemctl enable ipfs-cluster-service");
                    execSync("systemctl daemon-reload");
                }

            }
            catch(e){
                console.error(e);
                throw new Error("Error configuring IPFS Cluster Service");
            }

            try{
                let run_daemon_results
                if (os.userInfo().username == "root") {
                    let reloadDaemon = "systemctl daemon-reload";
                    let reloadDaemonResults = execSync(reloadDaemon);

                    // Enable service 
                    let enableDaemon = "systemctl enable ipfs-cluster-service";
                    let enableDaemonResults = execSync(enableDaemon);

                    // Start daemon
                    let startDaemon = "systemctl start ipfs-cluster-service";
                    let startDaemonResults = execSync(startDaemon);
                    await new Promise(resolve => setTimeout(resolve, 2000));
                    run_daemon = execSync("systemctl status ipfs-cluster-service | grep Active | awk '{print $2}'").toString();
                }
                else{
                    let run_daemon_cmd = "ipfs-cluster-service daemon";
                    run_daemon = exec(
                        run_daemon_cmd,
                        (error, stdout, stderr) => {
                            console.log(stdout);
                        }
                    );
                    await new Promise(resolve => setTimeout(resolve, 2000));
                    run_daemon = run_daemon.stderr.read();
                }
                // Check if daemon is running
                results["run_daemon"] = run_daemon;
            }
            catch(e){
                console.log(e);
                return e.toString();
            }
        }
        return results;
    }

    async configIPFSClusterCtl(options = {}) {
        let results = {};
        let run_daemon_cmd = "ipfs-cluster-ctl status";
        run_daemon = execSync(run_daemon_cmd).toString();

        findDaemon = "ps -ef | grep ipfs-cluster-service | grep -v grep | wc -l";
        findDaemonResuls = execSync(findDaemon).toString();

        if (parseInt(findDaemonResuls) == 0) {
            console.log("ipfs-cluster-service daemon is not running");
            throw new Error("ipfs-cluster-service daemon is not running");
        }
        else{
            let killDaemon = "ps -ef | grep ipfs-cluster-service | grep -v grep | awk '{print $2}' | xargs kill -9";
            let killDaemonResults = execSync(killDaemon);
        }

        results["run_daemon"] = run_daemon;

        return results;
    }

    async configIPFSClusterFollow(options = {}) {
        let clusterName = options.clusterName || this.clusterName;
        let diskStats = options.diskStats || this.diskStats;
        let ipfsPath = options.ipfsPath || this.ipfsPath;
        let secret = options.secret || this.secret;

        if (!diskStats) throw new Error("diskStats is None");
        if (!ipfsPath) throw new Error("ipfsPath is None");
        if (!clusterName) throw new Error("clusterName is None");
        if (!secret) throw new Error("secret is None");

        let thisDir = this.thisDir || path.dirname(new URL(import.meta.url).pathname);
        let homeDir = os.homedir();
        let clusterPath = path.join(ipfsPath, clusterName);
        let followPath;
        let run_daemon;
        let followInitCmdResults;
        if (os.userInfo().username == "root") {
            followPath = path.join("/root", ".ipfs-cluster-follow", clusterName);
        } else {
            followPath = path.join(homeDir, ".ipfs-cluster-follow", clusterName);
        }
        if (clusterName && ipfsPath && diskStats && secret) {
            try {
                let rm_command = `rm -rf ${followPath}`;
                execSync(rm_command);
                let followInitCmd = `ipfs-cluster-follow ${clusterName} init ${ipfsPath}`;
                followInitCmdResults = execSync(followInitCmd).toString()
                if (!fs.existsSync(clusterPath)) {
                    fs.mkdirSync(clusterPath, { recursive: true });
                }
                if (!fs.existsSync(followPath)) {
                    fs.mkdirSync(followPath, { recursive: true });
                }
                let serviceConfig = fs.readFileSync(path.join(thisDir, 'service_follower.json')).toString();
                let workerID = "worker-" + crypto.randomUUID();
                serviceConfig = serviceConfig.replace('"peername": "worker"', `peername": `+workerID+`"`);
                serviceConfig = serviceConfig.replace('"cluster_name": "ipfs-cluster"', 'cluster_name": "'+clusterName+'"');
                serviceConfig = serviceConfig.replace('"secret": "96d5952479d0a2f9fbf55076e5ee04802f15ae5452b5faafc98e2bd48cf564d3"', '"secret": "'+ secret +'"');
                fs.writeFileSync(path.join(followPath, 'service.json'), serviceConfig);
                let peerStore = fs.readFileSync(path.join(thisDir, 'peerstore')).toString();
                fs.writeFileSync(path.join(followPath, 'peerstore'), peerStore);

                // Link the pebble directory if needed
                let pebbleLink = path.join(followPath, "pebble");
                let pebbleDir = path.join(clusterPath, "pebble");
                if (clusterPath != followPath) {
                    if (fs.existsSync(pebbleLink)) {
                        fs.unlinkSync(pebbleLink);
                    }
                    if (!fs.existsSync(pebbleDir)) {
                        fs.mkdirSync(pebbleDir, { recursive: true });
                    }
                    fs.symlinkSync(pebbleDir, pebbleLink);
                }

                if (os.userInfo().username == "root") {
                    let serviceFile = fs.readFileSync(path.join(thisDir, 'ipfs_clusterFollow.service')).toString();
                    let new_service = serviceFile.replace("ExecStart=/usr/local/bin/ipfs-cluster-follow run","ExecStart=/usr/local/bin/ipfs-cluster-follow "+ clusterName + " run")
                    new_service = new_service.replace("Description=IPFS Cluster Follow","Description=IPFS Cluster Follow "+ clusterName)
                    fs.writeFileSync("/etc/systemd/system/ipfs-cluster-follow@"+clusterName+".service", new_service)
                    execSync("systemctl enable ipfs-cluster-follow@"+clusterName);
                    execSync("systemctl daemon-reload");
                }

            } catch (e) {
                console.error(e);
            }
        }

        try{
            let findDaemon = "ps -ef | grep ipfs-cluster-follow | grep -v grep | wc -l";
            let findDaemonResuls = execSync(findDaemon).toString();
            if (parseInt(findDaemonResuls) > 0) {
                killDaemon = "ps -ef | grep ipfs-cluster-follow | grep -v grep | awk '{print $2}' | xargs kill -9";
                killDaemonResults = execSync(killDaemon);
            }
            let run_daemon_results
            if (os.userInfo().username == "root") {
                let reloadDaemon = "systemctl daemon-reload";
                let reloadDaemonResults = execSync(reloadDaemon);

                // Enable service 
                let enableDaemon = "systemctl enable ipfs-cluster-follow@"+ clusterName;
                let enableDaemonResults = execSync(enableDaemon);

                // Start daemon
                let startDaemon = "systemctl start ipfs-cluster-follow@" + clusterName;
                let startDaemonResults = execSync(startDaemon);
                await new Promise(resolve => setTimeout(resolve, 2000));
                run_daemon = execSync("systemctl status ipfs-cluster-follow@"+ clusterName +" | grep Active | awk '{print $2}'").toString();
            }
            else{
                let run_daemon_cmd = "ipfs-cluster-follow " + clusterName + " run";
                run_daemon = exec(
                    run_daemon_cmd,
                    (error, stdout, stderr) => {
                        console.log(stdout);
                    }
                );
                await new Promise(resolve => setTimeout(resolve, 2000));
                run_daemon = run_daemon.stderr.read();
            }
            // Check if daemon is running
            await new Promise(resolve => setTimeout(resolve, 2000));

            findDaemon = "ps -ef | grep ipfs-cluster-follow | grep -v grep | wc -l";
            findDaemonResuls = execSync(findDaemon).toString();

            if (parseInt(findDaemonResuls) == 0) {
                console.log("ipfs-cluster-follow daemon is not running");
                throw new Error("ipfs-cluster-follow daemon is not running");
            }
            else{
                let killDaemon = "ps -ef | grep ipfs-cluster-follow | grep -v grep | awk '{print $2}' | xargs kill -9";
                let killDaemonResults = execSync(killDaemon);
            }
    
        }
        catch(e){
            console.log(e);
            return e.toString();
        }

        let results = {
            "followInitCmdResults": followInitCmdResults,
            "run_daemon": run_daemon
        };

        return results;
    }

    async configIPFS(options = {}) {
        let diskStats = options.diskStats || this.diskStats;
        let ipfsPath = options.ipfsPath || this.ipfsPath;
        let identity
        let config
        let peerId
        let run_daemon
        let public_key
        let ipfs_daemon
        if (!diskStats) throw new Error("diskStats is None");
        if (!ipfsPath) throw new Error("ipfsPath is None");

        ipfsPath = path.join(ipfsPath, "ipfs");
        fs.mkdirSync(ipfsPath, { recursive: true });

        let ipfsDirContents = fs.readdirSync(ipfsPath);
        if (ipfsDirContents.length > 0) {
            console.log("IPFS directory is not empty. Clearing contents...");
            for (let thisFile of ipfsDirContents) {
                let delfile = path.join(ipfsPath, thisFile);
                if (fs.existsSync(delfile)) {
                    if (fs.lstatSync(delfile).isFile()) {
                        fs.unlinkSync(delfile);
                    }
                    else if(fs.lstatSync(delfile).isDirectory()) {
                        fs.rmSync(delfile, {
                            recursive: true
                        });
                    }
                    else {
                        console.log(`Unknown file type: ${delfile}`);
                    }
                }
            }
        }
        
        let results = {
            config: null,
            identity: null,
            public_key: null
        };

        if (diskStats && ipfsPath) {
            try {
                execSync(`IPFS_PATH=${ipfsPath} ipfs init --profile=badgerds`);
                peerId = JSON.parse(execSync(`IPFS_PATH=${ipfsPath} ipfs id`).toString());
                execSync(`IPFS_PATH=${ipfsPath} ipfs config profile apply badgerds`);

                // Calculate available disk space and adjust storage allocation
                let diskAvailable = parseFloat(diskStats.disk_avail);
                let minFreeSpace = 32 * 1024 * 1024 * 1024; // 32 GB
                if (diskAvailable > minFreeSpace) {
                    let allocate = Math.ceil(((diskAvailable - minFreeSpace) * 0.8) / 1024 / 1024 / 1024);
                    execSync(`IPFS_PATH=${ipfsPath} ipfs config Datastore.StorageMax ${allocate}GB`);
                }

                // Load peer list and add to bootstrap
                let peerListPath = path.join(process.cwd(), "peerstore");
                if (fs.existsSync(peerListPath)) {
                    let peerList = fs.readFileSync(peerListPath).toString().split("\n");
                    peerList.forEach(peer => {
                        if (peer) {
                            execSync(`IPFS_PATH=${ipfsPath} ipfs bootstrap add ${peer}`);
                        }
                    });
                }

                //Assuming ipfs_service_text contains the systemd service configuration
                if (os.userInfo().username == "root") {
                    const original_service = fs.readFileSync("/etc/systemd/system/ipfs.service").toString();
                    const new_service_text = original_service.replace("ExecStart=","ExecStart= bash -c \"export IPFS_PATH="+ ipfsPath + " && ");
                    fs.writeFileSync("/etc/systemd/system/ipfs.service", new_service_text);
                }

                results.config = execSync(`IPFS_PATH=${ipfsPath} ipfs config show`).toString();
                results.identity = peerId.ID;
                results.public_key = peerId.PublicKey
                results.AgentVersion = peerId.AgentVersion
                results.Addresses = peerId.Addresses
            } catch (error) {
                console.error('Error configuring IPFS:', error);
            }
        }
        if (os.userInfo().username == "root") {
            try {
                // Reload daemon
                let reloadDaemon = "systemctl daemon-reload";
                let reloadDaemonResults = execSync(reloadDaemon);

                // Enable service 
                let enableDaemon = "systemctl enable ipfs";
                let enableDaemonResults = execSync(enableDaemon);


                // Check if daemon is running
                let findDaemon = "ps -ef | grep ipfs | grep daemon | grep -v grep | wc -l";
                let findDaemonResuls = execSync(findDaemon).toString();
                if (parseInt(findDaemonResuls) > 0) {
                    execSync("systemctl stop ipfs");
                    let findDaemonResuls = execSync(findDaemon).toString();
                }
                // Start daemon
                let startDaemon = "systemctl start ipfs";
                let startDaemonResults = execSync(startDaemon);

                if (parseInt(findDaemonResuls) ==  0) {
                    // Downloads image from ipfs as a test
                    let testDaemon = `bash -c "export IPFS_PATH=${ipfsPath} && ipfs cat /ipfs/QmSgvgwxZGaBLqkGyWemEDqikCqU52XxsYLKtdy3vGZ8uq > ${ipfsPath}/test.jpg"`;
                    let testDaemonResults = execSync(testDaemon);

                    // Time out for 2 seconds to allow the file to download
                    await new Promise(resolve => setTimeout(resolve, 5000));

                    if (fs.existsSync(`${ipfsPath}/test.jpg`)) {
                        if (fs.statSync(`${ipfsPath}/test.jpg`).size > 0) {
                            fs.unlinkSync(`${ipfsPath}/test.jpg`);
                        } else {
                            throw new Error("ipfs failed to download test file");
                        }
                        fs.unlinkSync(`${ipfsPath}/test.jpg`);
                    }
                } else {
                    throw new Error("ipfs failed to download test file");
                }
            } catch (e) {
                console.log(e);
                return e.toString();
            } finally {
                let stopDaemon = "systemctl stop ipfs";
                let stopDaemonResults = execSync(stopDaemon);
            }
        } else {
            let findDaemon = "ps -ef | grep ipfs | grep daemon | grep -v grep | wc -l";
            let findDaemonResuls = execSync(findDaemon).toString();
            if (parseInt(findDaemonResuls) > 0) {
                execSync("ps -ef | grep ipfs | grep daemon | grep -v grep | awk '{print $2}' | xargs kill -9");
                findDaemonResuls = execSync(findDaemon).toString();
            }

            console.warn('You need to be root to write to /etc/systemd/system/ipfs.service');
            let run_daemon_cmd = `IPFS_PATH=${ipfsPath} ipfs daemon --enable-pubsub-experiment --enable-gc`;
            run_daemon = exec(
                run_daemon_cmd,
                (error, stdout, stderr) => {
                    if (stdout.length > 0) {
                        console.log(stdout);
                    }
                    if (stderr.length > 0) {
                        console.error(stderr);
                        //throw new Error(stderr);
                    }
                }
            );
            await new Promise(resolve => setTimeout(resolve, 2000));
            findDaemon = "ps -ef | grep ipfs | grep daemon | grep -v grep | wc -l";
            findDaemonResuls = execSync(findDaemon).toString();
            run_daemon = run_daemon.stderr.read();
            try{
                // Start the daemon
                let testDaemon = `bash -c 'IPFS_PATH=${ipfsPath} ipfs cat /ipfs/QmSgvgwxZGaBLqkGyWemEDqikCqU52XxsYLKtdy3vGZ8uq' > ${ipfsPath}/test.jpg`;
                let testDaemonResults = execSync(testDaemon).toString();

                // Time out for 2 seconds to allow the file to download
                await new Promise(resolve => setTimeout(resolve, 2000));

                if (fs.existsSync(`${ipfsPath}/test.jpg`)) {
                    if (fs.statSync(`${ipfsPath}/test.jpg`).size > 0) {
                        fs.unlinkSync(`${ipfsPath}/test.jpg`);
                    } else {
                        fs.unlinkSync(`${ipfsPath}/test.jpg`);
                        throw new Error("ipfs failed to download test file");
                    }
                }
                else {
                    throw new Error("ipfs failed to download test file");
                }
            }
            catch(e){
                console.log(e);
                return e.toString();
            }
        }
        if (results.identity != undefined && results.identity.length == 52) {
            identity = results.identity ;
            config = JSON.parse(results.config.replace("\n", ""));
            public_key = results.public_key;
            ipfs_daemon = run_daemon;
        }
        results = {
            "config": config,
            "identity": identity,
            "public_key": public_key,
            "ipfs_daemon": ipfs_daemon
        };
        return results;
    }

    async runIPFSClusterService(options = {}) {
        let ipfsPath = options.ipfsPath || this.ipfsPath;
        ipfsPath = path.join(ipfsPath, "ipfs");
        fs.mkdirSync(ipfsPath, { recursive: true });

        const command = `IPFS_CLUSTER_PATH=${ipfsPath} ipfs-cluster-service`;
        const process = exec(command);

        process.stdout.on('data', (data) => {
            console.log(`stdout: ${data}`);
        });

        process.stderr.on('data', (data) => {
            console.error(`stderr: ${data}`);
        });

        process.on('close', (code) => {
            console.log(`ipfs-cluster-service process exited with code ${code}`);
        });

        return process;
    }

    async runIPFSClusterCtl(options = {}) {
        let ipfsPath = options.ipfsPath || this.ipfsPath;
        ipfsPath = path.join(ipfsPath, "ipfs");
        fs.mkdirSync(ipfsPath, { recursive: true });

        const command = `IPFS_CLUSTER_PATH=${ipfsPath} ipfs-cluster-ctl`;
        const process = exec(command);

        process.stdout.on('data', (data) => {
            console.log(`stdout: ${data}`);
        });

        process.stderr.on('data', (data) => {
            console.error(`stderr: ${data}`);
        });

        process.on('close', (code) => {
            console.log(`ipfs-cluster-ctl process exited with code ${code}`);
        });

        return process;
    }


    async ensureDirSync(dirPath) {
        if (!fs.existsSync(dirPath)) {
            fs.mkdirSync(dirPath, { recursive: true });
        }
    }

    async runIPFSClusterFollow(options = {}) {
        this.ensureDirSync(this.ipfsPath);
        const command = "ipfs-cluster-follow";
        let cluster_name = options.cluster_name || this.cluster_name;
        const args = [ "init", cluster_name]; // Example, adjust as needed
        const env = {ipfsPath: this.ipfsPath };
        const export_command = Object.entries(env).map(([key, value]) => `export ${key}=${value}`).join(" && ");
        const process_command = export_command + command + " " + args.join(" ");
        try {
            const { stdout, stderr } = await exec(process_command);
            console.log(stdout);
            console.error(stderr);
            return true;
        } catch (error) {
            console.error(error);
        }
    }

    async runIPFSDaemon(options = {}) {
        const ipfs_path = path.join( this.ipfsPath , "ipfs" )
        const psDaemon = "ps -ef | grep ipfs | grep daemon | grep -v grep | awk '{print $2}' | wc -l";
        const psDaemonResults = execSync(psDaemon).toString();
        if (parseInt(psDaemonResults) > 0) {
            const killDaemon = "ps -ef | grep ipfs | grep daemon | grep -v grep | awk '{print $2}' | xargs kill -9";
            const killDaemonResults = execSync(killDaemon);
        }
        const lockFile = path.join(ipfs_path, "repo.lock");
        if (fs.existsSync(lockFile)) {
            fs.unlinkSync(lockFile);
        }
        this.ensureDirSync(this.ipfsPath);
        const command = "ipfs";
        const args = ["daemon", "--enable-pubsub-experiment", "--enable-gc"];
        const env = {IPFS_PATH: ipfs_path };
        const export_command = Object.entries(env).map(([key, value]) => ` ${key}=${value}`).join(" ");
        const process_command = export_command + " " + command + " " + args.join(" ");
        try {
            let run_daemon = exec(
                process_command,
                (error, stdout, stderr) => {
                    if (stdout.length > 0) {
                        console.log(stdout);
                    }
                    if (stderr.length > 0) {
                        console.error(stderr);
                    }
                }
            );
            return true;
        } catch (error) {
            console.error(error);
        }
        finally {
            return true;
        }
    }

  
    async killProcessByPattern(pattern) {
        try {
            // Using pgrep and pkill for more precise process management
            const pids = execSync(`pgrep -f '${pattern}'`).toString().trim();
            if (pids) {
                execSync(`pkill -f '${pattern}'`);
            }
            return true;
        } catch (error) {
            console.error(`Failed to kill process with pattern ${pattern}: ${error}`);
            return false;
        }
    }

    async removeDirectorySync(dirPath) {
        // Recursive removal using rmSync in newer Node.js versions, for older versions consider rimraf package
        try {
            fs.rmSync(dirPath, { recursive: true, force: true });
            return true;
        } catch (error) {
            console.error(`Failed to remove directory ${dirPath}: ${error}`);
            return false;
        }
    }

    async uninstallIPFS(options = {}) {
        await this.killProcessByPattern('ipfs.*daemon');
        await this.killProcessByPattern('ipfs-cluster-follow');
        await this.removeDirectorySync(this.ipfsPath);
        await this.removeDirectorySync(path.join(os.homedir(), '.ipfs-cluster-follow', 'ipfs_cluster', 'api-socket'));
        return true;
    }


    async killProcessByPattern(pattern) {
        try {
            // Using pgrep and pkill for more precise process management
            const pids = execSync(`pgrep -f '${pattern}'`).toString().trim();
            if (pids) {
                execSync(`pkill -f '${pattern}'`);
            }
            return true;
        } catch (error) {
            console.error(`Failed to kill process with pattern ${pattern}: ${error}`);
            return false;
        }
    }

    async removeDirectorySync(dirPath) {
        // Recursive removal using rmSync in newer Node.js versions, for older versions consider rimraf package
        try {
            fs.rmSync(dirPath, { recursive: true, force: true });
            return true;
        } catch (error) {
            console.error(`Failed to remove directory ${dirPath}: ${error}`);
            return false;
        }
    }

    async uninstallIPFS(options = {}) {
        await this.killProcessByPattern('ipfs.*daemon');
        await this.killProcessByPattern('ipfs-cluster-follow');
        await this.removeDirectorySync(this.ipfsPath);
        await this.removeDirectorySync(path.join(os.homedir(), '.ipfs-cluster-follow', 'ipfs_cluster', 'api-socket'));
        return true;
    }

    async testUninstall(options = {}) {
        if (['leecher', 'worker', 'master'].includes(this.role)) {
            this.uninstallIPFS();
        }
        if (this.role === "master") {
            this.uninstallIPFSClusterService();
            this.uninstallIPFSClusterCtl();
        }
        if (this.role === "worker") {
            this.uninstallIPFSClusterFollow();
        }
    }

    async installExecutables(options = {}) {
        let results = {};
        if (['leecher', 'worker', 'master'].includes(this.role)) {
            let ipfs = await this.installIPFSDaemon();
            results["ipfs"] = ipfs;
        }
        if (this.role === "master") {
            let clusterService = await this.installIPFSClusterService();
            let clusterCtl = await this.installIPFSClusterCtl();
            results["clusterService"] = clusterService;
            results["clusterCtl"] = clusterCtl;
        }
        if (this.role === "worker") {
            let clusterFollow = await this.installIPFSClusterFollow();
            results["clusterFollow"] = clusterFollow;
        }
        return results;
    }


    async configExecutables(options = {}) {
        let results = {};
        if (['leecher', 'worker', 'master'].includes(this.role)) {
            let ipfsConfig = await this.configIPFS();
            results["ipfs_config"] = ipfsConfig.config;
        }
        if (this.role === "master") {
            let clusterServiceConfig = await this.configIPFSClusterService();
            let clusterCtlConfig = await this.configIPFSClusterCtl();
            results["clusterServiceConfig"] = clusterServiceConfig.config;
            results["clusterCtlConfig"] = clusterCtlConfig.config;
        }
        if (this.role === "worker") {
            let clusterFollowConfig = this.configIPFSClusterFollow();
            results["clusterFollowConfig"] = clusterFollowConfig.config;
        }
        return results;
    }

    async ipfsTestInstall() {
        try {
            execSync('which ipfs');
            return true;
        } catch (error) {
            return false;
        }
    }

    async ipfsClusterServiceTestInstall() {
        try {
            execSync('which ipfs-cluster-service');
            return true;
        } catch (error) {
            return false;
        }
    }

    async ipfsClusterFollowTestInstall() {
        try {
            execSync('which ipfs-cluster-follow');
            return true;
        } catch (error) {
            return false;
        }
    }

    async ipfsClusterCtlTestInstall() {
        try {
            execSync('which ipfs-cluster-ctl');
            return true;
        } catch (error) {
            return false;
        }
    }

    async ipgetTestInstall() {
        try {
            execSync('which ipget');
            return true;
        } catch (error) {
            return false;
        }
    }

    async installAndConfigure() {
        let results = {};
        let options = {diskStats: this.diskStats, ipfsPath: this.ipfsPath, clusterName: this.clusterName, clusterLocation: this.clusterLocation, secret: this.secret};
        try {
            if (['leecher', 'worker', 'master'].includes(this.role)) {
                // Assuming these methods are implemented and properly handle async operations
                this.installIPGet();
                this.installIPFSDaemon();
                const ipfsConfig =  await this.configIPFS(options)
                results.ipfs = true; // Assuming installation success
                results.ipfs_config = ipfsConfig;
                //await this.runIPFSDaemon();
            }
            if (this.role === 'master') {
                const clusterService = this.installIPFSClusterService(options);
                const clusterCtl = this.installIPFSClusterCtl(options);
                const clusterServiceConfig = await this.configIPFSClusterService(options);
                const clusterCtlConfig = await this.configIPFSClusterCtl(options);
                results.clusterService = clusterService;
                results.clusterCtl = clusterCtl;
                results.clusterServiceConfig = clusterServiceConfig;
                results.clusterCtlConfig = clusterCtlConfig;
                //await this.runIPFSClusterService(options);
            }
            if (this.role === 'worker') {
                const clusterFollow = this.installIPFSClusterFollow(options);
                const clusterFollowConfig = await this.configIPFSClusterFollow(options);
                results.clusterFollow = clusterFollow;
                results.clusterFollowConfig = clusterFollowConfig;
                //await this.runIPFSClusterFollow(options);
            }

            // Systemctl daemon reload
            if (os.userInfo().username == "root") {
                exec('systemctl daemon-reload');
                results.systemctl_reload = true;
            }
        } catch (error) {
            console.error('Error during installation and configuration:', error);
            return null; // Or handle the error as needed
        }

        return results;
    }

}
// run this if the script is run directly

async function main(){
    const meta = {
        role: "master",
        clusterName: "cloudkit_storage",
        clusterLocation: "/ip4/167.99.96.231/tcp/9096/p2p/12D3KooWKw9XCkdfnf8CkAseryCgS3VVoGQ6HUAkY91Qc6Fvn4yv",
        secret: "96d5952479d0a2f9fbf55076e5ee04802f15ae5452b5faafc98e2bd48cf564d3",
    };

    // Initialize the IPFS configuration manager with the provided metadata
    const install_ipfs = new InstallIPFS(undefined, meta);

    // Execute the installation and configuration process
    async function runInstallationAndConfiguration() {
        try {
            const results = await install_ipfs.installAndConfigure();
            console.log('Installation and Configuration Results:', results);
        } catch (error) {
            console.error('An error occurred during the installation and configuration process:', error);
        }
    }

    await runInstallationAndConfiguration();
}

main();
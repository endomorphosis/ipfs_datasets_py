
import { execSync, exec } from 'child_process';
import fs from 'fs';
import os from 'os';
import path from 'path';
import * as test_fio from './test_fio.js';

export class InstallIPFS {
    constructor(resources, meta = null) {
        this.resources = resources;
        this.meta = meta;
        this.ipfsTestInstall = this.ipfsTestInstall.bind(this);
        if (meta !== null) {
            this.config = meta.config ? meta.config : null;

            if (meta.role) {
                this.role = meta.role;
                if (!['master', 'worker', 'leecher'].includes(this.role)) {
                    throw new Error("role is not either master, worker, leecher");
                }
            } else {
                this.role = "leecher";
            }

            if (meta.ipfs_path) {
                this.ipfsPath = meta.ipfs_path;
                if (!fs.existsSync(this.ipfsPath)) {
                    fs.mkdirSync(this.ipfsPath, { recursive: true });
                }
                let testDisk = new test_fio.TestFio();
                this.disk_name = testDisk.disk_device_name_from_location(this.ipfsPath);
                this.disk_stats = {
                    disk_size: testDisk.disk_device_total_capacity(this.disk_name),
                    disk_used: testDisk.disk_device_used_capacity(this.disk_name),
                    disk_avail: testDisk.disk_device_avail_capacity(this.disk_name),
                    disk_name: this.disk_name
                };
            } else {
                this.ipfsPath = null;
                this.disk_stats = null;
            }

            this.cluster_name = meta.cluster_name ? meta.cluster_name : null;
            this.cluster_location = meta.cluster_location ? meta.cluster_location : "/ip4/167.99.96.231/tcp/9096/p2p/12D3KooWKw9XCkdfnf8CkAseryCgS3VVoGQ6HUAkY91Qc6Fvn4yv";

            if (['leecher', 'worker', 'master'].includes(this.role) && this.ipfsPath) {
                // Bind the methods for installing and configuring IPFS
                this.ipfs_install_command = this.installIPFSDaemon.bind(this);
                this.ipfs_config_command = this.configIPFS.bind(this);
            }

            if (this.role === "worker" && this.cluster_name && this.ipfsPath) {
                // Bind methods for worker role
                this.cluster_install = this.installIPFSClusterFollow.bind(this);
                this.cluster_config = this.configIPFSClusterFollow.bind(this);
            }

            if (this.role === "master" && this.cluster_name && this.ipfsPath) {
                // Bind methods for master role
                this.cluster_ctl_install = this.installIPFSClusterCtl.bind(this);
                this.cluster_ctl_config = this.configIPFSClusterCtl.bind(this);
                this.cluster_service_install = this.installIPFSClusterService.bind(this);
                this.cluster_service_config = this.configIPFSClusterService.bind(this);
            }
        }
    }

    async installIPFSDaemon() {
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

        if (!detect) {
            try {
                const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'ipfs-'));
                const tarFile = path.join(tmpDir, "kubo.tar.gz");
                execSync(`wget https://dist.ipfs.tech/kubo/v0.26.0/kubo_v0.26.0_linux-amd64.tar.gz -O ${tarFile}`);
                execSync(`tar -xvzf ${tarFile} -C ${tmpDir}`);
                execSync(`cd ${tmpDir}/kubo && sudo bash install.sh`);

                const results = execSync("ipfs --version").toString().trim();
                fs.writeFileSync("/etc/systemd/system/ipfs.service", "Contents of ipfs_service variable or actual service config");
                execSync("systemctl enable ipfs");

                return results.includes("ipfs");
            } catch (e) {
                console.error(e);
                return false;
            }
        }
    }

    installIPFSClusterFollow() {
        // Check if ipfs-cluster-follow is already installed
        execSync('which ipfs-cluster-follow', (error, stdout, stderr) => {
            if (!error && stdout) {
                console.log('ipfs-cluster-follow is already installed.');
                return true;
            } else {
                console.log('ipfs-cluster-follow is not installed, proceeding with installation.');
                // Downloading tarball
                const url = 'https://dist.ipfs.tech/ipfs-cluster-follow/v1.0.8/ipfs-cluster-follow_v1.0.8_linux-amd64.tar.gz';
                const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'ipfs-cluster-follow-'));
                const tarPath = path.join(tmpDir, 'ipfs-cluster-follow.tar.gz');
    
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
    
                                // Write and enable systemd service
                                const serviceConfig = '...'; // Define your systemd service file content here
                                fs.writeFileSync('/etc/systemd/system/ipfs-cluster-follow.service', serviceConfig);
                                execSync('systemctl enable ipfs-cluster-follow');
                                console.log('ipfs-cluster-follow service enabled.');
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
        });
    }
    
    async installIPFSClusterCtl() {
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

    async installIPFSClusterService() {
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
    
                        // Assuming ipfs_cluster_service is the content of your service file
                        const serviceContent = `your service file content here`;
                        fs.writeFileSync('/etc/systemd/system/ipfs-cluster-service.service', serviceContent);
                        execSync('systemctl enable ipfs-cluster-service');
                        console.log('ipfs-cluster-service service enabled.');
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

    async installIPGet() {
        try {
            // Check if ipget is already installed
            const detect = execSync("which ipget").toString().trim();
            if (detect) {
                console.log('ipget is already installed.');
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
                    const installScriptPath = path.join(tmpDir, 'ipget', 'install.sh');
                    execSync(`cd ${tmpDir}/ipget && sudo bash install.sh`);
    
                    // Update system settings
                    execSync('sudo sysctl -w net.core.rmem_max=2500000');
                    execSync('sudo sysctl -w net.core.wmem_max=2500000');
    
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
        let clusterName = options.cluster_name || this.cluster_name;
        let diskStats = options.disk_stats || this.disk_stats;
        let ipfsPath = options.ipfs_path || this.ipfsPath;
    
        // Validate required parameters
        if (!diskStats) throw new Error("disk_stats is None");
        if (!ipfsPath) throw new Error("ipfs_path is None");
    
        // Update instance properties if options are provided
        if (options.cluster_name) this.cluster_name = options.cluster_name;
        if (options.disk_stats) this.disk_stats = options.disk_stats;
        if (options.ipfs_path) this.ipfsPath = options.ipfs_path;
    
        // Ensure the IPFS path ends with "/ipfs/"
        ipfsPath = path.join(ipfsPath, "ipfs") + path.sep;
    
        let results1 = "";
    
        try {
            // Initialize the IPFS cluster service with the given IPFS path
            const command1 = `IPFS_PATH=${ipfsPath} ipfs-cluster-service init -f`;
            results1 = execSync(command1).toString();
        } catch (e) {
            results1 = e.toString();
        }
    
        return {
            results1: results1
        };
    }

    async configIPFSClusterCtl(options = {}) {
        let clusterName = options.cluster_name || this.cluster_name;
        let diskStats = options.disk_stats || this.disk_stats;
        let ipfsPath = options.ipfs_path || this.ipfsPath;

        if (!diskStats) throw new Error("disk_stats is None");
        if (!ipfsPath) throw new Error("ipfs_path is None");

        this.cluster_name = clusterName;
        this.disk_stats = diskStats;
        this.ipfsPath = ipfsPath;

        let results1;
        if (clusterName && ipfsPath && diskStats) {
            try {
                // The following command is commented out because it's a placeholder for actual implementation.
                // let command1 = `ipfs-cluster-ctl ${clusterName} init`;
                // results1 = execSync(command1).toString();
                
                let thisDir = __dirname;
                let homeDir = os.homedir();
                let configDir = path.join(homeDir, '.ipfs-cluster');
                let pebbleDir = path.join(ipfsPath, 'pebble');

                if (!fs.existsSync(configDir)) {
                    fs.mkdirSync(configDir, { recursive: true });
                }

                if (!fs.existsSync(pebbleDir)) {
                    fs.mkdirSync(pebbleDir, { recursive: true });
                }

                // Copying configuration files (service.json and peerstore) to the configuration directory.
                fs.copyFileSync(path.join(thisDir, 'service.json'), path.join(configDir, 'service.json'));
                fs.copyFileSync(path.join(thisDir, 'peerstore'), path.join(configDir, 'peerstore'));

                // Linking pebble directory
                let linkPath = path.join(configDir, 'pebble');
                if (fs.existsSync(linkPath)) {
                    fs.unlinkSync(linkPath);
                }
                fs.symlinkSync(pebbleDir, linkPath);
                
                // This is a placeholder for starting the IPFS cluster service daemon.
                // exec('ipfs-cluster-service daemon');
            } catch (e) {
                console.error(e);
                // Handle errors appropriately
            }
        }

        return {
            results1: results1
        };
    }

    configIPFSClusterFollow(options = {}) {
        let clusterName = options.cluster_name || this.cluster_name;
        let diskStats = options.disk_stats || this.disk_stats;
        let ipfsPath = options.ipfs_path || this.ipfsPath;

        if (!diskStats) throw new Error("disk_stats is None");
        if (!ipfsPath) throw new Error("ipfs_path is None");

        ipfsPath = path.join(ipfsPath, "ipfs_cluster");
        // Assuming run_ipfs_daemon is implemented elsewhere
        // this.run_ipfs_daemon();
        if (clusterName && ipfsPath && diskStats) {
            try {
                let followPath = path.join(homeDir, ".ipfs-cluster-follow", clusterName);
                let rm_command = `rm -rf ${followPath}`;
                execSync(rm_command);
                let command1 = `ipfs-cluster-follow ${clusterName} init ${ipfsPath}`;
                let results1 = execSync(command1)
                results1 = results1.toString();

                let thisDir = process.cwd();
                let clusterPath = path.join(ipfsPath, clusterName);
                let homeDir = os.homedir();

                if (!fs.existsSync(clusterPath)) {
                    fs.mkdirSync(clusterPath, { recursive: true });
                }
                if (!fs.existsSync(followPath)) {
                    fs.mkdirSync(followPath, { recursive: true });
                }

                // Copy the service and peerstore files
                fs.copyFileSync(path.join(thisDir, 'service_follower.json'), path.join(followPath, 'service.json'));
                fs.copyFileSync(path.join(thisDir, 'peerstore'), path.join(followPath, 'peerstore'));

                // Link the pebble directory if needed
                let pebbleLink = path.join(followPath, "pebble");
                let pebbleDir = path.join(clusterPath, "pebble");
                if (fs.existsSync(pebbleLink)) {
                    fs.unlinkSync(pebbleLink);
                }
                if (!fs.existsSync(pebbleDir)) {
                    fs.mkdirSync(pebbleDir, { recursive: true });
                }
                fs.symlinkSync(pebbleDir, pebbleLink);

                // Placeholder for starting the IPFS cluster follow daemon
                // let command5 = `ipfs-cluster-follow ${clusterName} run`;
                // exec(command5);
            } catch (e) {
                console.error(e);
                // Handle errors appropriately
            }
        }

        // Placeholder: results structure to mimic the Python version's output
        let results = {
            results1: "Command execution result or error message"
        };

        return results;
    }


    async configIPFS(options = {}) {
        let diskStats = options.disk_stats || this.disk_stats;
        let ipfsPath = options.ipfs_path || this.ipfsPath;

        if (!diskStats) throw new Error("disk_stats is None");
        if (!ipfsPath) throw new Error("ipfs_path is None");

        ipfsPath = path.join(ipfsPath, "ipfs");
        fs.mkdirSync(ipfsPath, { recursive: true });

        let results = {
            config: null,
            identity: null,
            public_key: null
        };

        if (diskStats && ipfsPath) {
            try {
                execSync(`IPFS_PATH=${ipfsPath} ipfs init --profile=badgerds`);
                let peerId = execSync(`IPFS_PATH=${ipfsPath} ipfs id`).toString();
                execSync(`IPFS_PATH=${ipfsPath} ipfs config profile apply badgerds`);

                // Calculate available disk space and adjust storage allocation
                let diskAvailable = parseFloat(diskStats.disk_avail);
                let minFreeSpace = 32 * 1024 * 1024 * 1024; // 32 GB
                if (diskAvailable > minFreeSpace) {
                    let allocate = Math.ceil(((diskAvailable - minFreeSpace) * 0.8) / 1024 / 1024 / 1024);
                    execSync(`IPFS_PATH=${ipfsPath} ipfs config Datastore.StorageMax ${allocate}GB`);
                }

                // Load peer list and add to bootstrap
                let peerListPath = path.join(__dirname, "peerstore");
                if (fs.existsSync(peerListPath)) {
                    let peerList = fs.readFileSync(peerListPath).toString().split("\n");
                    peerList.forEach(peer => {
                        if (peer) {
                            execSync(`IPFS_PATH=${ipfsPath} ipfs bootstrap add ${peer}`);
                        }
                    });
                }

                // Assuming ipfs_service_text contains the systemd service configuration
                // if (os.geteuid() === 0) {
                //     fs.writeFileSync("/etc/systemd/system/ipfs.service", ipfs_service_text);
                // }

                results.config = execSync(`IPFS_PATH=${ipfsPath} ipfs config show`).toString();
                results.identity = peerId.match(/"ID":\s?"([^"]+)"/)[1];
                results.public_key = peerId.match(/"PublicKey":\s?"([^"]+)"/)[1];
            } catch (error) {
                console.error('Error configuring IPFS:', error);
            }
        }

        return results;
    }


    async runIPFSClusterService(options = {}) {
        let ipfsPath = options.ipfs_path || this.ipfsPath;
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
        let ipfsPath = options.ipfs_path || this.ipfsPath;
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

  async runIPFSClusterFollow() {
    this.ensureDirSync(this.ipfsPath);
    const command = "ipfs-cluster-follow";
    const args = ["mycluster", "init", this.ipfsPath]; // Example, adjust as needed
    const process = spawn(command, args, { env: { ...process.env, IPFS_PATH: this.ipfsPath } });

    process.stdout.on('data', data => console.log(data.toString()));
    process.stderr.on('data', data => console.error(data.toString()));

    return process;
  }

  async runIPFSDaemon() {
    this.ensureDirSync(this.ipfsPath);
    const command = "ipfs";
    const args = ["daemon", "--enable-pubsub-experiment"];
    const process = spawn(command, args, { env: { ...process.env, IPFS_PATH: this.ipfsPath } });

    process.stdout.on('data', data => console.log(data.toString()));
    process.stderr.on('data', data => console.error(data.toString()));

    return process;
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

    async uninstallIPFS() {
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

    async uninstallIPFS() {
        await this.killProcessByPattern('ipfs.*daemon');
        await this.killProcessByPattern('ipfs-cluster-follow');
        await this.removeDirectorySync(this.ipfsPath);
        await this.removeDirectorySync(path.join(os.homedir(), '.ipfs-cluster-follow', 'ipfs_cluster', 'api-socket'));
        return true;
    }

    async testUninstall() {
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

    async installExecutables() {
        let results = {};
        if (['leecher', 'worker', 'master'].includes(this.role)) {
            let ipfs = await this.installIPFSDaemon();
            results["ipfs"] = ipfs;
        }
        if (this.role === "master") {
            let clusterService = await this.installIPFSClusterService();
            let clusterCtl = await this.installIPFSClusterCtl();
            results["cluster_service"] = clusterService;
            results["cluster_ctl"] = clusterCtl;
        }
        if (this.role === "worker") {
            let clusterFollow = await this.installIPFSClusterFollow();
            results["cluster_follow"] = clusterFollow;
        }
        return results;
    }


    async configExecutables() {
        let results = {};
        if (['leecher', 'worker', 'master'].includes(this.role)) {
            let ipfsConfig = await this.configIPFS();
            results["ipfs_config"] = ipfsConfig.config;
        }
        if (this.role === "master") {
            let clusterServiceConfig = await this.configIPFSClusterService();
            let clusterCtlConfig = await this.configIPFSClusterCtl();
            results["cluster_service_config"] = clusterServiceConfig.config;
            results["cluster_ctl_config"] = clusterCtlConfig.config;
        }
        if (this.role === "worker") {
            let clusterFollowConfig = this.configIPFSClusterFollow();
            results["cluster_follow_config"] = clusterFollowConfig.config;
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
        try {
            if (['leecher', 'worker', 'master'].includes(this.role)) {
                // Assuming these methods are implemented and properly handle async operations
                this.installIPGet();
                this.installIPFSDaemon();
                const ipfsConfig = this.configIPFS();

                results.ipfs = true; // Assuming installation success
                results.ipfs_config = ipfsConfig;
                this.runIPFSDaemon();
            }
            if (this.role === 'master') {
                const clusterService = this.installIPFSClusterService();
                const clusterCtl = this.installIPFSClusterCtl();
                const clusterServiceConfig = this.configIPFSClusterService();
                const clusterCtlConfig = this.configIPFSClusterCtl();

                results.cluster_service = clusterService;
                results.cluster_ctl = clusterCtl;
                results.cluster_service_config = clusterServiceConfig;
                results.cluster_ctl_config = clusterCtlConfig;
            }
            if (this.role === 'worker') {
                const clusterFollow = this.installIPFSClusterFollow();
                const clusterFollowConfig = this.configIPFSClusterFollow();

                results.cluster_follow = clusterFollow;
                results.cluster_follow_config = clusterFollowConfig;
            }

            // Systemctl daemon reload
            execAsync('systemctl daemon-reload');
            results.systemctl_reload = true;
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
        role: "worker",
        clusterName: "cloudkit_storage",
        clusterLocation: "/ip4/167.99.96.231/tcp/9096/p2p/12D3KooWKw9XCkdfnf8CkAseryCgS3VVoGQ6HUAkY91Qc6Fvn4yv",
        // Alternative cluster location (commented out in the example)
        // clusterLocation: "/ip4/167.99.96.231/udp/4001/quic-v1/p2p/12D3KooWS9pEXDb2FEsDv9TH4HicZgwhZtthHtSdSfyKKDnkDu8D",
        ipfsPath: "/home/kensix/.cache/ipfs/",
    };

    // Initialize the IPFS configuration manager with the provided metadata
    const configManager = new IPFSConfigManager(meta.role, meta.clusterName, meta.ipfsPath);

    // Execute the installation and configuration process
    async function runInstallationAndConfiguration() {
        try {
            const results = await configManager.installAndConfigure();
            console.log('Installation and Configuration Results:', results);
        } catch (error) {
            console.error('An error occurred during the installation and configuration process:', error);
        }
    }

    await runInstallationAndConfiguration();
}

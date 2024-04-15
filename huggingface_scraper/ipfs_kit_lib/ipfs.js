import { exec, execSync } from 'child_process';
import fs from 'fs';
import os from 'os';
import path from 'path';

export class ipfs {
    constructor(resources, meta) {
        if (meta !== null) {
            if ('config' in meta) {
                if (meta['config'] !== null) {
                    this.config = meta['config'];
                }
            }
            if ('role' in meta) {
                if (meta['role'] !== null) {
                    this.role = meta['role'];
                    if (!['master', 'worker', 'leecher'].includes(this.role)) {
                        throw new Error('role is not either master, worker, leecher');
                    } else {
                        this.role = 'leecher';
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
                    this.ipfsPath = meta['ipfs_path'];
                }
            }
            if (this.role === 'leecher' || this.role === 'worker' || this.role === 'master') {
                this.commands = {};
            }
        }
    }

    async daemon_start(kwargs = {}) {
        let cluster_name;
        if ('cluster_name' in this) {
            cluster_name = this.cluster_name;
        }
        if ('cluster_name' in kwargs) {
            cluster_name = kwargs['cluster_name'];
        }

        let results1 = null;
        let results2 = null;
        let ipfs_ready = false;

        // Run this if root and check if it passes 
        if (os.userInfo().uid === 0) {
            try {
                const command1 = "systemctl start ipfs";
                exec(command1, (error, stdout, stderr) => {
                    if (error) {
                        console.log(`Error starting ipfs: ${error.message}`);
                        results1 = error.message;
                    } else {
                        results1 = stdout;

                        const command2 = "ps -ef | grep ipfs | grep daemon | grep -v grep | wc -l";
                        exec(command2, (error, stdout, stderr) => {
                            if (!error && parseInt(stdout.trim()) > 0) {
                                ipfs_ready = true;
                            }
                        });
                    }
                });
            } catch (error) {
                results1 = error.message;
            }
        }

        // Run this if user is not root or root user fails check if it passes
        if (os.userInfo().uid !== 0 || ipfs_ready === false) {
            try {
                const command2 = `export IPFS_PATH=${path.resolve(path.join(this.ipfsPath,"ipfs"))} && ipfs daemon --enable-gc --enable-pubsub-experiment`;
                //const execute2 = execSync(command2);
                const execute2 = exec(command2, (error, stdout, stderr) => {
                    if (error) {
                        console.log(`Error starting ipfs: ${error.message}`);
                        results1 = error.message;
                    }
                });
                //results2 = execute2.toString();
            } catch (error) {
                console.log(`Error starting ipfs: ${error.message}`);
                results2 = error.message;
            }
        }

        const results = {
            "systemctl": results1,
            "bash": results2
        };

        return results;
    }


    async daemon_stop(kwargs = {}) {
        let cluster_name;
        if ('cluster_name' in this) {
            cluster_name = this.cluster_name;
        }
        if ('cluster_name' in kwargs) {
            cluster_name = kwargs['cluster_name'];
        }

        let results1 = null;
        let results2 = null;
        let ipfs_ready = false;

        // Run this if root and check if it passes 
        if (os.userInfo().uid === 0) {
            try {
                const command1 = "systemctl stop ipfs";
                exec(command1, (error, stdout, stderr) => {
                    if (error) {
                        results1 = error.message;
                    } else {
                        results1 = stdout;

                        const command2 = "ps -ef | grep ipfs | grep daemon | grep -v grep | wc -l";
                        exec(command2, (error, stdout, stderr) => {
                            if (!error && parseInt(stdout.trim()) === 0) {
                                ipfs_ready = true;
                            }
                        });
                    }
                });
            } catch (error) {
                results1 = error.message;
            }
        }

        // Run this if user is not root or root user fails check if it passes
        if (os.userInfo().uid !== 0 || ipfs_ready === false) {
            try {
                const command2 = "ps -ef | grep ipfs | grep daemon | grep -v grep | awk '{print $2}' | xargs kill -9";
                exec(command2, (error, stdout, stderr) => {
                    if (error) {
                        results2 = error.message;
                    } else {
                        results2 = stdout;
                    }
                });
            } catch (error) {
                results2 = error.message;
            }
        }

        const results = {
            "systemctl": results1,
            "bash": results2
        };

        return results;
    }


    async ipfs_resize(size, kwargs = {}) {
        const command1 = this.daemon_stop();
        const command2 = `ipfs config --json Datastore.StorageMax ${size}GB`;
        const results1 = await new Promise((resolve, reject) => {
            exec(command2, (error, stdout, stderr) => {
                if (error) {
                    reject(error.message);
                } else {
                    resolve(stdout);
                }
            });
        });
        const command3 = this.daemon_start();
        return results1;
    }

    async ipfs_ls_pin(kwargs = {}) {
        if ('hash' in kwargs) {
            const hash = kwargs['hash'];
            let request1 = null;
            try {
                request1 = await this.ipfs_execute({
                    "command": "cat",
                    "hash": hash
                });
            } catch (error) {
                console.error(error);
            }
            if (request1 !== null) {
                return request1;
            }
            let request2 = null;
            try {
                const command = `ipfs cat ${hash}`;
                request2 = await new Promise((resolve, reject) => {
                    exec(command, (error, stdout, stderr) => {
                        if (error) {
                            reject(error.message);
                        } else {
                            resolve(stdout);
                        }
                    });
                });
            } catch (error) {
                console.error(error);
            }
            if (request2 !== null) {
                return request2;
            }
        }
        throw new Error("hash not found");
    }


    async ipfs_get_pinset(kwargs = {}) {
        const this_tempfile = path.join(os.tmpdir(), 'temp.txt');
        const command = `export IPFS_PATH=${this.ipfsPath}ipfs/ && ipfs pin ls -s > ${this_tempfile}`;
        await new Promise((resolve, reject) => {
            exec(command, (error, stdout, stderr) => {
                if (error) {
                    reject(error.message);
                } else {
                    resolve(stdout);
                }
            });
        });
        const file_data = fs.readFileSync(this_tempfile, 'utf8');
        const pinset = {};
        const parse_results = file_data.split("\n");
        for (let i = 0; i < parse_results.length; i++) {
            const data = parse_results[i].split(" ");
            if (data.length > 1) {
                pinset[data[0]] = data[1];
            }
        }
        return pinset;
    }

    async ipfs_add_pin(pin, kwargs = {}) {
        const dirname = path.dirname(__filename);
        let result1;
        try {
            const command1 = `export IPFS_PATH=${this.ipfsPath}ipfs/ && cd ${this.ipfsPath}ipfs/ && ipfs pin add ${pin}`;
            result1 = await new Promise((resolve, reject) => {
                exec(command1, (error, stdout, stderr) => {
                    if (error) {
                        reject(error.message);
                    } else {
                        resolve(stdout);
                    }
                });
            });
        } catch (error) {
            result1 = error;
        }
        return result1;
    }

    async ipfs_mkdir(path, kwargs = {}) {
        const this_path_split = path.split("/");
        let this_path = "";
        const results = [];
        for (let i = 0; i < this_path_split.length; i++) {
            this_path += this_path_split[i] + "/";
            const command1 = `export IPFS_PATH=${this.ipfsPath}ipfs/ && ipfs files mkdir ${this_path}`;
            const result1 = await new Promise((resolve, reject) => {
                exec(command1, (error, stdout, stderr) => {
                    if (error) {
                        reject(error.message);
                    } else {
                        resolve(stdout);
                    }
                });
            });
            results.push(result1);
        }
        return results;
    }


    async ipfs_add_path2(path, kwargs = {}) {
        let ls_dir = [];
        if (!fs.existsSync(path)) {
            throw new Error("path not found");
        }
        if (fs.lstatSync(path).isFile()) {
            ls_dir = [path];
            await this.ipfs_mkdir(path.dirname(path), kwargs);
		} else if (fs.lstatSync(path).isDirectory()) {
            await this.ipfs_mkdir(path, kwargs);
            ls_dir = fs.readdirSync(path).map(file => path.join(path, file));
        }
        const results1 = [];
        for (let i = 0; i < ls_dir.length; i++) {
            let argstring = ` --to-files=${ls_dir[i]} `;
            const command1 = `ipfs add ${argstring}${ls_dir[i]}`;
            const result1 = await new Promise((resolve, reject) => {
                exec(command1, (error, stdout, stderr) => {
                    if (error) {
                        reject(error.message);
                    } else {
                        resolve(stdout);
                    }
                });
            });
            results1.push(result1);
        }
        return results1;
    }

    async ipfs_add_path(path, kwargs = {}) {
        let argstring = "";
        let ls_dir = path;
        if (!fs.existsSync(path)) {
            throw new Error("path not found");
        }
        if (fs.lstatSync(path).isFile()) {
            await this.ipfs_mkdir(path.dirname(path), kwargs);
        } else if (fs.lstatSync(path).isDirectory()) {
            await this.ipfs_mkdir(path, kwargs);
        }
        argstring += `--recursive --to-files=${ls_dir} `;
        const command1 = `ipfs add ${argstring}${ls_dir}`;
        const result1 = await new Promise((resolve, reject) => {
            exec(command1, (error, stdout, stderr) => {
                if (error) {
                    reject(error.message);
                } else {
                    resolve(stdout);
                }
            });
        });
        const results = {};
        const result_split = result1.split("\n");
        for (let i = 0; i < result_split.length; i++) {
            const parts = result_split[i].split(" ");
            if (parts.length > 1) {
                results[parts[2]] = parts[1];
            }
        }
        return results;
    }


    async ipfs_remove_path(path, kwargs = {}) {
        let result1 = null;
        let result2 = null;
        const stats = await this.ipfs_stat_path(path, kwargs);
        if (Object.keys(stats).length === 0) {
            throw new Error("path not found");
        }
        const pin = stats['pin'];
        if (stats["type"] === "file") {
            const command1 = `export IPFS_PATH=${this.ipfsPath}ipfs/ && ipfs files rm ${path}`;
            result1 = await new Promise((resolve, reject) => {
                exec(command1, (error, stdout, stderr) => {
                    if (error) {
                        reject(error.message);
                    } else {
                        resolve(stdout);
                    }
                });
            });
            const command2 = `export IPFS_PATH=${this.ipfsPath}ipfs/ && ipfs pin rm ${pin}`;
            result2 = await new Promise((resolve, reject) => {
                exec(command2, (error, stdout, stderr) => {
                    if (error) {
                        reject(error.message);
                    } else {
                        resolve(stdout);
                    }
                });
            });
            result2 = result2.split("\n");
        } else if (stats["type"] === "directory") {
            const contents = await this.ipfs_ls_path(path, kwargs);
            for (let i = 0; i < contents.length; i++) {
                if (contents[i].length > 0) {
                    result1 = await this.ipfs_remove_path(`${path}/${contents[i]}`, kwargs);
                }
            }
        } else {
            throw new Error("unknown path type");
        }
        const results = {
            "files_rm": result1,
            "pin_rm": result2
        };
        return results;
    }

    async ipfs_stat_path(path, kwargs = {}) {
        try {
            const stat1 = `export IPFS_PATH=${this.ipfsPath}ipfs/ && ipfs files stat ${path}`;
            const results1 = await new Promise((resolve, reject) => {
                exec(stat1, (error, stdout, stderr) => {
                    if (error) {
                        reject(error.message);
                    } else {
                        resolve(stdout);
                    }
                });
            });
            const results1Split = results1.split("\n");
            if (results1Split.length > 0 && Array.isArray(results1Split)) {
                const pin = results1Split[0];
                const size = parseFloat(results1Split[1].split(": ")[1]);
                const culumulative_size = parseFloat(results1Split[2].split(": ")[1]);
                const child_blocks = parseFloat(results1Split[3].split(": ")[1]);
                const type = results1Split[4].split(": ")[1];
                const results = {
                    "pin": pin,
                    "size": size,
                    "culumulative_size": culumulative_size,
                    "child_blocks": child_blocks,
                    "type": type
                };
                return results;
            } else {
                return false;
            }
        } catch (error) {
            console.error(error.message);
            return false;
        }
    }


    async ipfs_name_resolve(kwargs = {}) {
        let result1 = null;
        try {
            const command1 = `export IPFS_PATH=${this.ipfsPath}/ipfs/ && ipfs name resolve ${kwargs['path']}`;
            result1 = await new Promise((resolve, reject) => {
                exec(command1, (error, stdout, stderr) => {
                    if (error) {
                        reject(error.message);
                    } else {
                        resolve(stdout);
                    }
                });
            });
        } catch (error) {
            result1 = error.message;
        }
        return result1;
    }

    async ipfs_name_publish(path, kwargs = {}) {
        if (!fs.existsSync(path)) {
            throw new Error("path not found");
        }
        let results1 = null;
        let results2 = null;
        try {
            const command1 = `export IPFS_PATH=${this.ipfsPath}/ipfs/ && ipfs add --cid-version 1 ${path}`;
            results1 = await new Promise((resolve, reject) => {
                exec(command1, (error, stdout, stderr) => {
                    if (error) {
                        reject(error.message);
                    } else {
                        resolve(stdout);
                    }
                });
            });
            results1 = results1.trim();
            const cid = results1.split(" ")[1];
            const fname = results1.split(" ")[2];
            results1 = {
                [fname]: cid
            };
        } catch (error) {
            results1 = error.message;
        }

        try {
            const command2 = `export IPFS_PATH=${this.ipfsPath}/ipfs/ && ipfs name publish ${results1[Object.keys(results1)[0]]}`;
            results2 = await new Promise((resolve, reject) => {
                exec(command2, (error, stdout, stderr) => {
                    if (error) {
                        reject(error.message);
                    } else {
                        resolve(stdout);
                    }
                });
            });
            results2 = results2.split(":")[0].split(" ")[results2.split(":")[0].split(" ").length - 1];
        } catch (error) {
            results2 = error.message;
        }

        const results = {
            "add": results1,
            "publish": results2
        };
        return results;
    }


    async ipfs_ls_path(path, kwargs = {}) {
        let results1 = null;
        try {
            const stat1 = `export IPFS_PATH=${this.ipfsPath}ipfs/ && ipfs files ls ${path}`;
            results1 = await new Promise((resolve, reject) => {
                exec(stat1, (error, stdout, stderr) => {
                    if (error) {
                        reject(error.message);
                    } else {
                        resolve(stdout);
                    }
                });
            });
            results1 = results1.split("\n");
        } catch (error) {
            results1 = error.message;
        }
        if (results1.length > 0 && Array.isArray(results1)) {
            return results1;
        } else {
            return false;
        }
    }

    async ipfs_remove_pin(cid, kwargs = {}) {
        let result1 = null;
        let stdout = null;
        let stderr = null;
        try {
            const command1 = `export IPFS_PATH=${this.ipfsPath}ipfs/ && ipfs pin rm ${cid}`;
            const output = await new Promise((resolve, reject) => {
                exec(command1, (error, stdout, stderr) => {
                    if (error) {
                        reject({ stdout, stderr });
                    } else {
                        resolve({ stdout, stderr });
                    }
                });
            });
            stdout = output.stdout;
            stderr = output.stderr;
        } catch (error) {
            result1 = error.message;
        }
        if (stdout && stdout.includes("unpinned")) {
            result1 = true;
        }
        return result1;
    }


    async ipfs_remove_pin(cid, kwargs = {}) {
        let result1 = null;
        let stdout = null;
        let stderr = null;
        try {
            const command1 = `export IPFS_PATH=${this.ipfsPath}ipfs/ && ipfs pin rm ${cid}`;
            const output = await new Promise((resolve, reject) => {
                exec(command1, (error, stdout, stderr) => {
                    if (error) {
                        reject({ stdout, stderr });
                    } else {
                        resolve({ stdout, stderr });
                    }
                });
            });
            stdout = output.stdout;
            stderr = output.stderr;
        } catch (error) {
            result1 = error.message;
        }
        if (stdout && stdout.includes("unpinned")) {
            result1 = true;
        }
        return result1;
    }

    async test_ipfs() {
        let detect = null;
        try {
            detect = await new Promise((resolve, reject) => {
                exec("which ipfs", (error, stdout, stderr) => {
                    if (error) {
                        reject(error.message);
                    } else {
                        resolve(stdout);
                    }
                });
            });
        } catch (error) {
            detect = error.message;
        }
        if (detect && detect.length > 0) {
            return true;
        } else {
            return false;
        }
    }

    async ipfs_execute(command, kwargs = {}) {
        if (typeof kwargs !== 'object') {
            throw new Error("kwargs must be an object");
        }

        const executable = "ipfs ";
        const options = ["add", "pin", "unpin", "get", "cat", "ls", "refs", "refs-local", "refs-local-recursive", "refs-remote", "refs-remote-recursive", "repo", "version"];
        let execute = "";

        if (command === "add") {
            execute = `${executable}add ${kwargs.file}`;
        }

        if (!kwargs.hash) {
            throw new Error("hash not found in kwargs");
        }

        if (command === "get") {
            execute = `${executable}get ${kwargs.hash} -o ${kwargs.file}`;
        }

        if (command === "pin") {
            execute = `${executable}pin add ${kwargs.hash}`;
        }

        if (command === "unpin") {
            execute = `${executable}pin rm ${kwargs.hash}`;
        }

        if (command === "cat") {
            execute = `${executable}cat ${kwargs.hash}`;
        }

        if (command === "ls") {
            execute = `${executable}ls ${kwargs.hash}`;
        }

        if (command === "refs") {
            execute = `${executable}refs ${kwargs.hash}`;
        }

        if (command === "refs-local") {
            execute = `${executable}refs local ${kwargs.hash}`;
        }

        if (command === "refs-local-recursive") {
            execute = `${executable}refs local --recursive ${kwargs.hash}`;
        }

        if (command === "refs-remote") {
            execute = `${executable}refs remote ${kwargs.hash}`;
        }

        if (command === "refs-remote-recursive") {
            execute = `${executable}refs remote --recursive ${kwargs.hash}`;
        }

        if (command === "repo") {
            execute = `${executable}repo ${kwargs.hash}`;
        }

        if (command === "version") {
            execute = `${executable}version ${kwargs.hash}`;
        }

        try {
            const output = await new Promise((resolve, reject) => {
                exec(execute, (error, stdout, stderr) => {
                    if (error) {
                        reject(error.message);
                    } else {
                        resolve(stdout);
                    }
                });
            });
            console.log(`stdout: ${output}`);
            return output;
        } catch (error) {
            console.log(`error: ${error}`);
            return error;
        }
    }

}
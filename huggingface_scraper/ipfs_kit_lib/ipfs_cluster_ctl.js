class IPFSClusterCtl {
    constructor(resources, meta = null) {
        this.config = {};
        this.role = "leecher"; // Default role

        if (meta !== null) {
            if ("config" in meta && meta['config'] !== null) {
                this.config = meta['config'];
            }
            if ("role" in meta && meta['role'] !== null) {
                if (["master", "worker", "leecher"].includes(meta['role'])) {
                    this.role = meta['role'];
                } else {
                    throw new Error("role is not either master, worker, leecher");
                }
            }
        }

        // Any additional setup for roles can be added here
        if (["leecher", "worker", "master"].includes(this.role)) {
            // Perform role-specific initialization
        }
    }
    
    // Helper function to recursively walk through directory
    walkSync(dir, fileList = []) {
        fs.readdirSync(dir).forEach(file => {
            const filePath = path.join(dir, file);
            if (fs.statSync(filePath).isDirectory()) {
                this.walkSync(filePath, fileList);
            } else {
                fileList.push(filePath);
            }
        });
        return fileList;
    }

    ipfsClusterCtlAddPin(dirPath, metadata = {}) {
        if (!fs.existsSync(dirPath)) {
            throw new Error("Path not found");
        }
        
        const files = this.walkSync(dirPath);
        const results = files.map(file => {
            const relativePath = path.relative(dirPath, file);
            let argString = metadata[relativePath] ? ` --metadata ${metadata[relativePath]}` : "";
            let command = `ipfs-cluster-ctl pin add ${file}${argString}`;
            try {
                const output = execSync(command).toString();
                return output;
            } catch (error) {
                console.error(`Failed to execute command for file ${file}: ${error}`);
                return null;
            }
        });

        return results.filter(result => result !== null);
    }


    ipfsClusterCtlRemovePin(dirPath) {
        if (!fs.existsSync(dirPath)) {
            throw new Error("Path not found");
        }

        const files = this.walkSync(dirPath);
        const results = files.map(file => {
            let command = `ipfs-cluster-ctl pin rm ${file}`;
            try {
                const output = execSync(command).toString();
                return `Unpinned: ${file}`;
            } catch (error) {
                console.error(`Failed to execute command for file ${file}: ${error}`);
                return `Failed to unpin: ${file}`;
            }
        });

        return results;
    }


    // Simplified directory traversal for demonstration
    getDirectories(basePath) {
        return fs.readdirSync(basePath, { withFileTypes: true })
            .filter(dirent => dirent.isDirectory())
            .map(dirent => path.join(basePath, dirent.name));
    }

    ipfsClusterCtlAddPinRecursive(dirPath, metadata = {}) {
        if (!fs.existsSync(dirPath)) {
            throw new Error("Path not found");
        }

        // If the path is a directory, traverse and pin each subdirectory recursively.
        // Otherwise, pin the file directly.
        let targets = fs.statSync(dirPath).isDirectory() ? this.getDirectories(dirPath) : [dirPath];
        const results = targets.map(target => {
            const relativePath = path.relative(dirPath, target);
            let argString = metadata[relativePath] ? ` --metadata ${metadata[relativePath]}` : "";
            let command = `ipfs-cluster-ctl pin add -r ${target}${argString}`;

            try {
                const output = execSync(command, { encoding: 'utf-8' });
                return `Pinned: ${target}`;
            } catch (error) {
                console.error(`Failed to execute command for ${target}: ${error.message}`);
                return `Failed to pin: ${target}`;
            }
        });

        return results;
    }


    ipfs_cluster_ctl_execute(args) {
        if (!this.options.includes(args[0])) {
            console.error(`"${args[0]}" is not a valid command.`);
            return;
        }

        let command = `${this.executable}${args[0]}`;

        if (args[1]) {
            command += ` ${args[1]}`;

            // Validate subcommands for certain options
            switch (args[0]) {
                case "peers":
                    if (!["ls", "rm"].includes(args[1])) {
                        throw new Error("Invalid option for 'peers'");
                    }
                    break;
                case "pin":
                    if (!["add", "rm", "ls", "update"].includes(args[1])) {
                        throw new Error("Invalid option for 'pin'");
                    }
                    break;
                case "health":
                    if (!["graph", "metrics", "alerts"].includes(args[1])) {
                        throw new Error("Invalid option for 'health'");
                    }
                    break;
                case "ipfs":
                    if (args[1] !== "gc") {
                        throw new Error("Invalid option for 'ipfs'");
                    }
                    break;
            }
        }

        // Special handling for the 'add' command with multiple options
        if (args[0] === "add" && args.length > 2) {
            const path = args.pop(); // Assuming the last argument is always the path
            const options = args.slice(1).join(" ");
            command = `${this.executable}add ${options} ${path}`;
        }

        exec(command, (error, stdout, stderr) => {
            if (error) {
                console.error(`Error executing command: ${error}`);
                return;
            }
            if (stderr) {
                console.error(`stderr: ${stderr}`);
                return;
            }
            console.log(`stdout: ${stdout}`);
        });
    }


    getPinset() {
        // Create a temporary file path
        const tempFile = path.join(os.tmpdir(), `pinset-${Date.now()}.txt`);
        try {
            // Redirect output of the command to the temporary file
            execSync(`ipfs-cluster-ctl pin ls > ${tempFile}`);
            
            // Read and parse the temporary file
            const fileData = fs.readFileSync(tempFile, 'utf8');
            const pinset = this.parsePinsetData(fileData);
            
            // Clean up the temporary file
            fs.unlinkSync(tempFile);

            return pinset;
        } catch (error) {
            console.error(`Failed to get pinset: ${error.message}`);
            // Clean up the temporary file in case of an error
            if (fs.existsSync(tempFile)) {
                fs.unlinkSync(tempFile);
            }
            return {};
        }
    }

    parsePinsetData(fileData) {
        const pinset = {};
        const parseResults = fileData.split("\n");
        parseResults.forEach(resultLine => {
            const resultsList = resultLine.split(" | ");
            if (resultsList.length > 1) { // Ensure it's not an empty line
                const resultDict = {};
                resultsList.forEach(cell => {
                    const cellSplit = cell.split(":").map(part => part.trim());
                    if (cellSplit.length > 1) {
                        resultDict[cellSplit[0]] = cellSplit[1];
                    }
                });
                if (Object.keys(resultDict).length > 0) {
                    pinset[resultsList[0]] = resultDict;
                }
            }
        });
        return pinset;
    }

    ipfsClusterCtlStatus() {
        try {
            const command = "ipfs-cluster-ctl status";
            const results = execSync(command, { encoding: 'utf8' }); // Directly get the output as a string
            return results;
        } catch (error) {
            console.error(`Error executing ipfs-cluster-ctl status: ${error.message}`);
            return null;
        }
    }

    testIPFSClusterCtl() {
        return new Promise((resolve, reject) => {
            exec("which ipfs-cluster-ctl", (error, stdout) => {
                if (error) {
                    resolve(false);
                } else {
                    resolve(stdout.trim().length > 0);
                }
            });
        });
    }
}

if (require.main === module) {

    (async () => {
        const thisIpfsClusterCtl = new IPFSClusterCtl();
        const results = await thisIpfsClusterCtl.testIPFSClusterCtl();
        console.log(results);

        if (results) {
            const status = thisIpfsClusterCtl.ipfsClusterCtlStatus();
            console.log(status);
        } else {
            console.log("ipfs-cluster-ctl is not installed.");
        }
    })();

}
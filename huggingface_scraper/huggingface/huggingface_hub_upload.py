from huggingface_hub import HfApi, HfFolder
import os
import sys 


def upload_folder_to_hf_hub(folder_path, repo_name, hf_username, hf_token, this_organization):
    """
    Uploads the contents of a folder to a Hugging Face Hub repository.

    Parameters:
    folder_path (str): The path to the folder to upload.
    repo_name (str): The name of the repository on Hugging Face Hub.
    hf_username (str): Your Hugging Face username.
    hf_token (str): Your Hugging Face API token.
    """

    dataset = False
    buildDir = "/tmp/build/"
    # Initialize Hugging Face API
    api = HfApi()
    HfFolder.save_token(hf_token)
    # Login to Hugging Face
    ## find if the repo exists
    repo_id = hf_username+"/"+repo_name
    print("repo_id", repo_id)
    repo_exists = False

    repo_from = ""
    try:
        repo = api.model_info(repo_id=repo_id)
        print("repo", repo)
        ## try to assign repo_From repo.modelId but catch errors 
        repo_from = repo.modelId
        if isinstance(repo_from, str) and len(repo_from) > 0:
            repo_exists = True
        else:
            repo_exists = False

    except Exception:
        pass


    if repo_exists:
        print(f"Repository {repo_id} already exists")
        repo_url = " https://huggingface.co/" + repo_id

    else:
        repo_url = api.create_repo( repo_id=hf_username+"/"+repo_name  , private=False, exist_ok=True, token=hf_token)
        print(f"Repository URL: {repo_url}")

    if(folder_path.endswith("/")):
        parentname = os.path.dirname(os.path.dirname(folder_path))
    else:
        parentname = os.path.dirname(folder_path)
    print("parentname", parentname)
    basename = folder_path.replace(parentname , "")
    basename = basename.replace("/","")
    print("basename", basename)
    folder_path = os.path.join(parentname,basename)
    print ("folder_path", folder_path)

    ##print(f"Cloning repository {folder_path} ... to {repo_url}")
    ## check if repo exists in the local folder
    if os.path.exists(folder_path):
        print(f"folder {repo_name} already exists")
        ## check if empty
        if len(os.listdir(folder_path)) == 0:
            command_1 = "rm -rf " + folder_path
            print("Empty repo")
            print("command_1", command_1)
            os.system(command_1)
            os.system("cp -r " + buildDir + "/" + repo_name + "/ " + folder_path )
            api.upload_folder(
                folder_path=folder_path,
                path_in_repo="",  # root of the repo
                repo_id=repo_id,
                repo_type="model"
            )
        else:
            if os.path.exists(folder_path + "/.gitignore"):
                gitIgnore = open(folder_path + "/.gitignore", "r").read().splitlines()[0]
                print("gitIgnore: ", gitIgnore)
                api.upload_folder(
                    folder_path=folder_path,
                    path_in_repo="",  # root of the repo
                    repo_id=repo_id,
                    repo_type="model",
                    delete_patterns="*",
                    ignore_patterns="*/*"

                )
            else:
                api.upload_folder(
                    folder_path=folder_path,
                    path_in_repo="",  # root of the repo
                    repo_id=repo_id,
                    repo_type="model"
                )
    else:
        command_3 = "cp -r " + buildDir + "/" + repo_name + "/ " + folder_path
        print("command_3", command_3)
        os.system(command_3)
        api.upload_folder(
            folder_path=folder_path,
            path_in_repo="",  # root of the repo
            repo_id=repo_id,
            repo_type="model"
        )

    print(f"Folder '{folder_path}' successfully uploaded to Hugging Face Hub repository '{repo_name}'.")

if __name__ == "__main__":
    arg1 = sys.argv[1]
    arg2 = sys.argv[2]
    arg3 = sys.argv[3]
    arg4 = sys.argv[4]
    arg5 = sys.argv[5]
    upload_folder_to_hf_hub(arg1, arg2, arg3, arg4, arg5)

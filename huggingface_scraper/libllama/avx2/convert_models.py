import os

def main():
    cwd = os.getcwd()
    dir = os.path.dirname(__file__)
    os.chdir(dir)
    models_dir = os.path.join(dir, 'models')
    models = os.listdir(models_dir)
    for model in models:
        if os.path.isdir(os.path.join(models_dir, model)):
            this_dir = os.path.join(models_dir, model)
            if(os.path.isfile(os.path.join(this_dir, 'checkpoint.bin.bak'))):
                print("backup found")
                if(os.path.isfile(os.path.join(this_dir, 'checkpoint.bin'))):
                    print("original found")
                    pass
                else:
                    print("no original found")
                    # rename
                    os.system('mv ' + os.path.join(this_dir, 'checkpoint.bin.bak' ) + ' ' + os.path.join(this_dir, 'checkpoint.bin'))
                pass
        
            if(os.path.isfile(os.path.join(this_dir, 'checkpoint.bin'))):
                os.chdir(this_dir)
                os.system('python ../../skillset/convert-llama-ggmlv3-to-gguf.py --input checkpoint.bin --output checkpoint.gguf.bin ; mv checkpoint.bin checkpoint.bin.bak ; mv checkpoint.gguf.bin checkpoint.bin')
                os.chdir(dir)
            else:
                print("skipping " + model)
                print("no checkpoint.bin found")
                print(os.path.join(this_dir, 'checkpoint.bin'))
    print("done")
    return

if __name__ == '__main__': 
    main()
from boto3 import resource
from boto3.session import Session

session = None

class S3:
    def __init__(self, resources, meta=None):
        self.bucket = None
        self.bucket_files = None
        self.search_query = None
        self.search_results = None
        self.k = None
        if meta is not None:
            if "config" in meta:
                if meta['config'] is not None:
                    self.config = meta['config']
        self.get_session(meta['config'])

    def __call__(self, method, **kwargs):
        if method == 'read_dir':
            self.method = 'read_dir'
            return self.s3_read_dir(**kwargs)
        if method == 'download_object':
            self.method = 'download_object'
            return self.s3_download_object(**kwargs)
        pass


    def s3_read_dir(self, dir, bucket, s3_config):
        s3bucket = resource(**self.config_to_boto(s3_config)).Bucket(bucket)
        objects = s3bucket.objects.filter(Prefix=dir)
        return objects


    def s3_download_object(self, f, bucket, key, s3_config, progress_callback):
        s3 = self.get_session(s3_config)
        return s3.download_fileobj(
            bucket, 
            key, 
            f, 
            Callback=progress_callback
        )


    def get_session(self, s3_config):
        global session

        if not session:
            session = Session().client(**self.config_to_boto(s3_config))

        return session


    def config_to_boto(self, s3_config):
        return dict(
            service_name='s3',
            aws_access_key_id=s3_config['accessKey'],
            aws_secret_access_key=s3_config['secretKey'],
            endpoint_url=s3_config['endpoint'],
        )

def main():
    endpoint = "https://object.ord1.coreweave.com"
    access_key = ""
    secret_key = ""
    host_bucket = "%(bucket)s.object.ord1.coreweave.com"
    bucket = "swissknife-models"
    dir = "wizardmath-7b-v1.0-4bit@gguf"
    config = {
        "accessKey": access_key,
        "secretKey": secret_key,
        "endpoint": endpoint,
    }
    meta = {}
    meta["config"] = config
    test_s3 = S3(None, meta)
    s3_dir = test_s3.s3_read_dir(dir, bucket, config)
    print(s3_dir)
    
if __name__ == '__main__':
    #main()
    pass
    

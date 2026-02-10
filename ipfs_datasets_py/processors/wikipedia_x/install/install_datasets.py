import datasets


class install_datasets:
    def __init__(self):
        self.datasets = datasets()
        self.db = {}
        return None

    def install(self, dataset_name):
        dataset = self.datasets.get(dataset_name)
        dataset.install()
        return None

    def test_install_datasets(datasets):
        for dataset in datasets:
            install_datasets = install_datasets()
            install_datasets.install(dataset)
        return None

from pydantic import BaseModel


def _print_configs_on_startup(configs: BaseModel) -> None:
    config_dict = configs.model_dump()
    if configs.print_configs_on_startup:
        for key, value in config_dict.items():
            if key not in ['api_key', 'docintel_endpoint']:
                print(f"{key}: {value}")
            else:
                print(f"{key}: [REDACTED]")

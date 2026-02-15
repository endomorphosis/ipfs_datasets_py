# import asyncio
# from typing import Callable



# from fastapi import FastAPI


# from fastapi.staticfiles import StaticFiles
# from fastapi.middleware.cors import CORSMiddleware
# from fastapi.responses import HTMLResponse



# from configs import Configs, configs
# import managers
# from . import PythonAPI


# class WebsiteMethods:

#     from fastapi.templating import TemplateResponse

#     @staticmethod
#     async def _read_root():
#         return TemplateResponse("index.html", {"request": {}})

#     @staticmethod
#     async def _get_status(api_connected: bool):
#         if api_connected:
#             return {"status": "Connected"}
#         else:
#             return {"status": "Disconnected", "error": "API not connected"}

# class Gui:

#     def __init__(self, resources: dict = None, configs: Configs = None):
#         self.configs = configs
#         self.resources = resources

#         # Functions
#         self._read_root: Callable = self.resources['read_root']
#         self._get_status: Callable = self.resources['get_status']
#         self._run: Callable = self.resources['run']
        
#         # Classes
#         self.python_api: PythonAPI = self.resources['python_api']
#         self.app: FastAPI = self.resources['api']

#         # Configs
#         self._static_dir = (self.configs.paths.ROOT_DIR / "frontend" /"static" ).resolve()
#         self._version = self.configs.version


#         self._api_connected = False

#         try:
#             # Set up the FastAPI app
#             self.app(title="Omni-Converter", version=self.version)
#             # Set up the static files directory
#             self.setup_routes()
#         except Exception as e:
#             print(f"Error setting up routes: {e}")
#             raise e

#     async def setup_routes(self):
#         self.app.add_middleware(
#             CORSMiddleware,
#             allow_origins=["*"],
#             allow_credentials=True,
#             allow_methods=["*"],
#             allow_headers=["*"],
#         )

#         self.app.mount("/static", StaticFiles(directory="static"), name="static")

#         @self.app.get("/", response_class=HTMLResponse)
#         async def read_root():
#             return self._read_root()

#         @self.app.get("/api/status")
#         async def get_status():
#             return self._get_status(self._api_connected)
        
#     async def run(self, host: str = "0.0.0.0", port: int = 8000):
#         """
#         Run the FastAPI application.
        
#         Args:
#             host (str): The host to run the application on.
#             port (int): The port to run the application on.
#         """
#         try:
#             self._api_connected = True
#             self._run(self.app, host=self.host, port=self.port)
#         except Exception as e:
#             print(f"Error running server: {e}")
#         finally:
#             self.teardown()

#     async def teardown(self):
#         """
#         Tear down the GUI and clean up resources.
#         """
#         self._api_connected = False
#         # Add any additional cleanup logic here if needed
#         print("Tearing down GUI and cleaning up resources.")



# def make_gui():
#     import uvicorn

#     _api_resources = {
#         'batch_processor': managers.batch_processor.batch_processor,
#         'resource_monitor': managers.resource_monitor.resource_monitor,
#     }
#     python_api = PythonAPI(resources=_api_resources)

#     resources = {
#         'python_api': python_api,
#         'app': FastAPI,
#         'batch_processor': managers.batch_processor.batch_processor,
#         'resource_monitor': managers.resource_monitor.resource_monitor,
#         'read_root': StaticMethods._read_root,
#         '_get_status': StaticMethods._get_status,
#         'run': unvicorn.run,
#         'convert_file': python_api.convert_file,
#     }
#     return Gui(resources=resources, configs=configs)

# import threading

# if __name__ == "__main__":
#     gui = make_gui()
#     asyncio.run(gui.run())



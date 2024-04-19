import time
import uuid
from comfy_serverless import ComfyConnector
import os
import io
from urllib.parse import urlparse
import json
import copy
import shutil
import tkinter as tk
from PIL import PngImagePlugin, ImageTk, Image

MAX_WORKER_ATTEMPTS = 2 # Maximum number of times the worker will attempt to run before giving up
START_TIME = time.time() # Time at which the worker was initialized
APP_NAME = os.getenv('APP_NAME') # Name of the application
INSTANCE_IDENTIFIER = APP_NAME+'-'+str(uuid.uuid4()) # Unique identifier for this instance of the worker
INFERENCE_OUTPUT_FOLDER = os.getenv("INFERENCE_OUTPUT_FOLDER") if os.getenv("INFERENCE_OUTPUT_FOLDER") else None # Path to output folder in ComfyUI
INFERENCE_INPUT_FOLDER = os.getenv("INFERENCE_INPUT_FOLDER") if os.getenv("INFERENCE_INPUT_FOLDER") else None # Path to input folder in ComfyUI
CAMERA_PICTURE_FOLDER = os.getenv("CAMERA_PICTURE_FOLDER") if os.getenv("CAMERA_PICTURE_FOLDER") else None # Path to the folder where the webcam pictures are stored
MINIMUM_GB_FREE_DISK_SPACE = int(os.getenv("MINIMUM_GB_FREE_DISK_SPACE")) if os.getenv("MINIMUM_GB_FREE_DISK_SPACE") else 100 # Minimum GB of free disk space required for the worker to run
COMFY_PAYLOAD = json.load(open(os.getenv("COMFY_PAYLOAD"))) if os.getenv("COMFY_PAYLOAD") else json.load(open('payload_api.json'))
APP_WINDOW_TITLE = os.getenv("APP_WINDOW_TITLE") if os.getenv("APP_WINDOW_TITLE") else "Rethinking the Past"
IMAGES_PER_BATCH = 1

def confirm_disk_space():
    # declare helper function to get free space
    def get_free_space_gb(folder): # Return folder/drive free space (in gigabytes)
        total, used, free = shutil.disk_usage(folder)
        return free // (2**30)
    # declare helper function to delete files from a folder
    def delete_contents(folder): # Delete the contents of the specified folder
        for filename in os.listdir(folder):
            file_path = os.path.join(folder, filename)
            try:
                if os.path.isfile(file_path) or os.path.islink(file_path):
                    os.unlink(file_path)
                elif os.path.isdir(file_path):
                    shutil.rmtree(file_path)
            except Exception as e:
                raise
    if get_free_space_gb('/') < MINIMUM_GB_FREE_DISK_SPACE:  # Checking the root directory for overall disk space
        if INFERENCE_OUTPUT_FOLDER:
            delete_contents(INFERENCE_OUTPUT_FOLDER)
        if INFERENCE_INPUT_FOLDER:
            delete_contents(INFERENCE_INPUT_FOLDER)
        if CAMERA_PICTURE_FOLDER:
            delete_contents(CAMERA_PICTURE_FOLDER)

def fetch_images(payload):
    try:
        comfy_connector = ComfyConnector()
        image_objects = []
        comfy_api = payload['comfy_api']
        images = comfy_connector.generate_images(comfy_api)
        for image in images: 
            # Create a unique filename
            filename = f'distillery_{str(uuid.uuid4())}.png'
            # Add the metadata
            image_metadata_dict = copy.deepcopy(payload)
            #del image_metadata_dict['comfy_api'] # Remove the Comfy API from the metadata to keep the size small
            image_metadata = json.dumps(image_metadata_dict)
            pnginfo = PngImagePlugin.PngInfo()
            pnginfo.add_text('prompt', image_metadata)
            # Save the image to an in-memory file object
            image_object = io.BytesIO()
            image.save(image_object, format='PNG', pnginfo=pnginfo)
            image_object.seek(0)
            # Create a list of in-memory image objects
            image_objects.append(image_object)
        return image_objects # Return the list of in-memory image objects
    except Exception as e:
        raise

def flatten_list(nested_list):
    try:
        flat_list = []
        for item in nested_list:
            if isinstance(item, list):
                flat_list.extend(flatten_list(item))
            else:
                flat_list.append(item)
        return flat_list
    except Exception as e:
        raise

def worker_routine(payload, comfy_connector):
    attempt_number = 1
    try:
        while attempt_number <= MAX_WORKER_ATTEMPTS:
            try:
                comfy_connector = ComfyConnector()
                images_per_batch = payload['images_per_batch']
                files = []
                for i in range(images_per_batch):
                    file = fetch_images(payload)
                    files.append(file)
                corrected_files = flatten_list(files)
                print(f"Files being sent to the handler.")
                return corrected_files
            except Exception as e:
                if attempt_number < MAX_WORKER_ATTEMPTS:
                    message_to_log = f"Warning: Worker failed on attempt #{attempt_number}/{MAX_WORKER_ATTEMPTS}. Killing ComfyUI and retrying. Exception: {e}"
                    print(message_to_log)
                    time.sleep(0.25)
                    comfy_connector.kill_api()
                    attempt_number += 1
                else:
                    message_to_log = f"Error: Worker failed on attempt #{attempt_number}/{MAX_WORKER_ATTEMPTS}. Killing ComfyUI and returning None. Exception: {e}"
                    print(message_to_log)
                    comfy_connector.kill_api()
    except Exception as e:
        message_to_log = f"Error: Unhandled error on worker_routine. Exception: {e}"
        print(message_to_log)
        comfy_connector.kill_api()


class ImageWindow:
    def __init__(self):
        self.window = tk.Tk()
        self.window.title(APP_WINDOW_TITLE)  # Set the window title
        self.window.attributes('-fullscreen', True)  # Set the window to fullscreen
        self.label = tk.Label(self.window)
        self.label.pack(fill=tk.BOTH, expand=True)  # Make the label fill the window

    def update_image(self, image):
        # Resize the image to fit the screen
        screen_width = self.window.winfo_screenwidth()  # Get screen width
        screen_height = self.window.winfo_screenheight()  # Get screen height
        image = image.resize((screen_width, screen_height), Image.Resampling.LANCZOS)
        photo = ImageTk.PhotoImage(image)
        self.label.config(image=photo)
        self.label.image = photo  # Keep a reference!
        self.window.update()


def main():
    image_window = ImageWindow()
    while True:
        comfy_connector = ComfyConnector()
        try:
            payload = {}
            payload['comfy_api'] = COMFY_PAYLOAD
            payload['images_per_batch'] = IMAGES_PER_BATCH
            output = worker_routine(payload, comfy_connector)
            for image in output:
                image_window.update_image(Image.open(image))
            image_window.window.update()
        except Exception as e:
            message_to_log = f"Error: Unhandled error on main. Exception: {e}"
            print(message_to_log)
            comfy_connector.kill_api()
        finally:
            confirm_disk_space()
        time.sleep(0.1)

main()

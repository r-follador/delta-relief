import numpy as np
from IPython.display import display
from PIL import Image
import laspy
from scipy.ndimage import gaussian_filter
import re
import requests
import zipfile
import tempfile
import os
from tqdm.notebook import tqdm
import rasterio
import matplotlib.pyplot as plt

def create_image(array):
    return Image.fromarray(create_array(array))

def create_array(array):
    avg_norm = 255 * (array - np.min(array)) / (np.max(array) - np.min(array))
    return avg_norm.astype(np.uint8)

def show_image(array):
    display(create_image(array))

def show_image_turbo(array):
    normed = (array - np.min(array)) / (np.ptp(array))
    cmap = plt.get_cmap('turbo')
    color_mapped = cmap(normed)
    color_mapped_uint8 = (color_mapped[..., :3] * 255).astype(np.uint8)
    image = Image.fromarray(color_mapped_uint8)
    display(image)

def save_image(array, file_name):
    avg_norm = 255 * (array - np.min(array)) / (np.max(array) - np.min(array))
    avg_uint8 = avg_norm.astype(np.uint8)
    image = Image.fromarray(avg_uint8)
    image.save(file_name)

def normalize_image(array):
    return (array - np.min(array)) / (np.max(array) - np.min(array))


class DeltaRelief_GeoTiff:
    def __init__(self, file):
        self.file = file
        self._load()
        self._firstderivative_image = None
        self._secondderivative_image = None
        self._skewed_image = None
        self._skewed_image_second = None

    def _load(self):
        #print(f"Init from file {self.file}")
        with rasterio.open(self.file) as dataset:
            self._base_image = dataset.read(1)
        #print("Band 1 shape:", self._normal_image.shape)

    def get_base_image(self):
        return self._base_image

    def _computeFirstDerivativeImage(self):
        #print("Calculate First Derivative Image")
        #First derivative
        gradient_magnitude = computeFirstDerivative(self.get_base_image())
        #clamp to max 0.6
        gradient_magnitude = np.minimum(gradient_magnitude, 0.6)
        self._firstderivative_image = gradient_magnitude

    def _computeSecondDerivativeImage(self):
        print("Calculate Second Derivative Image")
        gradient_magnitude = computeFirstDerivative(self.get_first_derivative_image())
        gradient_magnitude = np.minimum(gradient_magnitude, 0.1)
        self._secondderivative_image = gradient_magnitude

    def get_first_derivative_image(self):
        if self._firstderivative_image is None:
            self._computeFirstDerivativeImage()
        return self._firstderivative_image

    def get_second_derivative_image(self):
        if self._secondderivative_image is None:
            self._computeSecondDerivativeImage()
        return self._secondderivative_image

    def get_skewed_image(self):
        if self._skewed_image is None:
            self._computeSkewedImage()
        return self._skewed_image

    def _computeSkewedImage(self):
        first_deriv = np.tanh(3*self.get_first_derivative_image())
        self._skewed_image = np.log(first_deriv+1)

    def get_skewed_image_second(self):
        if self._skewed_image_second is None:
            self._computeSkewedImage_second()
        return self._skewed_image_second

    def _computeSkewedImage_second(self):
        first_deriv = np.tanh(3*self.get_second_derivative_image())
        self._skewed_image_second = np.log(first_deriv+1)



class DeltaRelief_LAS:
    def __init__(self, file, ncol):
        self.ncol = ncol
        self.file = file
        self._load()
        self._average_image = None
        self._stdev_image = None
        self._firstderivative_image = None
        self._secondderivative_image = None

    def _load(self):
        print(f"Init from file {self.file}")
        las = laspy.read(self.file)
        ground_mask = las.classification == 2
        x = las.x[ground_mask]
        y = las.y[ground_mask]
        z = las.z[ground_mask]

        x = np.asarray(x)
        y = np.asarray(y)
        z = np.asarray(z)

        xmin, xmax = x.min(), x.max()
        ymin, ymax = y.min(), y.max()
        zmin, zmax = z.min(), z.max()

        # Define the desired resolution (number of cells)
        ncols = nrows = self.ncol  # Number of columns/rows in the image

        # Calculate the scale factors
        x_scale = (ncols - 1) / (xmax - xmin)
        y_scale = (nrows - 1) / (ymax - ymin)

        # Map coordinates to indices
        x_indices = ((x - xmin) * x_scale).astype(int)
        y_indices = ((y - ymin) * y_scale).astype(int)

        # Initialize sum, sum of squares, and count arrays
        self.sum_image = np.zeros((nrows, ncols), dtype=np.float64)
        self.sum_sq_image = np.zeros((nrows, ncols), dtype=np.float64)
        self.count_image = np.zeros((nrows, ncols), dtype=np.int32)

        y_indices_flipped = nrows - 1 - y_indices

        # Populate the sum, sum of squares, and count arrays
        np.add.at(self.sum_image, (y_indices_flipped, x_indices), z)
        np.add.at(self.sum_sq_image, (y_indices_flipped, x_indices), z ** 2)
        np.add.at(self.count_image, (y_indices_flipped, x_indices), 1)


    def _computeAverageImage(self):
        print("Calculate Average Image")
        with np.errstate(divide='ignore', invalid='ignore'):
            average_image = self.sum_image / self.count_image
            average_image[~np.isfinite(average_image)] = np.nan
        # Handle missing data by averaging neighboring cells instead of np.nanmin
        # First, mask the cells that are missing (where count_image is 0)
        mask = (self.count_image == 0)
        # Apply Gaussian filter only to the valid cells (where count_image > 0)
        filled_image = np.copy(average_image)
        filled_image[mask] = np.nanmean(average_image)  # Temporarily set missing values to 0 for convolution
        smoothed_image = gaussian_filter(filled_image, sigma=10.0)

        # Replace missing data (where count_image == 0) with smoothed values
        average_image[mask] = smoothed_image[mask]
        self._average_image = average_image

        print(f"One intensity step corresponds to {(np.max(self._average_image) - np.min(self._average_image))/255} meters")

    def get_base_image(self):
        if self._average_image is None:
            self._computeAverageImage()
        return self._average_image

    def _computeStdDevImage(self):
        # Compute standard deviation per pixel
        print("Calculate StdDev Image")
        with np.errstate(divide='ignore', invalid='ignore'):
            variance_image = (self.sum_sq_image - (self.sum_image ** 2) / self.count_image) / self.count_image
            stddev_image = np.sqrt(variance_image)
            stddev_image[~np.isfinite(stddev_image)] = np.nan

        # Handle missing data
        stddev_image = np.nan_to_num(stddev_image, nan=0.0)

        #Overdraw
        stddev_image = np.minimum(stddev_image*stddev_image,0.02)
        self._stdev_image = stddev_image

    def get_std_dev_image(self):
        if self._stdev_image is None:
            self._computeStdDevImage()
        return self._stdev_image

    def _computeFirstDerivativeImage(self):
        print("Calculate First Derivative Image")
        #First derivative
        gradient_magnitude = computeFirstDerivative(self.get_base_image())
        #clamp to max 0.6
        gradient_magnitude = np.minimum(gradient_magnitude, 0.6)
        self._firstderivative_image = gradient_magnitude

    def _computeSecondDerivativeImage(self):
        print("Calculate Second Derivative Image")
        gradient_magnitude = computeFirstDerivative(self.get_first_derivative_image())
        gradient_magnitude = np.minimum(gradient_magnitude, 0.1)
        self._secondderivative_image = gradient_magnitude

    def get_first_derivative_image(self):
        if self._firstderivative_image is None:
            self._computeFirstDerivativeImage()
        return self._firstderivative_image

    def get_second_derivative_image(self):
        if self._secondderivative_image is None:
            self._computeSecondDerivativeImage()
        return self._secondderivative_image

def computeFirstDerivative(image):
    # Compute gradients along y and x axes
    grad_y, grad_x = np.gradient(image, edge_order=2)
    # Compute the gradient magnitude (slope)
    gradient_magnitude = np.sqrt(grad_x**2 + grad_y**2)
    return gradient_magnitude

class LidarLinks_LAS:
    """
    LAS files; https://www.swisstopo.admin.ch/en/height-model-swisssurface3d
    This is not used in the examples.
    """
    def __init__(self):
        self._init_from_file("ch.swisstopo.swisssurface3d.csv")

    def _init_from_file(self, lidar_links):
        with open(lidar_links, 'r') as file:
            self.list_of_links = [line.strip() for line in file]
        print(f"Number of links in {lidar_links}: {len(self.list_of_links)}")

    def getLink(self, east: int, north: int):
        """
        Get the LiDAR-GEOTIFF/LAS file link for a given coordinate. (bottom/south, left/east corner of the tile)
        :param east:
        :param north:
        :return:
        """
        #in CH1903+https://www.swisstopo.admin.ch/en/the-swiss-coordinates-system, bottom left
        pattern = fr"_{east}-{north}_"
        for string in self.list_of_links:
            if re.search(pattern, string):
                return string  # Return the matching string
        return None  # Return None if no match is found

    def getLinkFromPaste(self, coordinates: str):
        """
        Convenience function to get the link to the LiDAR-GEOTIFF/LAS file from a string of coordinates.
        Allows to copy-paste a coordinate string from https://map.geo.admin.ch, e.g. "2'758'277.04, 1'178'933.71"
        :param coordinates:
        :return:
        """
        numbers = coordinates.replace("'", "").split(", ")
        # Convert the strings to float
        num1 = float(numbers[0])
        num2 = float(numbers[1])
        return self.getLink(int(num1/1000), int(num2/1000))

    def download(self, url):
        # Create a temporary directory
        temp_dir = tempfile.mkdtemp()
        # Get the file size from the headers (for progress bar)
        response = requests.head(url)
        file_size = int(response.headers.get('content-length', 0))
        # Stream the download
        response = requests.get(url, stream=True)
        zip_path = os.path.join(temp_dir, "tempfile.zip")
        # Write the file to disk with progress tracking
        chunk_size = 1024  # 1 KB
        with open(zip_path, 'wb') as file, tqdm(
                desc="Downloading",
                total=file_size,
                unit='B',
                unit_scale=True,
                unit_divisor=1024,
        ) as bar:
            for chunk in response.iter_content(chunk_size=chunk_size):
                if chunk:
                    file.write(chunk)
                    bar.update(len(chunk))
        # Unzip the file
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall(temp_dir)
        # Get the first file in the temp_dir
        first_file = None
        for root, dirs, files in os.walk(temp_dir):
            if files:
                first_file = os.path.join(root, files[0])
                break

        print(f"Downloaded File: {first_file}")
        # Return the path to the first file
        return first_file

class LidarLinks_GeoTiff(LidarLinks_LAS):
    """
    GEOTIFF files: https://www.swisstopo.admin.ch/en/height-model-swissalti3d
    """
    def __init__(self):
        self._init_from_file("ch.swisstopo.swissalti3d.csv")

    def download(self, url):
        temp_dir = tempfile.mkdtemp()
        filename = os.path.join(temp_dir, "downloaded_file")
        # Get the file size from the headers (for progress bar)
        response = requests.head(url)
        file_size = int(response.headers.get('content-length', 0))

        # Stream the download
        response = requests.get(url, stream=True)

        # Write the file to disk with progress tracking
        chunk_size = 1024  # 1 KB
        with open(filename, 'wb') as file, tqdm(
                desc="Downloading",
                total=file_size,
                unit='B',
                unit_scale=True,
                unit_divisor=1024,
        ) as bar:
            for chunk in response.iter_content(chunk_size=chunk_size):
                if chunk:
                    file.write(chunk)
                    bar.update(len(chunk))

        #print(f"File downloaded at: {filename}")
        return filename



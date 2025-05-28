import os
from Delta_Relief import create_array
from Delta_Relief import DeltaRelief_GeoTiff, LidarLinks_GeoTiff
import rasterio
from tqdm import tqdm

lidar_links = LidarLinks_GeoTiff()

def save_geotiff(count, url):
    output_path = f"/home/rainer/Downloads/larunga_all/deltarelief_{count}.tif"
    if os.path.exists(output_path):
        print("File exists")
        return  # Skip if already processed
    #print(url)
    try:
        filepath = lidar_links.download(url)
    except Exception as e:
        print(f"Error downloading Url '{url}': {e}")
        quit()
    dr = DeltaRelief_GeoTiff(filepath)
    image = dr.get_skewed_image()
    image =  create_array(image)

    orig_values = dict()

    with rasterio.open(filepath) as src:
        # Get metadata
        orig_values["crs"] = src.crs                   # Coordinate Reference System
        print(src.crs)
        orig_values["transform"]= src.transform       # Affine transform
        orig_values["bounds"] = src.bounds             # Bounding box in coordinate space
        orig_values["width"], orig_values["height"] = src.width, src.height
        orig_values["dtype"] = src.dtypes              # Data types for each band

    # Save as GeoTIFF
    with rasterio.open(
            output_path,
            "w",
            driver="GTiff",
            height=orig_values["height"],
            width=orig_values["width"],
            count=1,  # 3 for RGB, 1 for grayscale
            dtype=image.dtype,
            crs=orig_values["crs"],
            transform=orig_values["transform"],
    ) as dst:
        dst.write(image, 1)
    os.remove(filepath)

with open('ch.swisstopo.swissalti3d.csv', 'r') as file:
    lines = [line.strip() for line in file]

for count, url in tqdm(enumerate(lines), total=len(lines), desc="Processing"):
    save_geotiff(count, url)



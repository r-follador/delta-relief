import sqlite3
import io
from PIL import Image
from time import time

"""
A script to generate lower zoom levels from a higher zoom level directly in mbtile (sqlite3) files.
Tries to minimize memory usage by using a single image canvas and resizing it.

In the end, I decided to use gdaladdo directly. 
"""



input_file = 'lidar_2.mbtiles'
min_zoom = 14
max_zoom = 18

conn = sqlite3.connect(input_file)
cur = conn.cursor()

def tms_y(z, y):
    return (1 << z) - 1 - y

def generate_lower_zoom(src_z, dst_z):
    print(f"\n⤵️  Generating z={dst_z} from z={src_z}")
    start_time = time()
    count = 0

    # Calculate bounds
    cur.execute("SELECT MIN(tile_column), MAX(tile_column), MIN(tile_row), MAX(tile_row) FROM tiles WHERE zoom_level = ?", (src_z,))
    min_x, max_x, min_y_tms, max_y_tms = cur.fetchone()

    if None in (min_x, max_x, min_y_tms, max_y_tms):
        print(f"❌ No tiles found at z={src_z}, skipping.")
        return

    # Convert TMS to XYZ y-coordinates
    max_y = (1 << src_z) - 1 - min_y_tms
    min_y = (1 << src_z) - 1 - max_y_tms

    print(f"🔢 Scanning parent tiles from x={min_x//2} to {max_x//2}, y={min_y//2} to {max_y//2}")

    for x in range(min_x // 2, max_x // 2 + 1):
        for y in range(min_y // 2, max_y // 2 + 1):
            canvas = Image.new('RGBA', (512, 512), (0, 0, 0, 0))
            empty = True

            for dx in (0, 1):
                for dy in (0, 1):
                    cx = x * 2 + dx
                    cy = y * 2 + dy
                    tms_cy = (1 << src_z) - 1 - cy

                    cur.execute(
                        "SELECT tile_data FROM tiles WHERE zoom_level = ? AND tile_column = ? AND tile_row = ?",
                        (src_z, cx, tms_cy)
                    )
                    result = cur.fetchone()
                    if result:
                        try:
                            img = Image.open(io.BytesIO(result[0])).convert('RGBA')
                            canvas.paste(img, (dx * 256, dy * 256))
                            empty = False
                        except Exception as e:
                            print(f"⚠️ Tile ({cx},{cy}) could not be read: {e}")

            if not empty:
                downscaled = canvas.resize((256, 256), resample=Image.LANCZOS)
                buf = io.BytesIO()
                downscaled.save(buf, format='PNG')

                tms_y_dst = tms_y(dst_z, y)
                cur.execute(
                    "INSERT OR REPLACE INTO tiles (zoom_level, tile_column, tile_row, tile_data) VALUES (?, ?, ?, ?)",
                    (dst_z, x, tms_y_dst, buf.getvalue())
                )
                count += 1
                if count % 1000 == 0:
                    print(f"  ✅ {count} tiles written so far at z={dst_z}")

    conn.commit()
    print(f"✅ z={dst_z} complete: {count} tiles written in {time() - start_time:.1f}s")

# Start processing
print("🚀 Starting fully-streamed tile generation from z18 to z14...")
for z in range(max_zoom, min_zoom, -1):
    generate_lower_zoom(z, z - 1)

conn.close()
print("\n🎉 Done! All levels generated with minimal memory usage.")

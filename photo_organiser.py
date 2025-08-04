import os
import re
import json
import shutil
import imagehash
import piexif
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext
from PIL import Image
from tqdm import tqdm
from datetime import datetime

VALID_EXTENSIONS = {".jpg", ".jpeg", ".png", ".heic", ".webp", ".tiff", ".bmp"}

def get_image_date(image_path):
    try:
        img = Image.open(image_path)
        exif_data = img._getexif()
        if exif_data:
            date_str = exif_data.get(36867) or exif_data.get(306)
            if date_str:
                return datetime.strptime(date_str, "%Y:%m:%d %H:%M:%S")
    except:
        pass
    return None

def infer_date_from_path(path):
    patterns = [
        r"(\d{4})[/\\](\d{1,2})",
        r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*",
        r"(\d{2})/(\d{2})/(\d{4})",
        r"(\d{4})"
    ]
    parts = path.split(os.sep)
    for part in parts:
        for pattern in patterns:
            match = re.search(pattern, part, re.IGNORECASE)
            if match:
                try:
                    if len(match.groups()) == 2 and match.group(1).isdigit():
                        return datetime(int(match.group(1)), month_str_to_int(match.group(2)), 1)
                    elif len(match.groups()) == 3:
                        day, month, year = map(int, match.groups())
                        return datetime(year, month, day)
                    elif len(match.groups()) == 1:
                        return datetime(int(match.group(1)), 1, 1)
                    elif match.group(1):
                        return datetime(2000, month_str_to_int(match.group(0)), 1)
                except:
                    continue
    return None

def month_str_to_int(s):
    months = ["jan", "feb", "mar", "apr", "may", "jun",
              "jul", "aug", "sep", "oct", "nov", "dec"]
    s = s.lower()
    for i, m in enumerate(months, 1):
        if m in s:
            return i
    raise ValueError("Unknown month string")

def extract_location_keywords(path):
    path = path.lower()
    common_locations = ["paris", "london", "tokyo", "new york", "cork", "dublin", "rome", "berlin"]
    return [loc for loc in common_locations if loc in path]

def generate_image_hash(image_path):
    try:
        img = Image.open(image_path)
        return imagehash.average_hash(img)
    except:
        return None

def get_all_images(input_folder):
    all_images = []
    for root, _, files in os.walk(input_folder):
        for file in files:
            ext = os.path.splitext(file)[1].lower()
            if ext in VALID_EXTENSIONS:
                full_path = os.path.join(root, file)
                all_images.append(full_path)
    return all_images

def save_json(data, output_folder):
    with open(os.path.join(output_folder, "photo_index.json"), "w") as f:
        json.dump(data, f, indent=2, default=str)

def organise_photos(input_folder, output_folder, log_callback):
    seen_hashes = set()
    stats = {
        "total_files": 0,
        "deduplicated": 0,
        "copied": 0,
        "unknown_date": 0
    }
    photo_manifest = []

    images = get_all_images(input_folder)
    log_callback(f"Found {len(images)} images. Processing...")

    for path in tqdm(images):
        stats["total_files"] += 1
        img_hash = generate_image_hash(path)
        if img_hash and img_hash in seen_hashes:
            stats["deduplicated"] += 1
            continue
        seen_hashes.add(img_hash)

        date_taken = get_image_date(path)
        if not date_taken:
            date_taken = infer_date_from_path(path)
        if not date_taken:
            stats["unknown_date"] += 1
            continue

        year = str(date_taken.year)
        month = f"{date_taken.month:02d}"
        new_dir = os.path.join(output_folder, year, month)

        event_label = None
        for part in path.split(os.sep):
            if re.search(r"wedding|holiday|birthday|party|graduation|honeymoon|trip", part, re.IGNORECASE):
                event_label = part
                break
        if event_label:
            new_dir = os.path.join(new_dir, event_label)

        os.makedirs(new_dir, exist_ok=True)
        filename = os.path.basename(path)
        destination = os.path.join(new_dir, filename)

        if not os.path.exists(destination):
            shutil.copy2(path, destination)
            stats["copied"] += 1

            locations = extract_location_keywords(path)
            if locations:
                try:
                    exif_dict = piexif.load(destination)
                    user_comment = "; ".join(locations)
                    exif_dict["Exif"][piexif.ExifIFD.UserComment] = piexif.helper.UserComment.dump(user_comment)
                    exif_bytes = piexif.dump(exif_dict)
                    piexif.insert(exif_bytes, destination)
                except:
                    pass

            photo_manifest.append({
                "source": path,
                "destination": destination,
                "date_taken": date_taken,
                "locations": locations
            })

    save_json(photo_manifest, output_folder)
    return stats

# ---------------- GUI ----------------

def run_gui():
    def browse_input():
        folder = filedialog.askdirectory()
        if folder:
            input_entry.delete(0, tk.END)
            input_entry.insert(0, folder)

    def browse_output():
        folder = filedialog.askdirectory()
        if folder:
            output_entry.delete(0, tk.END)
            output_entry.insert(0, folder)

    def log(text):
        output_box.insert(tk.END, text + "\n")
        output_box.see(tk.END)
        root.update()

    def run_processing():
        in_path = input_entry.get()
        out_path = output_entry.get()
        if not os.path.isdir(in_path) or not os.path.isdir(out_path):
            messagebox.showerror("Error", "Please select valid input and output folders.")
            return
        output_box.delete(1.0, tk.END)
        stats = organise_photos(in_path, out_path, log)
        log("\n✅ Done!")
        log(f"Total: {stats['total_files']}, Deduplicated: {stats['deduplicated']}, Copied: {stats['copied']}, Unknown Date: {stats['unknown_date']}")
        messagebox.showinfo("Finished", "Photo organising is complete.")

    root = tk.Tk()
    root.title("📷 Photo Organiser")

    tk.Label(root, text="Source Folder").grid(row=0, column=0, sticky="e")
    input_entry = tk.Entry(root, width=50)
    input_entry.grid(row=0, column=1)
    tk.Button(root, text="Browse", command=browse_input).grid(row=0, column=2)

    tk.Label(root, text="Destination Folder").grid(row=1, column=0, sticky="e")
    output_entry = tk.Entry(root, width=50)
    output_entry.grid(row=1, column=1)
    tk.Button(root, text="Browse", command=browse_output).grid(row=1, column=2)

    tk.Button(root, text="Run", command=run_processing, bg="#4CAF50", fg="white").grid(row=2, column=1, pady=10)

    output_box = scrolledtext.ScrolledText(root, width=70, height=15)
    output_box.grid(row=3, column=0, columnspan=3, padx=10, pady=10)

    root.mainloop()

if __name__ == "__main__":
    run_gui()

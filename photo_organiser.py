import os
import re
import json
import shutil
import imagehash
import piexif
import piexif.helper
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext
from PIL import Image, ImageTk
from tqdm import tqdm
from datetime import datetime
from sklearn.cluster import DBSCAN
import face_recognition
import numpy as np
import sys
import traceback

VALID_EXTENSIONS = {".jpg", ".jpeg", ".png", ".heic", ".webp", ".tiff", ".bmp"}

# -------------------------------------------------------------------
# Global exception handler to catch any uncaught exceptions
def handle_exception(exc_type, exc_value, exc_traceback):
    if issubclass(exc_type, KeyboardInterrupt):
        # Let KeyboardInterrupt go through
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return
    print("❌ Uncaught exception:", "".join(traceback.format_exception(exc_type, exc_value, exc_traceback)))

sys.excepthook = handle_exception
# -------------------------------------------------------------------

def get_image_date(image_path):
    try:
        img = Image.open(image_path)
        exif_data = img._getexif()
        if exif_data:
            date_str = exif_data.get(36867) or exif_data.get(306)
            if date_str:
                return datetime.strptime(date_str, "%Y:%m:%d %H:%M:%S")
    except Exception as e:
        print(f"⚠️ Error reading EXIF from {image_path}: {e}")
    return None

def infer_date_from_path(path):
    patterns = [
        r"(\d{4})[/\\](\d{1,2})",
        r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*",
        r"(\d{2})/(\d{2})/(\d{4})",
        r"(?<!\d)(?:-|_|\s)?(19[8-9]\d|20[0-2]\d)(?:-|_|\s)?(?!\d)"
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
                        year = int(match.group(1))
                        if 1988 <= year <= 2025:
                            return datetime(year, 1, 1)
                    elif match.group(1):
                        return datetime(2000, month_str_to_int(match.group(0)), 1)
                except Exception:
                    continue
    return None

def month_str_to_int(s):
    months = ["jan", "feb", "mar", "apr", "may", "jun",
              "jul", "aug", "sep", "oct", "nov", "dec"]
    s = s.lower()
    for i, m in enumerate(months, 1):
        if m in s:
            return i
    raise ValueError(f"Unknown month string: {s}")

def extract_location_keywords(path):
    path_lower = path.lower()
    common_locations = ["paris", "london", "tokyo", "new york", "cork", "dublin", "rome", "berlin"]
    return [loc for loc in common_locations if loc in path_lower]

def generate_image_hash(image_path):
    try:
        img = Image.open(image_path)
        return imagehash.average_hash(img)
    except Exception as e:
        print(f"⚠️ Error hashing image {image_path}: {e}")
        return None

def get_all_images(input_folder):
    all_images = []
    for root, _, files in os.walk(input_folder):
        for file in files:
            ext = os.path.splitext(file)[1].lower()
            if ext in VALID_EXTENSIONS:
                all_images.append(os.path.join(root, file))
    return all_images

def save_json(data, output_folder):
    os.makedirs(output_folder, exist_ok=True)
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

        date_taken = get_image_date(path) or infer_date_from_path(path)
        if not date_taken:
            stats["unknown_date"] += 1
            continue

        year = str(date_taken.year)
        month = f"{date_taken.month:02d}"
        new_dir = os.path.join(output_folder, year, month)

        # detect event labels in path
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
            try:
                shutil.copy2(path, destination)
                stats["copied"] += 1
            except Exception as e:
                print(f"⚠️ Failed to copy {path} → {destination}: {e}")
                continue

            locations = extract_location_keywords(path)
            if locations:
                try:
                    exif_dict = piexif.load(destination)
                    user_comment = "; ".join(locations)
                    exif_dict["Exif"][piexif.ExifIFD.UserComment] = piexif.helper.UserComment.dump(user_comment)
                    exif_bytes = piexif.dump(exif_dict)
                    piexif.insert(exif_bytes, destination)
                except Exception as e:
                    print(f"⚠️ Failed to write EXIF to {destination}: {e}")

            photo_manifest.append({
                "source": path,
                "destination": destination,
                "date_taken": date_taken,
                "locations": locations
            })

    save_json(photo_manifest, output_folder)
    return stats, photo_manifest

def cluster_faces(image_paths, tolerance=0.5):
    face_encodings = []
    image_to_faces = {}

    for path in tqdm(image_paths, desc="Encoding faces"):
        try:
            image = face_recognition.load_image_file(path)
            encs = face_recognition.face_encodings(image)
            if encs:
                image_to_faces[path] = encs
                face_encodings.extend(encs)
        except Exception as e:
            print(f"⚠️ Error processing faces in {path}: {e}")

    if not face_encodings:
        return {}, [], {}

    encodings_np = np.array(face_encodings)
    clustering = DBSCAN(metric='euclidean', eps=tolerance, min_samples=1).fit(encodings_np)
    labels = clustering.labels_

    face_to_label = {}
    idx = 0
    for path, encs in image_to_faces.items():
        labelled = []
        for _ in encs:
            labelled.append(int(labels[idx]))
            idx += 1
        face_to_label[path] = labelled

    return face_to_label, face_encodings, image_to_faces

def extract_face_thumbnail(image_path, face_encoding, size=(200, 200)):
    try:
        image = face_recognition.load_image_file(image_path)
        face_locations = face_recognition.face_locations(image)
        encodings = face_recognition.face_encodings(image, face_locations)
    except Exception as e:
        print(f"⚠️ Error loading or encoding {image_path}: {e}")
        return None

    for loc, enc in zip(face_locations, encodings):
        if np.linalg.norm(enc - face_encoding) < 0.6:
            top, right, bottom, left = loc
            face_crop = image[top:bottom, left:right]
            img_pil = Image.fromarray(face_crop)
            img_pil.thumbnail(size)
            return img_pil
    return None

def label_faces_gui(face_encodings, cluster_labels, image_to_encodings):
    cluster_examples = {}
    paths = list(image_to_encodings.keys())
    idx = 0
    for label in cluster_labels:
        if label not in cluster_examples and idx < len(paths):
            cluster_examples[label] = (face_encodings[idx], paths[idx])
        idx += 1

    root = tk.Tk()
    root.title("Name the people")
    name_map = {}

    for label, (encoding, image_path) in cluster_examples.items():
        face_img = extract_face_thumbnail(image_path, encoding)
        if face_img is None:
            continue  # skip clusters we can't render

        try:
            window = tk.Toplevel(root)
            window.title(f"Cluster {label}")
            tk.Label(window, text=f"Cluster {label}").pack()

            img_tk = ImageTk.PhotoImage(face_img)
            lbl = tk.Label(window, image=img_tk)
            lbl.image = img_tk
            lbl.pack()

            entry = tk.Entry(window)
            entry.pack()

            def save_name(label=label, ent=entry, win=window):
                name_map[label] = ent.get().strip() or f"Unknown-{label}"
                win.destroy()

            tk.Button(window, text="Save", command=save_name).pack()
            root.wait_window(window)
        except Exception as e:
            print(f"⚠️ GUI error for cluster {label}: {e}")
            continue

    root.destroy()
    return name_map

def annotate_images_with_faces(face_to_label, name_map, output_json):
    annotated = {}
    for path, labels in face_to_label.items():
        names = list({name_map.get(l, f"Unknown-{l}") for l in labels})
        annotated[path] = names

        try:
            exif_dict = piexif.load(path)
            comment = "Faces: " + ", ".join(names)
            exif_dict["Exif"][piexif.ExifIFD.UserComment] = piexif.helper.UserComment.dump(comment)
            exif_bytes = piexif.dump(exif_dict)
            piexif.insert(exif_bytes, path)
        except Exception as e:
            print(f"⚠️ Failed to write face EXIF for {path}: {e}")

    try:
        with open(output_json, "w") as f:
            json.dump(annotated, f, indent=2)
    except Exception as e:
        print(f"⚠️ Failed to save annotations to {output_json}: {e}")
    return annotated

def search_photos_by_name(annotations_file):
    try:
        with open(annotations_file) as f:
            data = json.load(f)
    except Exception as e:
        messagebox.showerror("Error", f"Could not load annotations: {e}")
        return

    root = tk.Tk()
    root.title("🔍 Search by Person")

    tk.Label(root, text="Name 1").grid(row=0, column=0)
    name1_entry = tk.Entry(root)
    name1_entry.grid(row=0, column=1)

    tk.Label(root, text="Name 2 (optional)").grid(row=1, column=0)
    name2_entry = tk.Entry(root)
    name2_entry.grid(row=1, column=1)

    result_box = scrolledtext.ScrolledText(root, width=80, height=25)
    result_box.grid(row=3, column=0, columnspan=2)

    def do_search():
        result_box.delete(1.0, tk.END)
        n1 = name1_entry.get().strip().lower()
        n2 = name2_entry.get().strip().lower()
        for path, people in data.items():
            pl = [p.lower() for p in people]
            if n1 and n1 not in pl: continue
            if n2 and n2 not in pl: continue
            result_box.insert(tk.END, f"{path} — {', '.join(people)}\n")

    tk.Button(root, text="Search", command=do_search).grid(row=2, column=0, columnspan=2, pady=5)
    root.mainloop()

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
        try:
            stats, manifest = organise_photos(in_path, out_path, log)
            face_to_label, encs, img_encs = cluster_faces([e["destination"] for e in manifest])
            name_map = label_faces_gui(encs, list({l for labels in face_to_label.values() for l in labels}), img_encs)
            annotate_images_with_faces(face_to_label, name_map, os.path.join(out_path, "faces.json"))
            log("\n✅ Done!")
            log(f"Total: {stats['total_files']}, Deduplicated: {stats['deduplicated']}, "
                f"Copied: {stats['copied']}, Unknown Date: {stats['unknown_date']}")
            messagebox.showinfo("Finished", "Photo organising is complete.")
        except Exception as e:
            print(f"❌ Unexpected error during processing: {e}")

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

    tk.Button(root, text="Run", command=run_processing, bg="#4CAF50", fg="white") \
        .grid(row=2, column=1, pady=10)
    tk.Button(root, text="Search by Name",
              command=lambda: search_photos_by_name(os.path.join(output_entry.get(), "faces.json"))) \
        .grid(row=2, column=2, pady=10)

    output_box = scrolledtext.ScrolledText(root, width=70, height=15)
    output_box.grid(row=3, column=0, columnspan=3, padx=10, pady=10)

    root.mainloop()

if __name__ == "__main__":
    run_gui()

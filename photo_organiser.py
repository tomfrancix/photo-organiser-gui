import os
import re
import json
import shutil
import imagehash
import piexif
import piexif.helper
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, Toplevel, Label, Entry, Button
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
# Global IMAGE_REFERENCES to keep PhotoImage alive
# -------------------------------------------------------------------
IMAGE_REFERENCES = []

# -------------------------------------------------------------------
# Global exception handler
# -------------------------------------------------------------------
def handle_exception(exc_type, exc_value, exc_traceback):
    if issubclass(exc_type, KeyboardInterrupt):
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

# -------------------------------------------------------------------
def infer_date_from_path(path):
    patterns = [
        r"(\d{4})[/\\](\d{1,2})",
        r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*",
        r"(\d{2})/(\d{2})/(\d{4})",
        r"(?<!\d)(?:-|_|\s)?(19[8-9]\d|20[0-2]\d)(?:-|_|\s)?(?!\d)"
    ]
    for part in path.split(os.sep):
        for pattern in patterns:
            match = re.search(pattern, part, re.IGNORECASE)
            if match:
                groups = match.groups()
                try:
                    if len(groups) == 2 and groups[0].isdigit():
                        return datetime(int(groups[0]), month_str_to_int(groups[1]), 1)
                    if len(groups) == 3:
                        day, month, year = map(int, groups)
                        return datetime(year, month, day)
                    if len(groups) == 1:
                        year = int(groups[0])
                        if 1988 <= year <= 2025:
                            return datetime(year, 1, 1)
                except:
                    pass
    return None

# -------------------------------------------------------------------
def month_str_to_int(s):
    months = ["jan","feb","mar","apr","may","jun","jul","aug","sep","oct","nov","dec"]
    s = s.lower()
    for i, m in enumerate(months, 1):
        if m in s:
            return i
    raise ValueError(f"Unknown month: {s}")

# -------------------------------------------------------------------
def extract_location_keywords(path):
    locs = []
    for loc in ["paris","london","tokyo","new york","cork","dublin","rome","berlin"]:
        if loc in path.lower():
            locs.append(loc)
    return locs

# -------------------------------------------------------------------
def generate_image_hash(image_path):
    try:
        img = Image.open(image_path)
        return imagehash.average_hash(img)
    except Exception as e:
        print(f"⚠️ Error hashing {image_path}: {e}")
        return None

# -------------------------------------------------------------------
def get_all_images(input_folder):
    all_images = []
    for root, _, files in os.walk(input_folder):
        for f in files:
            if os.path.splitext(f)[1].lower() in VALID_EXTENSIONS:
                all_images.append(os.path.join(root, f))
    return all_images

# -------------------------------------------------------------------
def save_json(data, output_folder):
    os.makedirs(output_folder, exist_ok=True)
    with open(os.path.join(output_folder, "photo_index.json"), "w") as f:
        json.dump(data, f, indent=2, default=str)

# -------------------------------------------------------------------
def organise_photos(input_folder, output_folder, log_callback):
    seen_hashes = set()
    stats = {"total_files": 0, "deduplicated": 0, "copied": 0, "unknown_date": 0}
    photo_manifest = []
    images = get_all_images(input_folder)
    log_callback(f"Found {len(images)} images. Processing...")
    for path in tqdm(images, desc="Organising photos"):
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
        # detect event label
        for part in path.split(os.sep):
            if re.search(r"wedding|holiday|birthday|party|graduation|honeymoon|trip", part, re.IGNORECASE):
                new_dir = os.path.join(new_dir, part)
                break
        os.makedirs(new_dir, exist_ok=True)
        dst = os.path.join(new_dir, os.path.basename(path))
        if not os.path.exists(dst):
            try:
                shutil.copy2(path, dst)
                stats["copied"] += 1
            except Exception as e:
                print(f"⚠️ Failed to copy {path}: {e}")
                continue
            locs = extract_location_keywords(path)
            if locs:
                try:
                    exif_data = piexif.load(dst)
                    comment = "; ".join(locs)
                    exif_data["Exif"][piexif.ExifIFD.UserComment] = piexif.helper.UserComment.dump(comment)
                    piexif.insert(piexif.dump(exif_data), dst)
                except Exception as e:
                    print(f"⚠️ Failed to write EXIF to {dst}: {e}")
            photo_manifest.append({"source": path, "destination": dst, "date_taken": date_taken, "locations": locs})
    save_json(photo_manifest, output_folder)
    return stats, photo_manifest

# -------------------------------------------------------------------
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
            print(f"⚠️ Error processing {path}: {e}")
    if not face_encodings:
        return {}, [], {}, []
    enc_array = np.array(face_encodings)
    labels = DBSCAN(metric='euclidean', eps=tolerance, min_samples=1).fit(enc_array).labels_
    face_to_label = {}
    idx = 0
    for path, encs in image_to_faces.items():
        labels_for_image = []
        for _ in encs:
            labels_for_image.append(int(labels[idx]))
            idx += 1
        face_to_label[path] = labels_for_image
    return face_to_label, face_encodings, image_to_faces, labels

# -------------------------------------------------------------------
def extract_face_thumbnail(image_path, face_encoding, size=(200, 200)):
    try:
        image = face_recognition.load_image_file(image_path)
        locations = face_recognition.face_locations(image)
        encodings = face_recognition.face_encodings(image, locations)
    except Exception as e:
        print(f"⚠️ Error loading {image_path}: {e}")
        return None
    for loc, enc in zip(locations, encodings):
        if np.linalg.norm(enc - face_encoding) < 0.6:
            top, right, bottom, left = loc
            crop = image[top:bottom, left:right]
            pil_crop = Image.fromarray(crop)
            pil_crop.thumbnail(size)
            return pil_crop
    return None

# -------------------------------------------------------------------
def label_faces_gui(face_encodings, cluster_labels, image_to_encodings):
    # Build cluster examples mapping
    cluster_examples = {}
    idx = 0
    for path, encs in image_to_encodings.items():
        for enc in encs:
            cluster_id = cluster_labels[idx]
            if cluster_id not in cluster_examples:
                cluster_examples[cluster_id] = (enc, path)
            idx += 1
    # GUI for naming
    root = tk.Tk()
    root.withdraw()
    name_map = {}
    for cluster_id, (enc, path) in cluster_examples.items():
        thumbnail = extract_face_thumbnail(path, enc)
        if not thumbnail:
            print(f"⚠️ No thumbnail for cluster {cluster_id}")
            continue
        window = Toplevel(root)
        window.title(f"Cluster {cluster_id}")
        Label(window, text=f"Cluster {cluster_id}").pack()
        # Create PhotoImage with proper master to avoid GC issues
        img_tk = ImageTk.PhotoImage(thumbnail, master=window)
        IMAGE_REFERENCES.append(img_tk)
        lbl = Label(window, image=img_tk)
        lbl.pack()
        entry = Entry(window)
        entry.pack()
        def save_name(_id=cluster_id, e=entry, w=window):
            name_map[_id] = e.get()
            w.destroy()
        Button(window, text="Save", command=save_name).pack()
        root.wait_window(window)
    root.destroy()
    return name_map

# -------------------------------------------------------------------
def annotate_images_with_faces(face_to_label, name_map, output_json):
    annotations = {}
    for path, labels in face_to_label.items():
        names = [name_map.get(l, f"Unknown-{l}") for l in labels]
        annotations[path] = names
        try:
            ex=piexif.load(path)
            ex["Exif"][piexif.ExifIFD.UserComment] = piexif.helper.UserComment.dump("Faces: "+", ".join(names))
            piexif.insert(piexif.dump(ex), path)
        except Exception as e:
            print(f"⚠️ Failed EXIF annotate {path}: {e}")
    with open(output_json, "w") as f:
        json.dump(annotations, f, indent=2)
    return annotations

# -------------------------------------------------------------------
def search_photos_by_name(annotations_file):
    try:
        with open(annotations_file) as f:
            data = json.load(f)
    except Exception as e:
        messagebox.showerror("Error", f"Could not load annotations: {e}")
        return
    window = tk.Tk()
    window.title("Search by Person")
    Label(window, text="Name 1").grid(row=0, column=0)
    e1 = Entry(window)
    e1.grid(row=0, column=1)
    Label(window, text="Name 2 (optional)").grid(row=1, column=0)
    e2 = Entry(window)
    e2.grid(row=1, column=1)
    results = scrolledtext.ScrolledText(window, width=80, height=25)
    results.grid(row=3, column=0, columnspan=2)
    def do_search():
        results.delete(1.0, tk.END)
        n1 = e1.get().strip().lower()
        n2 = e2.get().strip().lower()
        for p, people in data.items():
            lower = [x.lower() for x in people]
            if n1 and n1 not in lower: continue
            if n2 and n2 not in lower: continue
            results.insert(tk.END, f"{p} — {', '.join(people)}\n")
    Button(window, text="Search", command=do_search).grid(row=2, column=0, columnspan=2, pady=5)
    window.mainloop()

# -------------------------------------------------------------------

def run_gui():
    root = tk.Tk()
    root.title("Photo Organiser")
    Label(root, text="Source Folder").grid(row=0, column=0, sticky="e")
    src = Entry(root, width=50)
    src.grid(row=0, column=1)
    Button(root, text="Browse", command=lambda: src.insert(0, filedialog.askdirectory())).grid(row=0, column=2)
    Label(root, text="Destination Folder").grid(row=1, column=0, sticky="e")
    dst = Entry(root, width=50)
    dst.grid(row=1, column=1)
    Button(root, text="Browse", command=lambda: dst.insert(0, filedialog.askdirectory())).grid(row=1, column=2)
    box = scrolledtext.ScrolledText(root, width=70, height=15)
    box.grid(row=3, column=0, columnspan=3, padx=10, pady=10)
    def log(msg):
        box.insert(tk.END, msg+"\n")
        box.see(tk.END)
    def process():
        box.delete(1.0, tk.END)
        stats, manifest = organise_photos(src.get(), dst.get(), log)
        f2l, encs, mapping, labels = cluster_faces([i['destination'] for i in manifest])
        nm = label_faces_gui(encs, labels.tolist(), mapping)
        annotate_images_with_faces(f2l, nm, os.path.join(dst.get(), "faces.json"))
        messagebox.showinfo("Done", "Processing complete.")
    Button(root, text="Run", bg="#4CAF50", fg="white", command=process).grid(row=2, column=1)
    Button(root, text="Search by Name", command=lambda: search_photos_by_name(os.path.join(dst.get(), "faces.json"))).grid(row=2, column=2)
    root.mainloop()

if __name__ == "__main__": run_gui()

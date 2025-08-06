# 📷 Photo Organiser

**Photo Organiser** is a simple, one-click tool that helps you clean up and reorganise your photo collection. Whether you're drowning in old digital albums, scattered folders, or duplicate images — this tool helps make sense of it all.

No technical knowledge required. Just select your folders and click **Run**.

---

## What It Does

- **Scans all photos** in a folder (including subfolders)
- **Reads the date** the photo was taken (from metadata or folder names)
- **Organises photos** by Year and Month in a clean new folder
- **Preserves folder labels** like "Wedding" or "Holiday" as event subfolders
- **Detects locations** in filenames and adds that to image metadata
- **Removes duplicates** using perceptual hashing — not just filenames
- **Creates a JSON log** of all photo movements
- **Retains original files** – nothing is deleted

---

## How to Use

1. **Download and unzip** the program (e.g. `PhotoOrganiserGUI.exe`)
2. **Double-click the EXE** to launch the app
3. **Choose the folder** containing your photos
4. **Choose the destination** folder where the organised photos should go
5. Click **Run**
6. Wait for the organiser to finish — you’ll see stats at the bottom
7. Click **Finish**

Your newly organised photo collection will be in the destination folder you chose.

---

## Example Output Structure

```
Organised_Photos/
├── 2011/
│   ├── 08/
│   │   ├── David's Wedding/
│   │   │   └── IMG_1234.jpg
│   │   └── IMG_5678.jpg
├── 2020/
│   └── 12/
│       └── IMG_9012.jpg
└── photo_index.json
```

---

## Advanced Details (For Developers)

- Written in **Python 3.11+**
- GUI built with `tkinter`
- Uses `Pillow`, `piexif`, `imagehash`, and `tqdm`
- Detects date from:
  - EXIF metadata (`DateTimeOriginal`)
  - Folder names like `August 2011`, `20/08/2011`, etc.
- Duplicates are detected using **perceptual hashing** (not just file content)

To rebuild or customise, run:
```bash
pip install -r requirements.txt
pyinstaller --onefile photo_organiser_gui.py
or
python3.10 -m PyInstaller --onefile --name PhotoOrganiser photo_organiser.py  
```

---

## Notes

- This tool does **not delete** or modify your original photo folder
- Organised photos are **copied**, not moved
- SmartScreen may warn on first run (because the EXE is unsigned)

---

## Questions or Feedback?

If something breaks or you'd like extra features (like face grouping or cloud sync), get in touch!

---

© 2025 – Created with ❤️ by Thomas Fahey

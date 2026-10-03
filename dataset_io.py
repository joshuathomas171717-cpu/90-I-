"""dataset_io.py — one way to read and write the dataset files.

`ml_engine`'s artifact cache is keyed on the *bytes* of the CSVs it trains from. That makes formatting
load-bearing: if two parts of the pipeline write the same table with different line endings — pandas
writes LF, `csv.writer` writes CRLF — then a no-op rewrite changes the key, discards a perfectly good
model and forces a full retrain. It happened, twice, in different disguises (float formatting, then
line endings).

So both writers use this module, and `write_dataset` skips a file whose parsed content already matches
what is on disk. The invariant it exists to protect: **a no-op update changes no bytes, so nothing
downstream is invalidated.**
"""
import csv
import os


def read_csv(path):
    """(rows, fieldnames). Raises if the file is missing — callers decide what that means."""
    with open(path, newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        return list(reader), reader.fieldnames


def same_value(a, b):
    """Content equality, not formatting equality: "1.5" and "1.50" are the same number."""
    a = "" if a is None else str(a)
    b = "" if b is None else str(b)
    if a == b:
        return True
    try:
        return float(a) == float(b)
    except ValueError:
        return False


def same_content(path, rows, fields):
    """Does the file already hold exactly these rows? (Field order included: it is the schema.)"""
    if not os.path.exists(path):
        return False
    try:
        with open(path, newline="", encoding="utf-8") as fh:
            on_disk = list(csv.DictReader(fh))
    except (OSError, csv.Error, UnicodeDecodeError):
        return False
    if len(on_disk) != len(rows) or (on_disk and list(on_disk[0].keys()) != list(fields)):
        return False
    for disk_row, new_row in zip(on_disk, rows):
        for key in fields:
            if not same_value(disk_row.get(key), new_row.get(key)):
                return False
    return True


def write_csv(path, rows, fields):
    """Atomic write in the dialect the whole project uses (CRLF, header, quoted as needed)."""
    tmp = path + ".tmp"
    with open(tmp, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(fields))
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in fields})
    os.replace(tmp, path)


def write_dataset(root, files, skip_identical=True):
    """Write {filename: (rows, fields)} into `root`. Returns the list of files actually replaced.

    Skipping identical files is load-bearing, not an optimisation: see the module docstring.
    """
    changed = []
    for name, (rows, fields) in files.items():
        path = os.path.join(root, name)
        if skip_identical and same_content(path, rows, fields):
            continue
        write_csv(path, rows, fields)
        changed.append(name)
    return changed

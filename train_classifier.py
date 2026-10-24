import argparse
import zipfile
from pathlib import Path

import joblib
import numpy as np
from PIL import Image
from sklearn.linear_model import SGDClassifier
from sklearn.metrics import accuracy_score, classification_report

from local_classifier import IMAGE_SIZE


def entries_for_split(archive: zipfile.ZipFile, split: str):
    prefix = f"DATASET/{split}/"
    return [
        entry
        for entry in archive.infolist()
        if entry.filename.startswith(prefix)
        and entry.filename.lower().endswith((".jpg", ".jpeg", ".png", ".webp"))
    ]


def read_features(archive: zipfile.ZipFile, entries):
    features = np.empty((len(entries), IMAGE_SIZE[0] * IMAGE_SIZE[1] * 3), dtype=np.float32)
    labels = np.empty(len(entries), dtype="<U1")
    for index, entry in enumerate(entries):
        with archive.open(entry) as image_file:
            image = Image.open(image_file).convert("RGB")
            image = image.resize(IMAGE_SIZE, Image.Resampling.BILINEAR)
            features[index] = np.asarray(image, dtype=np.float32).reshape(-1) / 255.0
        labels[index] = entry.filename.split("/")[2]
    return features, labels


def main():
    parser = argparse.ArgumentParser(description="Train RecycleLink's local waste classifier.")
    parser.add_argument("archive", type=Path, help="Path to the labeled dataset ZIP archive.")
    parser.add_argument("--output", type=Path, default=Path("models/waste_classifier.joblib"))
    args = parser.parse_args()

    with zipfile.ZipFile(args.archive) as archive:
        train_entries = entries_for_split(archive, "TRAIN")
        test_entries = entries_for_split(archive, "TEST")
        train_features, train_labels = read_features(archive, train_entries)
        test_features, test_labels = read_features(archive, test_entries)

    classifier = SGDClassifier(
        loss="log_loss",
        penalty="l2",
        alpha=1e-5,
        max_iter=40,
        tol=1e-3,
        random_state=42,
    )
    classifier.fit(train_features, train_labels)
    predictions = classifier.predict(test_features)
    print(f"train_images={len(train_labels)} test_images={len(test_labels)}")
    print(f"accuracy={accuracy_score(test_labels, predictions):.4f}")
    print(classification_report(test_labels, predictions, digits=4))

    args.output.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(classifier, args.output)
    print(f"saved_model={args.output}")


if __name__ == "__main__":
    main()

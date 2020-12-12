from config import config
from train import Trainer
import os
from create_dataset import NoteRepresentationManager

if __name__ == "__main__":
    note_manager = NoteRepresentationManager(**config["tokens"], **config["data"], **config["paths"])
    trainer = Trainer(model=None,
                      pad_token=config["tokens"]["pad_token"],
                      dataset_path=config["paths"]["dataset_path"],
                      **config["train"])
    checkpoint = os.path.join("training_2020-12-07_11-25-32", "checkpoint_150.pt")
    sampled_dir = os.path.join("training_2020-12-07_11-25-32", "sampled")
    trainer.generate(checkpoint_path=checkpoint, sampled_dir=sampled_dir, note_manager=note_manager)
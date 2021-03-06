from config import config
import torch
import numpy as np
from torch.nn import functional as f
import os
import subprocess
from config import remote

def get_prior(shape):
    reduced_shape = tuple([shape[0], shape[1] // 4])
    g1 = torch.randn(*reduced_shape) - 2
    g2 = torch.randn(*reduced_shape) - 6
    g3 = torch.randn(*reduced_shape) + 2
    g4 = torch.randn(*reduced_shape) + 6
    g = torch.cat([g1, g2, g3, g4], dim=1)
    return g
    # return Variable(torch.randn(*shape) * 5.).to(config["train"]["device"])  # single gaussian


def get_memories(n_batch=None):
    a = 4
    b = config["model"]["layers"]
    c = n_batch if n_batch is not None else config["train"]["batch_size"]
    e = config["model"]["d_model"]
    device = config["train"]["device"]
    mem_len = config["model"]["mem_len"]
    cmem_len = config["model"]["cmem_len"]
    e_mems = torch.zeros(a, b, c, mem_len, e, dtype=torch.float32, device=device)
    e_cmems = torch.zeros(a, b, c, cmem_len, e, dtype=torch.float32, device=device)
    d_mems = torch.zeros(a, b, c, mem_len, e, dtype=torch.float32, device=device)
    d_cmems = torch.zeros(a, b, c, cmem_len, e, dtype=torch.float32, device=device)
    return e_mems, e_cmems, d_mems, d_cmems


def create_trg_mask(trg):
    trg_mask = np.full(trg.shape + (trg.shape[-1],), True)
    for i in range(trg.shape[0]):
        for b in range(trg.shape[1]):
            line_mask = trg[i][b] != config["tokens"]["pad"]
            pad_mask = np.matmul(line_mask[:, np.newaxis], line_mask[np.newaxis, :])
            subsequent_mask = np.expand_dims(np.tril(np.ones((trg.shape[-1], trg.shape[-1]))), (0, 1))
            subsequent_mask = subsequent_mask.astype(np.bool)
            trg_mask[i][b] = pad_mask & subsequent_mask
    trg_mask = torch.BoolTensor(trg_mask).to(config["train"]["device"])
    return trg_mask


def pad_attention(attentions):  # pad list of array to be the same size
    length = max([s.shape[-1] for s in attentions])
    for count, attention in enumerate(attentions):
        attentions[count] = f.pad(attention, (length - attention.shape[-1], 0))
    return torch.mean(torch.stack(attentions, dim=0), dim=0)


def min_max_scaling(value, old_interval, new_interval):
    """
    It scales a value with range [mn, mx] into a int value with range [a, b]
    """
    mn, mx = old_interval
    a, b = new_interval
    return round((((value - mn) * (b - a)) / (mx - mn)) + a)


def midi_to_wav(input_file, output_file):
    """
    - Manual is available in
        https://github.com/FluidSynth/fluidsynth/wiki/UserManual
    - Sound font can be downloaded from
        http://timtechsoftware.com/ad.html?keyword=sf2%20format?file_name=the%20General%20MIDI%20Soundfont?file_url=uploads/
        GeneralUser_GS_SoftSynth_v144.sf2
    - To install FluidSync for windows, download the executable, for unix use conda
    """
    subprocess.call(["fluidsynth" if remote else os.path.join("fl", "bin", "fluidsynth"),
                     "-F", output_file,
                     # "-i", "-n", "-T", "wav",  # those seems to be useless
                     # "-q",  # activate quiet mode
                     "-r", "8000",
                     # "-T", "raw",  # audio type
                     "sound_font.sf2" if remote else os.path.join("fl", "sound_font.sf2"),  # a sound font
                     input_file])


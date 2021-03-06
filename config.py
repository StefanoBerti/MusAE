import os
import numpy as np

# MAXIMUM ON REMOTE MACHINE: 16GB with 5 layers and 23 bars, 3450 on 3750

remote = os.getcwd() != 'C:\\Users\\berti\\PycharmProjects\\MusAE'

max_bar_length = 200  # for preprocessing, seq_len, mem_len e cmem_len

config = {
    "train": {
        "verbose": True,
        "make_songs": True,
        "log_images": False,
        "do_eval": False,
        "aae": False,
        "n_bars": 8 if remote else 8,  # TODO careful
        "test_losses": False,
        "device": "cuda" if remote else "cuda",
        "batch_size": 1 if remote else 1,
        "test_size": 0.00001 if remote else 0.1,  # 0.001 if remote else 0.1,  # 100 on remote  it was 0.0001 in remote
        "n_workers": 0,
        "n_epochs": 25000,
        "label_smoothing": 0.1,
        "steps_before_eval": 1000 if remote else 500,  # if >= early_stopping, happens at each epoch
        "after_steps_save_model": 1000 if remote else 500,
        "after_steps_make_songs": 1000 if remote else 500,
        "after_steps_log_images": 1000 if remote else 500,
        "warmup_steps": 4000,
        "lr_min": 1e-4,
        "lr_max": 1e-3,
        "decay_steps": 50000,
        "minimum_lr": 5e-5,
        "generated_iterations": 16 if remote else 4,
        # "test_loss": False,
        "train_aae_after_steps": 0,
        "increase_beta_every": 2000 if remote else 2000,
        "max_beta": 0.3 if remote else 0.3,
        "lambda": 10,
        "critic_iterations": 5,
        "interpolation_timesteps": 3,  # intermediate timesteps excluding first and second (with 3: 0 (1 2 3) 4)
        "interpolation_timesteps_length": 4,  # number of bar for each timesteps
        "top_k_mixed_embeddings": 5,
        "min_tf_prob": 0.,
        "max_tf_prob": 1.,
        "tf_prob_step_reduction": 5e-4 if remote else 1e-3  # 5e-4 seems good
    },
    "model": {
        "seq_len": max_bar_length,
        "d_model": 32,
        "heads": 4,
        "ff_mul": 2,
        "layers": 2 if remote else 2,  # if remote else 1,  # 3 GB each
        "mem_len": max_bar_length,  # keep last 2 seq
        "cmem_len": max_bar_length,  # keep 4 compression
        "cmem_ratio": 4,
        "reconstruction_attn_dropout": 0.1,
        "attn_layer_dropout": 0.1,
        "ff_dropout": 0.1,
        "discriminator_dropout": 0.1,
        "n_latents": 200
    },
    "data": {  # Parameters to create and listen the note representation
        "truncated_bars": 32 if remote else 8,  # To truncate the song along bars
        "max_bar_length": max_bar_length,
        "max_bars": 200,
        "use_velocity": False,
        "reconstruction_programs": [0, 0, 32, 40],
        "early_stop": 100000 if remote else 10,  # set this to 0 to disable early stop
        "resolution": 24,
        "tempo": 120,
        "velocities_total": (0, 127),  # using min max scaling, limits are inclusive
        "velocities_compact": (0, 31),  # using min max scaling, limits are inclusive
    },
    "tokens": {
        "pad": 0,
        "bar": 1,
        "sos": 2,
        "eos": 3,
        # Values
        "time_n_values": 128,
        "pitch_n_values": 128,
        "duration_n_values": 128,
        "velocity_n_values": 32,
        "time_first":     4,
        "pitch_first":    4 + 128,
        "duration_first": 4 + 128*2,
        "velocity_first": 4 + 128*3,
        "vocab_size": 4 + 128*3,
        # now event tokens
        "event_pad": 388,  # TODO WAS 0
        "event_sos": 389,
        "event_eos": 390,
        "event_vocab_size": 391
    },
    "paths": {
        "raw_midi": "/data/musae3.0/" if remote else "D:",
        "dataset": ("/data/musae3.0/" if remote else "D:") + os.sep + "lmd_matched_converted_8",
        "test": ("/data/musae3.0" if remote else "D:") + os.sep + "test_converted_8",
        "checkpoints": ("/data/musae3.0/" if remote else ".") + os.sep + "musae_model_checkpoints_8"
    }
}


def get_freer_gpu():
    os.system('nvidia-smi -q -d Memory |grep -A4 GPU|grep Free >tmp')
    memory_available = [int(x.split()[2]) for x in open('tmp', 'r').readlines()]
    return np.argmax(memory_available)


def set_freer_gpu():
    if remote:
        os.environ["CUDA_DEVICE_ORDER"] = "PCI_BUS_ID"
        gpu = str(get_freer_gpu())
        os.environ["CUDA_VISIBLE_DEVICES"] = gpu
        print("Remote execution on gpu ", gpu)
    else:
        print("Local execution")

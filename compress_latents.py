import torch.nn as nn
from config import config
import torch


class LatentCompressor(nn.Module):
    def __init__(self, d_model=config["model"]["d_model"]):
        super(LatentCompressor, self).__init__()
        self.compressor = nn.Linear(d_model*4, d_model)

    def forward(self, latent):
        n_batch, n_track, seq_len, d_model = latent.shape
        latent = latent.reshape(n_batch, seq_len, d_model*4)
        latent = self.compressor(latent)
        # latent = latent[:, :config["model"]["n_latents"], :]
        latent = torch.mean(latent, dim=1, keepdim=True)
        latent = latent.reshape(n_batch, -1)
        return latent

import torch.nn as nn
import torch
import math
from torch.nn import functional as F
import copy
from config import config
from torch.autograd import Variable


class CompressiveEncoder(nn.Module):
    def __init__(self,
                 d_model=config["model"]["d_model"],
                 heads=config["model"]["heads"],
                 ff_mul=config["model"]["ff_mul"],
                 attn_layer_dropout=config["model"]["attn_layer_dropout"],
                 reconstruction_attn_dropout=config["model"]["reconstruction_attn_dropout"],
                 ff_dropout=config["model"]["ff_dropout"],
                 layers=config["model"]["layers"],
                 vocab_size=config["tokens"]["vocab_size"],
                 seq_len=config["model"]["seq_len"],
                 mem_len=config["model"]["mem_len"],
                 cmem_len=config["model"]["cmem_len"],
                 cmem_ratio=config["model"]["cmem_ratio"],
                 device=config["train"]["device"]
                 ):
        super(CompressiveEncoder, self).__init__()
        assert mem_len >= seq_len, 'length of memory should be at least the sequence length'
        assert cmem_len >= (mem_len // cmem_ratio), f'len of cmem should be at least ' f'{int(mem_len // cmem_ratio)}' \
                                                    f' but it is ' f'{int(cmem_len)}'

        self.pos_emb = nn.Parameter(
            torch.zeros(4, heads, seq_len * 2 + mem_len + cmem_len, d_model // heads, device=device,
                        requires_grad=True))
        c = copy.deepcopy

        self_mem_attn = Residual(PreNorm(d_model, MyMemoryAttention(heads, d_model, seq_len,
                                                                    mem_len, cmem_len, cmem_ratio,
                                                                    attn_dropout=attn_layer_dropout,
                                                                    reconstruction_attn_dropout=reconstruction_attn_dropout)))

        ff = Residual(PreNorm(d_model, FeedForward(d_model, ff_mul, dropout=ff_dropout)))

        encoder = Encoder(EncoderLayer(c(self_mem_attn), c(ff)), layers, vocab_size, d_model)
        self.drums_encoder = c(encoder)
        self.bass_encoder = c(encoder)
        self.guitar_encoder = c(encoder)
        self.strings_encoder = c(encoder)
        for p in self.parameters():
            if p.dim() > 1:
                nn.init.xavier_uniform_(p)

    def forward(self, seq, mask, mems, cmems):
        d_z, d_mem, d_cmem, d_l, daw = self.drums_encoder(seq[0, ...], mask[0, ...], mems[0, ...],
                                                          cmems[0, ...], self.pos_emb[0, ...])
        b_z, b_mem, b_cmem, b_l, baw = self.bass_encoder(seq[1, ...], mask[1, ...], mems[1, ...],
                                                         cmems[1, ...], self.pos_emb[1, ...])
        g_z, g_mem, g_cmem, g_l, gaw = self.guitar_encoder(seq[2, ...], mask[2, ...], mems[2, ...],
                                                           cmems[2, ...], self.pos_emb[2, ...])
        s_z, s_mem, s_cmem, s_l, saw = self.strings_encoder(seq[3, ...], mask[3, ...], mems[3, ...],
                                                            cmems[3, ...], self.pos_emb[3, ...])
        mems = torch.stack([d_mem, b_mem, g_mem, s_mem])
        cmems = torch.stack([d_cmem, b_cmem, g_cmem, s_cmem])
        latents = torch.stack([d_z, b_z, g_z, s_z], dim=1)
        aux_loss = torch.stack((d_l, b_l, g_l, s_l)).mean()
        # aws = torch.mean(torch.stack([daw, baw, gaw, saw], dim=0), dim=0)
        aws = torch.stack([daw, baw, gaw, saw], dim=0)
        return latents, mems, cmems, aux_loss, aws


class CompressiveDecoder(nn.Module):
    def __init__(self,
                 d_model=config["model"]["d_model"],
                 heads=config["model"]["heads"],
                 ff_mul=config["model"]["ff_mul"],
                 ff_dropout=config["model"]["ff_dropout"],
                 reconstruction_attn_dropout=config["model"]["reconstruction_attn_dropout"],
                 attn_layer_dropout=config["model"]["attn_layer_dropout"],
                 layers=config["model"]["layers"],
                 vocab_size=config["tokens"]["vocab_size"],
                 seq_len=config["model"]["seq_len"],
                 mem_len=config["model"]["mem_len"],
                 cmem_len=config["model"]["cmem_len"],
                 cmem_ratio=config["model"]["cmem_ratio"],
                 device=config["train"]["device"]
                 ):
        super(CompressiveDecoder, self).__init__()
        assert mem_len >= seq_len, 'length of memory should be at least the sequence length'
        assert cmem_len >= (mem_len // cmem_ratio), f'len of cmem should be at least ' f'{int(mem_len // cmem_ratio)}' \
                                                    f' but it is ' f'{int(cmem_len)}'
        self.pos_emb = nn.Parameter(torch.zeros(4, heads, seq_len + mem_len + cmem_len, d_model // heads, device=device,
                                                requires_grad=True))
        c = copy.deepcopy
        self_mem_attn = Residual(PreNorm(d_model, MyMemoryAttention(heads, d_model, seq_len,
                                                                    mem_len, cmem_len, cmem_ratio,
                                                                    attn_dropout=attn_layer_dropout,
                                                                    reconstruction_attn_dropout=reconstruction_attn_dropout)))
        src_attn = Residual(PreNorm(d_model, MultiHeadedAttention(heads, d_model, dropout=0.1)))
        ff = Residual(PreNorm(d_model, FeedForward(d_model, ff_mul, dropout=ff_dropout)))

        decoder = Decoder(DecoderLayer(c(self_mem_attn), c(src_attn), c(ff)), layers, vocab_size, d_model)

        self.drums_decoder = c(decoder)
        self.bass_decoder = c(decoder)
        self.guitar_decoder = c(decoder)
        self.strings_decoder = c(decoder)
        self.generator = Generator(d_model, vocab_size)
        for p in self.parameters():
            if p.dim() > 1:
                nn.init.xavier_uniform_(p)

    def forward(self, trg, trg_mask, src_mask, latent, d_mems, d_cmems, just=None, emb_weights=None):
        src_mask = None  # TODO fix architecture
        #  before each decoder received src_mask[0, ...] src_mask[1, ...] etc.
        if just is None:
            d_out, d_self_w, d_src_w, d_mem, d_cmem, d_loss = self.drums_decoder(trg[0, ...],
                                                                                 trg_mask[0, ...],
                                                                                 None,
                                                                                 latent,
                                                                                 d_mems[0, ...], d_cmems[0, ...],
                                                                                 self.pos_emb[0, ...],
                                                                                 emb_weights=emb_weights[0, ...] if emb_weights is not None else None)
            b_out, b_self_w, b_src_w, b_mem, b_cmem, b_loss = self.bass_decoder(trg[1, ...],
                                                                                trg_mask[1, ...],
                                                                                None,
                                                                                latent,
                                                                                d_mems[1, ...], d_cmems[1, ...],
                                                                                self.pos_emb[1, ...],
                                                                                emb_weights=emb_weights[1, ...] if emb_weights is not None else None)
            g_out, g_self_w, g_src_w, g_mem, g_cmem, g_loss = self.guitar_decoder(trg[2, ...],
                                                                                  trg_mask[2, ...],
                                                                                  None,
                                                                                  latent,
                                                                                  d_mems[2, ...], d_cmems[2, ...],
                                                                                  self.pos_emb[2, ...],
                                                                                  emb_weights=emb_weights[2, ...] if emb_weights is not None else None)
            s_out, s_self_w, s_src_w, s_mem, s_cmem, s_loss = self.strings_decoder(trg[3, ...],
                                                                                   trg_mask[3, ...],
                                                                                   None,
                                                                                   latent,
                                                                                   d_mems[3, ...], d_cmems[3, ...],
                                                                                   self.pos_emb[3, ...],
                                                                                   emb_weights=emb_weights[3, ...] if emb_weights is not None else None)
            mems = torch.stack([d_mem, b_mem, g_mem, s_mem])
            cmems = torch.stack([d_cmem, b_cmem, g_cmem, s_cmem])
            output = torch.stack([d_out, b_out, g_out, s_out], dim=0)
            output = self.generator(output)
            aux_loss = torch.stack((d_loss, b_loss, g_loss, s_loss))
            aux_loss = torch.mean(aux_loss)
            self_weights = torch.stack([d_self_w, b_self_w, g_self_w, s_self_w], dim=0)
            src_weights = torch.stack([d_src_w, b_src_w, g_src_w, s_src_w])
            return output, self_weights, src_weights, mems, cmems, aux_loss
        else:
            if just == "drums":
                out, _, _, _, _, _ = self.drums_decoder(trg,
                                                        trg_mask,
                                                        None,
                                                        latent,
                                                        d_mems[0, ...], d_cmems[0, ...],
                                                        self.pos_emb[0, ...])
                out = self.generator(out, just=just)
                return out, None, None, None, None, None
            elif just == "bass":
                out, _, _, _, _, _ = self.bass_decoder(trg,
                                                       trg_mask,
                                                       None,
                                                       latent,
                                                       d_mems[1, ...], d_cmems[1, ...],
                                                       self.pos_emb[1, ...])
                out = self.generator(out, just=just)
                return out, None, None, None, None, None
            elif just == "guitar":
                out, _, _, _, _, _ = self.guitar_decoder(trg,
                                                         trg_mask,
                                                         None,
                                                         latent,
                                                         d_mems[2, ...], d_cmems[2, ...],
                                                         self.pos_emb[2, ...])
                out = self.generator(out, just=just)
                return out, None, None, None, None, None
            elif just == "strings":
                out, _, _, _, _, _ = self.strings_decoder(trg,
                                                          trg_mask,
                                                          None,
                                                          latent,
                                                          d_mems[3, ...], d_cmems[3, ...],
                                                          self.pos_emb[3, ...])
                out = self.generator(out, just=just)
                return out, None, None, None, None, None


class Encoder(nn.Module):
    def __init__(self, layer, N, vocab_size, d_model):
        super(Encoder, self).__init__()
        self.layers = clones(layer, N)
        self.embed = nn.Embedding(vocab_size, d_model)
        self.pos = PositionalEncoding(d_model)
        self.N = N

    def forward(self, seq, mask, mems, cmems, pos_emb):
        attn_losses = torch.tensor(0., requires_grad=True, device=seq.device, dtype=torch.float32)
        seq = self.embed(seq)
        # seq = self.pos(seq)
        new_mems = []
        new_cmems = []
        self_weights = []
        for layer, mem, cmem in zip(self.layers, mems, cmems):
            seq, new_mem, new_cmem, attn_loss, attn = layer(seq, (mem, cmem), mask, pos_emb)  # pos_emb
            self_weights.append(attn)
            new_mems.append(new_mem)
            new_cmems.append(new_cmem)
            attn_losses = attn_losses + attn_loss
        # self_weights = torch.mean(torch.stack(self_weights, dim=0), dim=
        self_weights = torch.stack(self_weights, dim=0)
        new_mems = torch.stack(new_mems)
        new_cmems = torch.stack(new_cmems)
        attn_loss = attn_losses / self.N  # normalize w.r.t number of layers
        return seq, new_mems, new_cmems, attn_loss, self_weights


class Decoder(nn.Module):
    """Generic N layer decoder with masking."""

    def __init__(self, layer, N, vocab_size, d_model):
        super(Decoder, self).__init__()
        self.layers = clones(layer, N)
        self.embed = nn.Embedding(vocab_size, d_model)
        self.pos = PositionalEncoding(d_model)
        self.N = N

    def forward(self, trg, trg_mask, src_mask, latent, mems, cmems, pos_emb, emb_weights=None):
        attn_losses = torch.tensor(0., requires_grad=True, device=trg.device, dtype=torch.float32)
        if emb_weights is None:
            trg = self.embed(trg)
        else:  # compute weighted sum of the embeddings
            mix = torch.zeros((trg.shape[0], trg.shape[1], config["model"]["d_model"]), dtype=torch.float32,
                              device=trg.device)
            for i in range(trg.shape[-1]):
                emb = self.embed(trg[..., i]) * emb_weights[..., i].unsqueeze(-1).expand_as(mix)
                mix = mix + emb
            trg = mix
        # trg = self.pos(trg)
        new_mems = []
        new_cmems = []
        self_weights = []
        src_weights = []
        for layer, mem, cmem in zip(self.layers, mems, cmems):
            trg, new_mem, new_cmem, self_weight, src_weight, attn_loss = layer(trg, trg_mask, src_mask, latent,
                                                                               (mem, cmem), pos_emb)  # pos_emb
            self_weights.append(self_weight)
            src_weights.append(src_weight)
            new_mems.append(new_mem)
            new_cmems.append(new_cmem)
            attn_losses = attn_losses + attn_loss
        # src_weights = torch.mean(torch.stack(src_weights, dim=0), dim=(0, 1, 2))
        # self_weights = torch.mean(torch.stack(self_weights, dim=0), dim=(0, 1, 2))  # mn of layer batch instruments
        src_weights = torch.stack(src_weights, dim=0)
        self_weights = torch.stack(self_weights, dim=0)
        new_mems = torch.stack(new_mems)
        new_cmems = torch.stack(new_cmems)
        attn_losses = attn_losses / self.N  # normalize w.r.t number of layers
        return trg, self_weights, src_weights, new_mems, new_cmems, attn_losses


class EncoderLayer(nn.Module):
    def __init__(self, mem_attn, feed_forward):
        super(EncoderLayer, self).__init__()
        self.mem_attn = mem_attn
        self.feed_forward = feed_forward

    def forward(self, x, memories, input_mask, pos_emb):
        x, m, cm, attn_loss, attn = self.mem_attn(x, memories=memories, input_mask=input_mask, pos_emb=pos_emb)
        x, = self.feed_forward(x)
        return x, m, cm, attn_loss, attn


class DecoderLayer(nn.Module):
    """Decoder is made of self-attn, src-attn, and feed forward (defined below)"""

    def __init__(self, self_mem_attn, src_attn, feed_forward):
        super(DecoderLayer, self).__init__()
        self.self_mem_attn = self_mem_attn
        self.src_attn = src_attn
        self.feed_forward = feed_forward

    def forward(self, x, trg_mask, src_mask, latent, memories, pos_emb):
        x, new_mem, new_cmem, attn_loss, self_weights = self.self_mem_attn(x, memories=memories, input_mask=trg_mask,
                                                                           pos_emb=pos_emb)
        x, src_weights = self.src_attn(x, key=latent, value=latent, mask=src_mask)  # TODO FIX src_mask!!!
        x, = self.feed_forward(x)
        return x, new_mem, new_cmem, self_weights, src_weights, attn_loss


class MyMemoryAttention(nn.Module):
    def __init__(self, h, dim, seq_len, mem_len, cmem_len, cmem_ratio, attn_dropout=0.1,
                 reconstruction_attn_dropout=0.1):
        super(MyMemoryAttention, self).__init__()
        assert dim % h == 0
        self.dim_head = dim // h
        self.h = h
        self.seq_len = seq_len
        self.mem_len = mem_len
        self.cmem_len = cmem_len
        self.cmem_ratio = cmem_ratio
        self.scale = self.dim_head ** (-0.5)  # 1/root(dim_head)
        self.compress_mem_fn = ConvCompress(dim, cmem_ratio)
        self.reconstruction_attn_dropout = nn.Dropout(reconstruction_attn_dropout)
        self.multi_head_attention = MultiHeadedAttention(h, dim, attn_dropout)
        self.norm1 = nn.LayerNorm(dim)

    def forward(self, h, memories=None, input_mask=None, pos_emb=None):
        # Prepare mask
        if input_mask is not None:
            if input_mask.dim() == 2:  # encoder mask, cover just pad
                input_mask = input_mask[:, :, None] * input_mask[:, None, :]
            input_mask = F.pad(input_mask, (self.cmem_len + self.mem_len, 0), value=True)
        # Algorithm from paper
        m, cm = memories
        mem = torch.cat((cm, m, h), dim=1)  # TODO x too?
        a, weights = self.multi_head_attention(h, key=mem, value=mem, mask=input_mask, pos_emb=pos_emb)
        a = self.norm1(a + h)
        old_mem = m[:, :self.seq_len, :]
        new_cm = self.compress_mem_fn(old_mem)
        m = torch.cat((m, h), dim=1)[:, -self.mem_len:, :]
        cm = torch.cat((cm, new_cm), dim=1)[:, -self.cmem_len:, :]
        h = a
        # Attention reconstruction
        h_copy = h.detach().clone()
        old_mem = torch.detach(old_mem)
        Q = torch.detach(self.multi_head_attention.linears[0].weight.data)
        K = torch.detach(self.multi_head_attention.linears[1].weight.data)
        V = torch.detach(self.multi_head_attention.linears[2].weight.data)

        def attn(hh, mm):
            n_batches = hh.shape[0]
            hQ = torch.matmul(hh, Q).view(n_batches, -1, self.h, self.dim_head).transpose(1, 2)
            mK = torch.matmul(mm, K).view(n_batches, -1, self.h, self.dim_head).transpose(1, 2)
            mV = torch.matmul(mm, V).view(n_batches, -1, self.h, self.dim_head).transpose(1, 2)
            attention, _ = full_attn(hQ, mK, mV, dropout=self.reconstruction_attn_dropout)
            return attention

        new_cm = self.compress_mem_fn(old_mem)
        l_attn = F.mse_loss(attn(h_copy, old_mem), attn(h_copy, new_cm))

        return h, m, cm, l_attn, weights


class MultiHeadedAttention(nn.Module):
    def __init__(self, h, d_model, dropout=0.1):
        super(MultiHeadedAttention, self).__init__()
        assert d_model % h == 0
        self.d_out = d_model // h
        self.h = h
        self.linears = (clones(nn.Linear(d_model, d_model, bias=False), 4))  # TODO bias or not?
        self.dropout = nn.Dropout(p=dropout)

    def forward(self, query, key=None, value=None, mask=None, pos_emb=None):
        if mask is not None:  # apply same mask to all heads
            if mask.dim() == 2:
                mask = mask[:, :, None] * mask[:, None, :]
            mask = mask.unsqueeze(1)
        n_batches = query.size(0)
        query, key, value = [l(x).view(n_batches, -1, self.h, self.d_out).transpose(1, 2)
                             for l, x in zip(self.linears, (query, key, value))]
        x, weights = full_attn(query, key, value, mask=mask, dropout=self.dropout, pos_emb=pos_emb)
        x = x.transpose(1, 2).contiguous().view(n_batches, -1, self.h * self.d_out)
        return self.linears[-1](x), weights


class FeedForward(nn.Module):
    def __init__(self, dim, ff_mul, dropout=0.):
        super().__init__()
        activation = nn.GELU
        self.w1 = nn.Linear(dim, dim * ff_mul)
        self.act = activation()
        self.dropout = nn.Dropout(dropout)
        self.w2 = nn.Linear(dim * ff_mul, dim)

    def forward(self, x):
        x = self.w1(x)
        x = self.act(x)
        x = self.dropout(x)
        x = self.w2(x)
        return x


class Residual(nn.Module):
    def __init__(self, fn):
        super().__init__()
        self.fn = fn

    def forward(self, x, **kwargs):
        out = self.fn(x, **kwargs)
        out = cast_tuple(out)
        ret = (out[0] + x), *out[1:]
        return ret


class PreNorm(nn.Module):
    def __init__(self, dim, fn):
        super().__init__()
        self.norm = nn.LayerNorm(dim)
        self.fn = fn

    def forward(self, x, **kwargs):
        x = self.norm(x)
        return self.fn(x, **kwargs)


class Generator(nn.Module):
    """Define standard linear + softmax generation step."""

    def __init__(self, d_model, vocab):
        super(Generator, self).__init__()
        self.proj_drums = nn.Linear(d_model, vocab)
        self.proj_bass = nn.Linear(d_model, vocab)
        self.proj_guitar = nn.Linear(d_model, vocab)
        self.proj_strings = nn.Linear(d_model, vocab)

    def forward(self, x, just=None):
        if just is None:
            out_drums = F.log_softmax(self.proj_drums(x[0]), dim=-1)
            out_bass = F.log_softmax(self.proj_bass(x[1]), dim=-1)
            out_guitar = F.log_softmax(self.proj_guitar(x[2]), dim=-1)
            out_strings = F.log_softmax(self.proj_strings(x[3]), dim=-1)
            out = torch.stack([out_drums, out_bass, out_guitar, out_strings], dim=0)
            return out
        elif just == "drums":
            out = F.log_softmax(self.proj_drums(x), dim=-1)
            return out
        elif just == "bass":
            out = F.log_softmax(self.proj_bass(x), dim=-1)
            return out
        elif just == "guitar":
            out = F.log_softmax(self.proj_guitar(x), dim=-1)
            return out
        elif just == "strings":
            out = F.log_softmax(self.proj_strings(x), dim=-1)
            return out


class ConvCompress(nn.Module):
    def __init__(self, dim, ratio=4):
        super().__init__()
        self.conv = nn.Conv1d(dim, dim, ratio, stride=ratio)

    def forward(self, mem):
        mem = mem.transpose(1, 2)
        compressed_mem = self.conv(mem)
        return compressed_mem.transpose(1, 2)


class Embeddings(nn.Module):
    def __init__(self, vocab, d_model):
        super(Embeddings, self).__init__()
        self.lut = nn.Embedding(vocab, d_model)
        self.d_model = d_model

    def forward(self, x):
        aux = self.lut(x)
        return aux * math.sqrt(self.d_model)


def full_attn(q, k, v, mask=None, dropout=None, pos_emb=None):
    *_, dim = q.shape
    dots = torch.einsum('bhid,bhjd->bhij', q, k) * (dim ** -0.5)  # Q K^T

    if pos_emb is not None:
        # pos_emb = pos_emb[:, -(k.shape[-2] + v.shape[-2]):].type(q.dtype) TODO add if use lucidrains memattn
        # pos_dots = torch.einsum('bhid,hjd->bhij', q, pos_emb) * (q.shape[-1] ** 0.5)  TODO remove we have dim
        pos_dots = torch.einsum('bhid,hjd->bhij', q, pos_emb) * (dim ** 0.5)
        pos_dots = shift(pos_dots)  # left upper triangular has positional embedding of illegal token
        pos_dots = pos_dots[..., :dots.shape[-1]]  # TODO select useful embedding, confirm or remove
        dots = dots + pos_dots

    if mask is not None:
        dots = dots.masked_fill(mask == 0, -1e9)  # same mask for all heads
    attn = dots.softmax(dim=-1)
    if dropout is not None:
        attn = dropout(attn)
    return torch.einsum('bhij,bhjd->bhid', attn, v), attn  # (Q K^T) V


def clones(module, N):
    """ Produce N identical layers."""
    return nn.ModuleList([copy.deepcopy(module) for _ in range(N)])


def max_neg_value(tensor):
    return -torch.finfo(tensor.dtype).max


def reshape_dim(t, dim, split_dims):
    """
    Reshape dimension dim of tensor t with split dims
    Ex: t = (2, 200, 16), dim = -1, split_dims = (-1, 4) ---> t = (2, 200, -1, 4)
    """
    shape = list(t.shape)
    num_dims = len(shape)
    dim = (dim + num_dims) % num_dims
    shape[dim:dim + 1] = split_dims
    return t.reshape(shape)


def shift(x):
    """
    It skews the matrix x, as done in Relative Local Attention of Music Transformer
    0, 0, a     a, 0, 0
    0, b, c =>  b, c, 0
    d, e, f     d, e, f
    """
    *_, i, j = x.shape
    zero_pad = torch.zeros((*_, i, i), **to(x))
    x = torch.cat([x, zero_pad], -1)
    l = i + j - 1
    x = x.view(*_, -1)
    zero_pad = torch.zeros(*_, -x.size(-1) % l, **to(x))
    shifted = torch.cat([x, zero_pad], -1).view(*_, -1, l)
    return shifted[..., :i, i - 1:]


def to(t):
    return {'dtype': t.dtype, 'device': t.device}


def queue_fifo(*args, length, dim=-2):
    queue = torch.cat(args, dim=dim)
    if length > 0:
        return split_at_index(dim, -length, queue)

    device = queue.device
    shape = list(queue.shape)
    shape[dim] = 0
    return queue, torch.empty(shape, device=device)


def split_at_index(dim, index, t):
    pre_slices = (slice(None),) * dim
    left = (*pre_slices, slice(None, index))
    right = (*pre_slices, slice(index, None))
    return t[left], t[right]


def cast_tuple(el):
    return el if isinstance(el, tuple) else (el,)


class MemorySelfAttention(nn.Module):
    def __init__(self, heads, dim, seq_len, mem_len, cmem_len, cmem_ratio=4, attn_dropout=0., dropout=0.,
                 reconstruction_attn_dropout=0., one_kv_head=False):
        super().__init__()
        assert (dim % heads) == 0, 'dimension must be divisible by the number of heads'

        self.heads = heads
        self.dim_head = dim // heads
        self.seq_len = seq_len
        self.mem_len = mem_len
        self.cmem_len = cmem_len
        self.cmem_ratio = cmem_ratio
        self.scale = self.dim_head ** (-0.5)

        self.compress_mem_fn = ConvCompress(dim, cmem_ratio)

        self.to_q = nn.Linear(dim, dim, bias=False)

        kv_dim = self.dim_head if one_kv_head else dim
        self.to_kv = nn.Linear(dim, kv_dim * 2, bias=False)
        self.to_out = nn.Linear(dim, dim)

        self.attn_dropout = nn.Dropout(attn_dropout)
        self.dropout = nn.Dropout(dropout)

        self.reconstruction_attn_dropout = nn.Dropout(reconstruction_attn_dropout)

    def forward(self, x, memories=None, pos_emb=None, input_mask=None, calc_memory=True, concat_q=True):
        b, t, e, h, dim_h = *x.shape, self.heads, self.dim_head

        mem, cmem = memories

        mem_len = mem.shape[1]
        cmem_len = cmem.shape[1]

        q = self.to_q(x)

        if concat_q:
            kv_input = torch.cat((cmem, mem, x), dim=1)
        else:
            kv_input = torch.cat((cmem, mem), dim=1)
        kv_len = kv_input.shape[1]
        k, v = self.to_kv(kv_input).chunk(2, dim=-1)

        merge_heads = lambda x: reshape_dim(x, -1, (-1, dim_h)).transpose(1, 2)
        q, k, v = map(merge_heads, (q, k, v))

        k, v = map(lambda x: x.expand(-1, h, -1, -1), (k, v))

        dots = torch.einsum('bhid,bhjd->bhij', q, k) * self.scale
        mask_value = max_neg_value(dots)

        if pos_emb is not None:
            pos_emb = pos_emb[:, -kv_len:].type(q.dtype)
            pos_dots = torch.einsum('bhid,hjd->bhij', q, pos_emb) * self.scale
            pos_dots = shift(pos_dots)
            dots = dots + pos_dots

        if input_mask is not None:
            if input_mask.dim() == 2:
                mask = input_mask[:, None, :, None] * input_mask[:, None, None, :]
            else:
                mask = input_mask.unsqueeze(1)
            if concat_q:
                mask = F.pad(mask, (mem_len + cmem_len, 0), value=True)
            else:
                mask = F.pad(mask, (mem_len + cmem_len - self.seq_len, 0), value=True)
            dots.masked_fill_(~mask, mask_value)

        # total_mem_len = mem_len + cmem_len
        # mask = torch.ones(t, t + total_mem_len, **to(x)).triu_(diagonal = 1 + total_mem_len).bool()
        # dots.masked_fill_(mask[None, None, ...], mask_value)

        attn = dots.softmax(dim=-1)
        weights = attn.detach().clone()
        attn = self.attn_dropout(attn)

        out = torch.einsum('bhij,bhjd->bhid', attn, v)
        out = out.transpose(1, 2).reshape(b, t, -1)
        logits = self.to_out(out)
        logits = self.dropout(logits)

        new_mem = mem
        new_cmem = cmem
        aux_loss = torch.zeros(1, requires_grad=True, **to(q))

        # if self.seq_len > t or not calc_memory:
        #     return logits, Memory(new_mem, new_cmem), aux_loss

        # calculate memory and compressed memory

        old_mem, new_mem = queue_fifo(mem, x, length=self.mem_len, dim=1)
        old_mem_padding = old_mem.shape[1] % self.cmem_ratio

        if old_mem_padding != 0:
            old_mem = F.pad(old_mem, (0, 0, old_mem_padding, 0), value=0.)

        if old_mem.shape[1] == 0 or self.cmem_len <= 0:
            return logits, new_mem, new_cmem, aux_loss, weights

        compressed_mem = self.compress_mem_fn(old_mem)
        old_cmem, new_cmem = split_at_index(1, -self.cmem_len, torch.cat((cmem, compressed_mem), dim=1))

        # if not self.training:
        #     return logits, Memory(new_mem, new_cmem), aux_loss

        # calculate compressed memory auxiliary loss if training
        # old_mem = old_mem.detach()  # TODO detached
        # compressed_mem = self.compress_mem_fn(old_mem)

        freezed = self.to_kv.requires_grad_(False)
        cmem_k, cmem_v = freezed(compressed_mem).chunk(2, dim=-1)
        cmem_k, cmem_v = map(merge_heads, (cmem_k, cmem_v))
        cmem_k, cmem_v = map(lambda x: x.expand(-1, h, -1, -1), (cmem_k, cmem_v))

        old_mem_range = slice(- min(mem_len, self.mem_len) - self.seq_len, -self.seq_len)
        old_mem_k, old_mem_v = map(lambda x: x[:, :, old_mem_range].clone(), (k, v))

        q, old_mem_k, old_mem_v, cmem_k, cmem_v = map(torch.detach, (q, old_mem_k, old_mem_v, cmem_k, cmem_v))
        # q, old_mem_k, old_mem_v = map(torch.detach, (q, old_mem_k, old_mem_v))

        aux_loss = F.mse_loss(
            full_attn(q, old_mem_k, old_mem_v, dropout=self.reconstruction_attn_dropout)[0],
            full_attn(q, cmem_k, cmem_v, dropout=self.reconstruction_attn_dropout)[0]
        )

        return logits, new_mem, new_cmem, aux_loss, weights


class PositionalEncoding(nn.Module):
    "Implement the PE function."

    def __init__(self, d_model, dropout=0.1, max_len=5000):
        super(PositionalEncoding, self).__init__()
        self.dropout = nn.Dropout(p=dropout)

        # Compute the positional encodings once in log space.
        pe = torch.zeros(max_len, d_model)
        position = torch.arange(0, max_len).unsqueeze(1)
        div_term = torch.exp(torch.arange(0, d_model, 2) *
                             -(math.log(10000.0) / d_model))
        pe[:, 0::2] = torch.sin(position * div_term)
        pe[:, 1::2] = torch.cos(position * div_term)
        pe = pe.unsqueeze(0)
        self.register_buffer('pe', pe)

    def forward(self, x):
        x = x + Variable(self.pe[:, :x.size(1)],
                         requires_grad=False)
        return self.dropout(x)


#################################################
### THIS FILE WAS AUTOGENERATED! DO NOT EDIT! ###
#################################################
# file to edit: dev_nb/08a_lsuv.ipynb

from exp.nb_08 import *

def get_batch(dl, run):
    run.xb, run.yb = next(iter(dl))
    for cb in run.cbs: cb.set_runner(run)
    run('begin_batch')
    return run.xb, run.yb

def find_mods(m, func):
    if func(m): return [m]
    return sum([find_mods(o, func) for o in m.children()], [])

def is_lin_layer(l):
    layers = (nn.Conv1d, nn.Conv2d, nn.Conv3d, nn.Linear, nn.ReLU)
    return isinstance(l, layers)

def lsuv_append_stat(hook, mod, inp, outp):
    d = outp.data
    hook.mean, hook.std = d.mean().item(), d.std().item()

def lsuv_module(m, xb):
    h = Hook(m, lsuv_append_stat)

    while mdl(xb) is not None and abs(h.mean ) > 1e-3: m.bias -= h.mean
    while mdl(xb) is not None and abs(h.std-1) > 1e-3: m.weight.data /= h.std

    h.remove()
    return h.mean, h.std
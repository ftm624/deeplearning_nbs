
#################################################
### THIS FILE WAS AUTOGENERATED! DO NOT EDIT! ###
#################################################
# file to edit: dev_nb/10_optimizers.ipynb

from exp.nb_09a import *

def sgd_step(p, lr, **kwargs):
    p.data.add_(-lr, p.grad.data)
    return p

class AvgStats():
    def __init__(self, metrics, in_train):
        self.metrics = listify(metrics)
        self.in_train = in_train

    def reset(self):
        self.tot_loss = 0.
        self.count = 0
        self.tot_mets = [0.]*len(self.metrics)

    @property
    def all_stats(self):
        return [self.tot_loss.item()] + [o.item() for o in self.tot_mets]

    @property
    def avg_stats(self):
        return [o/self.count for o in self.all_stats]

    def __repr__(self):
        if not self.count: return "Something went wrong: count is zero."
        if self.in_train:
            return f"Train: {[round(o,4) for o in self.avg_stats]}"
        else:
            return f"Valid: {[round(o,4) for o in self.avg_stats]}\n"

    def accumulate(self, run):
        bn = run.xb.shape[0]
        self.tot_loss += run.loss * bn
        self.count += bn
        for i, m in enumerate(self.metrics):
            self.tot_mets[i] += m(run.pred, run.yb) * bn

class AvgStatsCallback(Callback):
    def __init__(self, metrics):
        self.train_stats = AvgStats(metrics, True)
        self.valid_stats = AvgStats(metrics, False)

    def begin_epoch(self):
        self.train_stats.reset()
        self.valid_stats.reset()

    def after_loss(self):
        stats = self.train_stats if self.in_train else self.valid_stats
        with torch.no_grad():
            stats.accumulate(self.run)

    def after_epoch(self):
        print(self.train_stats)
        print(self.valid_stats)

class Recorder(Callback):
    def begin_fit(self):
        self.losses = []
        self.lrs = []

    def after_batch(self):
        if not self.in_train: return
        self.lrs.append(self.opt.hypers[-1]['lr'])
        self.losses.append(self.loss.detach().cpu())

    def plot_loss(self): plt.plot(self.losses)
    def plot_lr  (self): plt.plot(self.lrs)

    def plot(self, skip_last=0):
        losses = [o.item() for o in self.losses]
        n = len(losses)-skip_last
        plt.xscale('log')
        plt.plot(self.lrs[:n], losses[:n])

class ParamScheduler(Callback):
    _order = 1
    def __init__(self, pname, sched_funcs):
        self.pname = pname
        self.sched_funcs = listify(sched_funcs)

    def begin_batch(self):
        if not self.in_train: return # end if not in train mode
        fs = self.sched_funcs # list of scheduler funcs
        if len(fs)==1: # if only 1 scheduler multiple it and use it for each group
            fs = fs*len(self.opt.param_groups)
        pos = self.n_epochs/self.epochs # position in training
        for scheduler, hyper in zip(fs, self.opt.hypers):
            hyper[self.pname] = scheduler(pos) # change the pname according to the scheduler


class LR_Find(Callback):
    _order = 1

    def __init__(self, max_iter=100, min_lr=1e-6, max_lr=10):
        self.max_iter = max_iter
        self.min_lr = min_lr
        self.max_lr = max_lr
        self.best_loss = 1e9

    def begin_batch(self):
        if not self.in_train: return
        pos = self.n_iter/self.max_iter
        lr = self.min_lr * (self.max_lr/self.min_lr) ** pos
        for pg in self.opt.hypers: pg['lr'] = lr # change from opt.param_groups

    def after_step(self):
        if self.n_iter >= self.max_iter or self.loss > self.best_loss*10:
            raise CancelTrainException
        if self.loss < self.best_loss:
            self.best_loss = self.loss

def l2_reg(p, lr, wd, **kwargs):
    p.grad.data.add_(wd, p.data) # scalar times parameter and then add to gradient
    return p

l2_reg._defaults = dict(wd=0.)

def weight_decay(p, lr, wd, **kwargs):
    p.data.mul_(1 - lr*wd)
    return p

weight_decay._defaults = dict(wd=0.)

def get_defaults(d):
    return getattr(d, "_defaults", {})

def maybe_update(steppers, dest, func):
    for s in steppers:
        for k,v in func(s).items():
            if not k in dest: dest[k] = v

class Optimizer():
    def __init__(self, params, steppers, **defaults):
        self.steppers = listify(steppers) # add stepper functions
        maybe_update(self.steppers, defaults, get_defaults) # get defaults
        self.param_groups = list(params)
        if not isinstance(self.param_groups[0], list):
            self.param_groups = [self.param_groups]
        self.hypers = [{**defaults} for p in self.param_groups] # make dict of hyper

    def grad_params(self):
        return [(p, hyper) for pg, hyper in zip(self.param_groups, self.hypers)
                for p in pg if p.grad is not None]

    def zero_grad(self):
        for p, hyper in self.grad_params():
            p.grad.detach_()
            p.grad.zero_()

    def step(self):
        for p, hyper in self.grad_params():
            compose(p, self.steppers, **hyper)

sgd_opt = partial(Optimizer, steppers=[weight_decay, sgd_step])

class StatefulOptimizer(Optimizer):
    def __init__(self, params, steppers, stats=None, **defaults):
        self.stats = listify(stats)
        maybe_update(self.stats, defaults, get_defaults)
        super().__init__(params, steppers, **defaults)
        self.state = {}

    def step(self):
        for p, hyper in self.grad_params():
            if p not in self.state:
                self.state[p] = {}
                maybe_update(self.stats, self.state[p], lambda o: o.init_state(p))
            state = self.state[p]
            for stat in self.stats:
                state = stat.update(p, state, **hyper)
            compose(p, self.steppers, **state, **hyper)
            self.state[p] = state

class Stat():
    _defaults = {}
    def init_state(self, p):
        raise NotImplementedError
    def update(self, p, state, **kwargs):
        raise NotImplementedError

def momentum_step(p, lr, grad_avg, **kwargs):
    p.data.add_(-lr, grad_avg)
    return p

class AverageGrad(Stat):
    _defaults = dict(mom=0.9)

    def __init__(self, dampening:bool=False):
        self.dampening=dampening

    def init_state(self, p):
        return {'grad_avg': torch.zeros_like(p.grad.data)}

    def update(self, p, state, mom, **kwargs):
        state['mom_damp'] = 1-mom if self.dampening else 1.
        state['grad_avg'].mul_(mom).add_(state['mom_damp'], p.grad.data)
        return state

class AverageSqrGrad(Stat):
    _defaults = dict(sqr_mom=0.99)

    def __init__(self, dampening:bool=True):
        self.dampening=dampening

    def init_state(self, p):
        return {'sqr_avg': torch.zeros_like(p.grad.data)}

    def update(self, p, state, sqr_mom, **kwargs):
        state['sqr_damp'] = 1-sqr_mom if self.dampening else 1.
        state['sqr_avg'].mul_(sqr_mom).addcmul_(state['sqr_damp'], p.grad.data, p.grad.data)
        return state

class StepCount(Stat):
    def init_state(self, p): return {'step': 0}
    def update(self, p, state, **kwargs):
        state['step'] += 1
        return state

def debias(mom, damp, step): return damp * (1 - mom**step) / (1-mom)

def adam_step(p, lr, mom, mom_damp, step, sqr_mom, sqr_damp, grad_avg, sqr_avg, eps, **kwargs):
    debias1 = debias(mom,     mom_damp, step)
    debias2 = debias(sqr_mom, sqr_damp, step)
    p.data.addcdiv_(-lr / debias1, grad_avg, (sqr_avg/debias2).sqrt() + eps)
    return p

adam_step._defaults = dict(eps=1e-5)

def adam_opt(xtra_step=None, **kwargs):
    return partial(StatefulOptimizer, steppers=[adam_step,weight_decay]+listify(xtra_step),
                   stats=[AverageGrad(dampening=True), AverageSqrGrad(), StepCount()], **kwargs)
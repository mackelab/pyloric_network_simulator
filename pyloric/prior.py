from typing import Dict, Optional, Tuple, List

import numpy as np
import pandas as pd
import torch

from sbi.utils import BoxUniform
from pyloric.utils import select_names, ensure_array_not_scalar


def create_prior(
    lower_bound: Optional[np.ndarray] = None,
    upper_bound: Optional[np.ndarray] = None,
    customization: Dict = {},
    synapses_log_space: bool = True,
) -> "pd_prior":
    """
    Return prior over circuit parameters of the pyloric network.

    Args:
        lower_bound: Lower bound of the prior. If `None`, use the values used in
            Goncalves et al. 2020. If passed, it must be a 1D array with as many
            elements as `True` values in `customization`.
        upper_bound: Upper bound of the prior. If `None`, use the values used in
            Goncalves et al. 2020. If passed, it must be a 1D array with as many
            elements as `True` values in `customization`.
        customization: If you want to exclude some of the circuit_parameters and use
            constant default values for them, you have to set these entries to `False`
            in the `membrane_gbar` key in the `customization` dictionary. If you want
            to include $Q_{10}$ values, you have to set them in this dictionary.
        synapses_log_space: Whether the synapses will be uniformly distributed in
            logarithmic space or not (=in linear space).

    Returns:
        A uniform prior distribution.
    """

    setups = {
        "membrane_gbar": [
            [True, True, True, True, True, True, True, True],
            [True, True, True, True, True, True, True, True],
            [True, True, True, True, True, True, True, True],
        ],
        "Q10_gbar_mem": [False, False, False, False, False, False, False, False],
        "Q10_gbar_syn": [False, False],  # first for glutamate, second for choline
        "Q10_tau_m": [False],
        "Q10_tau_h": [False],
        "Q10_tau_CaBuff": [False],
        "Q10_tau_syn": [False, False],  # first for glutamate, second for choline
    }
    setups.update(customization)
    for key in setups.keys():
        setups[key] = ensure_array_not_scalar(setups[key])

    l_bound, u_bound = prior_bounds(setups, synapses_log_space=synapses_log_space)
    if lower_bound is None:
        lower_bound = l_bound
    if upper_bound is None:
        upper_bound = u_bound
    type_names, channel_names = select_names(setups)

    class pd_prior:
        """Wrapper for the pytorch prior such that it returns pandas samples."""

        def __init__(self, lower, upper, parameter_names):
            self.lower = torch.tensor(lower)
            self.upper = torch.tensor(upper)
            self.names = parameter_names
            self.numerical_prior = BoxUniform(self.lower, self.upper)

        def sample(self, sample_shape):
            numerical_sample = self.numerical_prior.sample(sample_shape).numpy()
            return pd.DataFrame(numerical_sample, columns=self.names)

        def log_prob(self, theta):
            numerical_theta = theta.to_numpy()
            return self.numerical_prior.log_prob(numerical_theta)

    prior = pd_prior(lower_bound, upper_bound, [type_names, channel_names])

    return prior


def prior_bounds(
    setups: Dict, synapses_log_space: bool = True
) -> Tuple[np.ndarray, np.ndarray]:
    """
    Returns the lower and upper bound for the prior as used in Goncalves et al. 2020.

    Args:
        setups: If you want to exclude some of the circuit_parameters and use
            constant default values for them, you have to set these entries to `False`
            in the `membrane_gbar` key in the `customization` dictionary. If you want
            to include $Q_{10}$ values, you have to set them in this dictionary.
        synapses_log_space: Whether the synapses will be uniformly distributed in
            logarithmic space or not (=in linear space).

    Returns:
        Lower and upper bound of the prior.
    """

    gbar_l, gbar_u = _get_min_max_membrane_gbar(setups["membrane_gbar"])
    syn_l, syn_u = _get_min_max_synapse_gbar(1e-08, 0.001, log_space=synapses_log_space)

    # Prior bounds for Q10 values.
    g_min = 1.0
    g_max = 2.0
    tau_min = 1.0
    tau_max = 4.0

    q10_mem_gbar_l, q10_mem_gbar_u = _select(g_min, g_max, setups["Q10_gbar_mem"])
    q10_syn_gbar_l, q10_syn_gbar_u = _select(g_min, g_max, setups["Q10_gbar_syn"])
    q10_tau_m_l, q10_tau_m_u = _select(tau_min, tau_max, setups["Q10_tau_m"])
    q10_tau_h_l, q10_tau_h_u = _select(tau_min, tau_max, setups["Q10_tau_h"])
    q10_tau_ca_l, q10_tau_ca_u = _select(tau_min, tau_max, setups["Q10_tau_CaBuff"])
    q10_syn_tau_l, q10_syn_tau_u = _select(tau_min, tau_max, setups["Q10_tau_syn"])

    l_bound = np.concatenate(
        (
            gbar_l,
            syn_l,
            q10_mem_gbar_l,
            q10_syn_gbar_l,
            q10_tau_m_l,
            q10_tau_h_l,
            q10_tau_ca_l,
            q10_syn_tau_l,
        )
    )
    u_bound = np.concatenate(
        (
            gbar_u,
            syn_u,
            q10_mem_gbar_u,
            q10_syn_gbar_u,
            q10_tau_m_u,
            q10_tau_h_u,
            q10_tau_ca_u,
            q10_syn_tau_u,
        )
    )

    return l_bound, u_bound


def _get_min_max_membrane_gbar(selector: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    """
    Returns the lower and upper bound of the maximal membrane conductances.

    These values are the ones used in Goncalves et al. 2020.

    Args:
        selector: Array of bool values of shape (3, 8). Each value indicates whether or
            not to return the corresponding membrane conductance bound.

    Returns:
        A tuple of two 1D arrays (lower and upper bound). They only contain the
        membrane conductances that were selected in the `selector` array.
    """
    # Contains the minimal values that were used by Prinz et al.
    membrane_cond_mins = (
        np.asarray(
            [
                [100, 2.5, 2, 10, 5, 50, 0.01, 0.0],  # PM
                [100, 0.0, 4, 20, 0, 25, 0.0, 0.02],  # LP
                [100, 2.5, 0, 40, 0, 75, 0.0, 0.0],  # PY
            ]
        )
        * 0.628e-3
    )

    # Contains the maximal values that were used by Prinz et al.
    membrane_cond_maxs = (
        np.asarray(
            [
                [400, 5, 6, 50, 10, 125, 0.01, 0.0],  # PM
                [100, 0, 10, 50, 5, 100, 0.05, 0.03],  # LP
                [500, 10, 2, 50, 0, 125, 0.05, 0.03],  # PY
            ]
        )
        * 0.628e-3
    )

    padding = np.asarray([100, 2.5, 2, 10, 5, 25, 0.01, 0.01]) * 0.628e-3
    membrane_cond_mins = membrane_cond_mins - padding
    membrane_cond_maxs = membrane_cond_maxs + padding
    membrane_cond_mins[membrane_cond_mins < 0.0] = 0.0
    use_membrane = np.asarray(selector)
    membrane_used_mins = membrane_cond_mins[use_membrane].flatten()
    membrane_used_maxs = membrane_cond_maxs[use_membrane].flatten()

    return membrane_used_mins, membrane_used_maxs


def _get_min_max_synapse_gbar(min_val, max_val, log_space):
    """
    Return minimum and maximum of the synaptic conductances as used in Goncalves et al.
    """
    syn_dim_mins = np.ones(7) * min_val
    syn_dim_maxs = np.ones(7) * max_val
    syn_dim_maxs[0] *= 10.0

    if log_space:
        syn_dim_mins = np.log(syn_dim_mins)
        syn_dim_maxs = np.log(syn_dim_maxs)
    return syn_dim_mins, syn_dim_maxs


def _select(minimum_val, maximum_val, selector):
    ndims = np.prod(selector.shape)
    min_vals = minimum_val * np.ones(ndims)
    max_vals = maximum_val * np.ones(ndims)
    selected_min_vals = min_vals[selector].flatten()
    selected_max_vals = max_vals[selector].flatten()
    return selected_min_vals, selected_max_vals

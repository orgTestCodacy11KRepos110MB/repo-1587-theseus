# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

from typing import List, Optional, Tuple

import torch

from theseus import CostFunction, CostWeight
from theseus.geometry import LieGroup


class VariableDifference(CostFunction):
    def __init__(
        self,
        var: LieGroup,
        cost_weight: CostWeight,
        target: LieGroup,
        name: Optional[str] = None,
    ):
        super().__init__(cost_weight, name=name)
        if not isinstance(var, target.__class__):
            raise ValueError(
                "Variable for the VariableDifference inconsistent with the given target."
            )
        if not var.dof() == target.dof():
            raise ValueError(
                "Variable and target in the VariableDifference must have identical dof."
            )
        self.var = var
        self.target = target
        self.register_optim_vars(["var"])
        self.register_aux_vars(["target"])

    def error(self) -> torch.Tensor:
        return self.target.local(self.var)

    def jacobians(self) -> Tuple[List[torch.Tensor], torch.Tensor]:
        Jlist: List[torch.Tensor] = []
        self.target.local(self.var, jacobians=Jlist)
        return [Jlist[1]], self.error()

    def dim(self) -> int:
        return self.var.dof()

    def _copy_impl(self, new_name: Optional[str] = None) -> "VariableDifference":
        return VariableDifference(  # type: ignore
            self.var.copy(), self.weight.copy(), self.target.copy(), name=new_name
        )

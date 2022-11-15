# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

from typing import List, Optional
import abc

import torch


class LieGroupFunction:
    @staticmethod
    @abc.abstractmethod
    def check_group_tensor(tensor: torch.Tensor) -> bool:
        pass

    @staticmethod
    @abc.abstractmethod
    def check_tangent_vector(tangent_vector: torch.Tensor) -> bool:
        pass

    @staticmethod
    @abc.abstractmethod
    def check_hat_matrix(matrix: torch.Tensor):
        pass

    @staticmethod
    @abc.abstractmethod
    def rand(
        *size: int,
        generator: Optional[torch.Generator] = None,
        dtype: Optional[torch.dtype] = None,
        device: torch.device = None,
        requires_grad: bool = False,
    ) -> torch.Tensor:
        pass

    @staticmethod
    @abc.abstractmethod
    def randn(
        *size: int,
        generator: Optional[torch.Generator] = None,
        dtype: Optional[torch.dtype] = None,
        device: torch.device = None,
        requires_grad: bool = False,
    ) -> torch.Tensor:
        pass

    @staticmethod
    class project(torch.autograd.Function):
        @staticmethod
        @abc.abstractmethod
        def call(matrix: torch.Tensor) -> torch.Tensor:
            pass

        @staticmethod
        def forward(ctx, matrix):
            return LieGroupFunction.project(matrix)

        @staticmethod
        @abc.abstractmethod
        def backward(ctx, grad_output):
            pass

    @staticmethod
    class left_project(torch.autograd.Function):
        @staticmethod
        def call(group: torch.Tensor, matrix: torch.Tensor) -> torch.Tensor:
            return LieGroupFunction.project.call(
                LieGroupFunction.left_apply.call(
                    LieGroupFunction.inverse.call(group), matrix
                )
            )

        @staticmethod
        def forward(ctx, group, matrix):
            return LieGroupFunction.left_project.call(group, matrix)

    @staticmethod
    class right_project(torch.autograd.Function):
        @staticmethod
        def call(matrix: torch.Tensor, group: torch.Tensor) -> torch.Tensor:
            return LieGroupFunction.project.call(
                LieGroupFunction.right_apply.call(
                    matrix, LieGroupFunction.inverse.call(group)
                )
            )

        @staticmethod
        def forward(ctx, group, matrix):
            return LieGroupFunction.left_project.call(group, matrix)

    class left_apply(torch.autograd.Function):
        @staticmethod
        @abc.abstractmethod
        def call(
            group: torch.Tensor,
            matrix: torch.Tensor,
            jacobians: Optional[List[torch.Tensor]] = None,
        ) -> torch.Tensor:
            pass

        @staticmethod
        @abc.abstractmethod
        def forward(ctx, group, matrix, jacobians):
            pass

        @staticmethod
        @abc.abstractmethod
        def backward(ctx, grad_output):
            pass

    class right_apply(torch.autograd.Function):
        @staticmethod
        @abc.abstractmethod
        def call(
            matrix: torch.Tensor,
            group: torch.Tensor,
            jacobians: Optional[List[torch.Tensor]] = None,
        ) -> torch.Tensor:
            pass

        @staticmethod
        @abc.abstractmethod
        def forward(ctx, matrix, group, jacobians):
            pass

        @staticmethod
        @abc.abstractmethod
        def backward(ctx, grad_output):
            pass

    class hat(torch.autograd.Function):
        @staticmethod
        @abc.abstractmethod
        def call(tangent_vector: torch.Tensor) -> torch.Tensor:
            pass

        @staticmethod
        def forward(ctx, tangent_vector):
            return LieGroupFunction.call(tangent_vector)

        @staticmethod
        @abc.abstractmethod
        def backward(ctx, grad_output):
            pass

    class vee(torch.autograd.Function):
        @staticmethod
        @abc.abstractmethod
        def call(matrix: torch.Tensor) -> torch.Tensor:
            pass

        @staticmethod
        def forward(ctx, matrix):
            return LieGroupFunction.vee.call(matrix)

        @staticmethod
        @abc.abstractmethod
        def backward(ctx, grad_output):
            pass

    class exp_map(torch.autograd.Function):
        @staticmethod
        @abc.abstractmethod
        def call(
            tangent_vector: torch.Tensor,
            jacobians: Optional[List[torch.Tensor]] = None,
        ) -> torch.Tensor:
            pass

        @staticmethod
        @abc.abstractmethod
        def jacobian(tangent_vector: torch.Tensor) -> torch.Tensor:
            pass

        @staticmethod
        @abc.abstractmethod
        def forward(
            ctx,
            tangent_vector,
            jacobians=None,
        ):
            pass

        @staticmethod
        @abc.abstractmethod
        def backward(ctx, grad_output):
            pass

    class adjoint(torch.autograd.Function):
        @staticmethod
        @abc.abstractmethod
        def call(
            g: torch.Tensor,
        ) -> torch.Tensor:
            pass

        @staticmethod
        @abc.abstractmethod
        def forward(ctx, g):
            pass

        @staticmethod
        @abc.abstractmethod
        def backward(ctx, grad_output):
            pass

    class inverse(torch.autograd.Function):
        @staticmethod
        @abc.abstractmethod
        def call(
            g: torch.Tensor, jacobians: Optional[List[torch.Tensor]] = None
        ) -> torch.Tensor:
            pass

        @staticmethod
        @abc.abstractmethod
        def jacobian(g: torch.Tensor) -> torch.Tensor:
            pass

        @staticmethod
        @abc.abstractmethod
        def forward(ctx, g, jacobians=None):
            pass

        @staticmethod
        @abc.abstractmethod
        def backward(ctx, grad_output):
            pass

    class compose(torch.autograd.Function):
        @staticmethod
        @abc.abstractmethod
        def call(
            g0: torch.Tensor,
            g1: torch.Tensor,
            jacobians: Optional[List[torch.Tensor]] = None,
        ) -> torch.Tensor:
            pass

        @staticmethod
        @abc.abstractmethod
        def forward(ctx, g0, g1, jacobians=None):
            pass

        @staticmethod
        @abc.abstractmethod
        def backward(ctx, grad_output):
            pass
